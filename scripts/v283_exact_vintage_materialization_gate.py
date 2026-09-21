from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import duckdb
from huggingface_hub import hf_hub_download

CALENDAR = Path("evidence/V2.7.32_JOINT_A_SHARE_TRADING_CALENDAR_2026.json")
LEDGER = Path("evidence/V2.8.3_PROSPECTIVE_SIGNAL_SOURCE_LEDGER.csv")
FIRST_SIGNAL = date(2026, 9, 22)
SH_TZ = ZoneInfo("Asia/Shanghai")
FIELDS = [
    "signal_date","feature_source_state","source_pin_file","source_pin_commit_sha",
    "source_pin_committed_at_utc","stock_revision_sha","stock_lfs_sha256",
    "benchmark_revision_sha","benchmark_lfs_sha256","stock_max_bar_date",
    "benchmark_max_bar_date","target_d5","target_d10","outcome_d5_state",
    "outcome_d10_state"
]

def sha_file(path: Path) -> str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""):
            h.update(b)
    return h.hexdigest()

def load_calendar():
    obj=json.loads(CALENDAR.read_text(encoding="utf-8"))
    days=[date.fromisoformat(r["date"]) for r in obj["dates"] if r["is_joint_a_share_trading_day"]]
    idx={d:i for i,d in enumerate(days)}
    return days,idx

def target_date(d:date,n:int,days:list[date],idx:dict[date,int]):
    if d not in idx:
        return None
    j=idx[d]+n
    return days[j] if j<len(days) else None

def pin_sources(pin:dict)->dict[str,dict]:
    rows={r["repo_id"]:r for r in pin.get("sources",[])}
    required={"AlphaDojo/dojo_stock_kline","AlphaDojo/dojo_benchmark_kline"}
    if set(rows)!=required:
        raise RuntimeError(f"PIN_SOURCE_SET_INVALID:{sorted(rows)}")
    return rows

def git_creation_identity(pin_path:Path)->tuple[str,datetime]:
    cmd=["git","log","--diff-filter=A","--follow","--format=%H|%cI","--",str(pin_path)]
    out=subprocess.check_output(cmd,text=True).strip().splitlines()
    if not out:
        raise RuntimeError("PIN_GIT_CREATION_NOT_FOUND")
    sha,ts=out[-1].split("|",1)
    dt=datetime.fromisoformat(ts.replace("Z","+00:00"))
    return sha,dt.astimezone(timezone.utc)

def latest_allowed_pin_time(d:date)->datetime:
    local=datetime.combine(d+timedelta(days=1),time(23,59,59),tzinfo=SH_TZ)
    return local.astimezone(timezone.utc)

def materialize_source(src:dict)->Path:
    p=Path(hf_hub_download(
        repo_id=src["repo_id"],
        repo_type="dataset",
        filename=src["target_file"],
        revision=src["revision_sha"],
    ))
    actual=sha_file(p)
    if actual!=src["target_lfs_sha256"]:
        raise RuntimeError(f"SOURCE_BYTES_MISMATCH:{src['repo_id']}:{actual}")
    return p

def inspect_stock(path:Path)->dict:
    con=duckdb.connect()
    try:
        cols={r[0] for r in con.execute(f"DESCRIBE SELECT * FROM read_parquet('{str(path).replace("'","''")}')").fetchall()}
        required={"bar_time","kline_t","market","quote_type"}
        if not required.issubset(cols):
            raise RuntimeError(f"SOURCE_SCHEMA_BLOCKED:stock:{sorted(required-cols)}")
        q=f"""
          SELECT max(cast(bar_time as date)) max_date
          FROM read_parquet('{str(path).replace("'","''")}')
          WHERE cast(kline_t as varchar)='1D'
            AND cast(market as varchar)='cn'
            AND cast(quote_type as varchar)='EQUITY'
        """
        m=con.execute(q).fetchone()[0]
        return {"max_date":str(m) if m else ""}
    finally:
        con.close()

def inspect_benchmark(path:Path,d:date)->dict:
    con=duckdb.connect()
    try:
        esc=str(path).replace("'","''")
        q=f"""
          SELECT cast(bar_time as date) d, cast(close as double) c
          FROM read_parquet('{esc}')
          WHERE cast(symbol as varchar)='000300.SS'
            AND cast(kline_t as varchar)='1D'
          ORDER BY d
        """
        rows=con.execute(q).fetchall()
        if not rows:
            raise RuntimeError("SOURCE_SCHEMA_BLOCKED:benchmark_missing_000300")
        dates=[r[0] for r in rows]
        maxd=max(dates)
        through=[r for r in rows if r[0]<=d and r[1] is not None and float(r[1])>0]
        # 60 daily returns require at least 61 closes ending at D.
        return {"max_date":str(maxd),"history_closes_through_d":len(through)}
    finally:
        con.close()

def evaluate_metadata(d:date,pin_path:Path,pin_commit_time:datetime,stock_max:str,bench_max:str,bench_hist:int)->str:
    days,idx=load_calendar()
    if d<FIRST_SIGNAL:
        return "PRE_CONFIRMATORY_BOUNDARY"
    if d not in idx:
        return "NON_TRADING_SIGNAL_DATE"
    if pin_commit_time>latest_allowed_pin_time(d):
        return "PIN_OBSERVED_AFTER_CUTOFF"
    if stock_max!=d.isoformat():
        return "STOCK_MAX_BAR_DATE_MISMATCH"
    if bench_max!=d.isoformat():
        return "BENCHMARK_MAX_BAR_DATE_MISMATCH"
    if bench_hist<61:
        return "BENCHMARK_WARMUP_INSUFFICIENT"
    return "ELIGIBLE_FEATURE_SOURCE"

def ledger_rows():
    if not LEDGER.exists():
        return []
    return list(csv.DictReader(LEDGER.read_text(encoding="utf-8").splitlines()))

def append_ledger(row:dict):
    existing=ledger_rows()
    if any(r["signal_date"]==row["signal_date"] for r in existing):
        raise RuntimeError("SIGNAL_DATE_ALREADY_ADMITTED_NO_REPLACEMENT")
    LEDGER.parent.mkdir(parents=True,exist_ok=True)
    new_file=not LEDGER.exists()
    with LEDGER.open("a",encoding="utf-8",newline="") as f:
        w=csv.DictWriter(f,fieldnames=FIELDS,lineterminator="\n")
        if new_file:
            w.writeheader()
        w.writerow({k:row.get(k,"") for k in FIELDS})

def gate(signal_date:str,pin_file:str,write:bool):
    d=date.fromisoformat(signal_date)
    p=Path(pin_file)
    pin=json.loads(p.read_text(encoding="utf-8"))
    sources=pin_sources(pin)
    commit_sha,commit_time=git_creation_identity(p)

    stock=materialize_source(sources["AlphaDojo/dojo_stock_kline"])
    bench=materialize_source(sources["AlphaDojo/dojo_benchmark_kline"])
    stock_diag=inspect_stock(stock)
    bench_diag=inspect_benchmark(bench,d)

    state=evaluate_metadata(
        d,p,commit_time,stock_diag["max_date"],bench_diag["max_date"],
        bench_diag["history_closes_through_d"]
    )
    days,idx=load_calendar()
    t5=target_date(d,5,days,idx)
    t10=target_date(d,10,days,idx)
    row={
        "signal_date":d.isoformat(),
        "feature_source_state":state,
        "source_pin_file":str(p),
        "source_pin_commit_sha":commit_sha,
        "source_pin_committed_at_utc":commit_time.isoformat(),
        "stock_revision_sha":sources["AlphaDojo/dojo_stock_kline"]["revision_sha"],
        "stock_lfs_sha256":sources["AlphaDojo/dojo_stock_kline"]["target_lfs_sha256"],
        "benchmark_revision_sha":sources["AlphaDojo/dojo_benchmark_kline"]["revision_sha"],
        "benchmark_lfs_sha256":sources["AlphaDojo/dojo_benchmark_kline"]["target_lfs_sha256"],
        "stock_max_bar_date":stock_diag["max_date"],
        "benchmark_max_bar_date":bench_diag["max_date"],
        "target_d5":t5.isoformat() if t5 else "",
        "target_d10":t10.isoformat() if t10 else "",
        "outcome_d5_state":"OUTCOME_PENDING" if state=="ELIGIBLE_FEATURE_SOURCE" and t5 else "NOT_ADMITTED",
        "outcome_d10_state":"OUTCOME_PENDING" if state=="ELIGIBLE_FEATURE_SOURCE" and t10 else "NOT_ADMITTED",
    }
    if write:
        append_ledger(row)
    print(json.dumps(row,ensure_ascii=False,indent=2))

def self_test():
    days,idx=load_calendar()
    tests=[]
    def ck(name,x): tests.append({"name":name,"pass":bool(x)})
    d=date(2026,9,22)
    ck("M01_first_signal_boundary", evaluate_metadata(
        date(2026,9,21),Path("x"),datetime(2026,9,22,tzinfo=timezone.utc),
        "2026-09-21","2026-09-21",100
    )=="PRE_CONFIRMATORY_BOUNDARY")
    ck("M02_nontrading_block", evaluate_metadata(
        date(2026,9,25),Path("x"),datetime(2026,9,25,tzinfo=timezone.utc),
        "2026-09-25","2026-09-25",100
    )=="NON_TRADING_SIGNAL_DATE")
    ck("M03_cutoff_block", evaluate_metadata(
        d,Path("x"),latest_allowed_pin_time(d)+timedelta(seconds=1),
        d.isoformat(),d.isoformat(),100
    )=="PIN_OBSERVED_AFTER_CUTOFF")
    ck("M04_stock_max_exact", evaluate_metadata(
        d,Path("x"),datetime(2026,9,22,tzinfo=timezone.utc),
        "2026-09-21",d.isoformat(),100
    )=="STOCK_MAX_BAR_DATE_MISMATCH")
    ck("M05_benchmark_max_exact", evaluate_metadata(
        d,Path("x"),datetime(2026,9,22,tzinfo=timezone.utc),
        d.isoformat(),"2026-09-21",100
    )=="BENCHMARK_MAX_BAR_DATE_MISMATCH")
    ck("M06_warmup_gate", evaluate_metadata(
        d,Path("x"),datetime(2026,9,22,tzinfo=timezone.utc),
        d.isoformat(),d.isoformat(),60
    )=="BENCHMARK_WARMUP_INSUFFICIENT")
    ck("M07_eligible", evaluate_metadata(
        d,Path("x"),datetime(2026,9,22,tzinfo=timezone.utc),
        d.isoformat(),d.isoformat(),61
    )=="ELIGIBLE_FEATURE_SOURCE")
    ck("M08_d5_frozen", target_date(d,5,days,idx)==date(2026,9,30))
    ck("M09_d10_frozen", target_date(d,10,days,idx)==date(2026,10,14))
    result={"schema":"AI_CORE_EVID_V2_8_3_MATERIALIZATION_GATE_SELFTEST_V1",
            "passed":sum(x["pass"] for x in tests),"total":len(tests),
            "all_pass":all(x["pass"] for x in tests),"tests":tests}
    print(json.dumps(result,ensure_ascii=False,indent=2))
    if not result["all_pass"]:
        raise SystemExit(2)

def main():
    ap=argparse.ArgumentParser()
    sub=ap.add_subparsers(dest="cmd",required=True)
    sub.add_parser("self-test")
    g=sub.add_parser("gate")
    g.add_argument("--signal-date",required=True)
    g.add_argument("--pin-file",required=True)
    g.add_argument("--write-ledger",action="store_true")
    a=ap.parse_args()
    if a.cmd=="self-test":
        self_test()
    else:
        gate(a.signal_date,a.pin_file,a.write_ledger)

if __name__=="__main__":
    main()
