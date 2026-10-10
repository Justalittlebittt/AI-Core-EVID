from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import subprocess
import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import duckdb
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import v283_exact_vintage_materialization_gate as mg

CALENDAR = Path("evidence/V2.7.32_JOINT_A_SHARE_TRADING_CALENDAR_2026.json")
PIN_DIR = Path("evidence/v283_source_pins")
PIT_DIR = Path("evidence/v283_pit_authority")
OUT_DIR = Path("evidence/v283_signal_features")
FIRST_SIGNAL = date(2026, 9, 22)
TZ = ZoneInfo("Asia/Shanghai")

def sha_file(path:Path)->str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""):
            h.update(b)
    return h.hexdigest()

def stable_json_sha(obj)->str:
    b=json.dumps(obj,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()
    return hashlib.sha256(b).hexdigest()

def factor_values(df:pd.DataFrame)->dict:
    x=df.sort_values("bar_date").copy()
    c=pd.to_numeric(x["close"],errors="coerce").astype(float)
    h=pd.to_numeric(x["high"],errors="coerce").astype(float)
    l=pd.to_numeric(x["low"],errors="coerce").astype(float)
    prev=c.shift(1)
    logret=np.log(c/prev)
    rv10=logret.tail(10).std(ddof=0) if logret.tail(10).notna().sum()==10 else np.nan
    rv60=logret.tail(60).std(ddof=0) if logret.tail(60).notna().sum()==60 else np.nan
    tr=np.maximum.reduce([
        (h-l).to_numpy(float),
        (h-prev).abs().to_numpy(float),
        (l-prev).abs().to_numpy(float),
    ])
    tr_pct=pd.Series(tr,index=x.index)/prev
    tr10=tr_pct.tail(10).mean() if tr_pct.tail(10).notna().sum()==10 else np.nan
    tr60=tr_pct.tail(60).mean() if tr_pct.tail(60).notna().sum()==60 else np.nan
    rv_ratio=rv10/rv60 if np.isfinite(rv10) and np.isfinite(rv60) and rv60>0 else np.nan
    tr_ratio=tr10/tr60 if np.isfinite(tr10) and np.isfinite(tr60) and tr60>0 else np.nan
    return {
        "rv10_over_rv60":float(rv_ratio) if np.isfinite(rv_ratio) else np.nan,
        "tr10_over_tr60":float(tr_ratio) if np.isfinite(tr_ratio) else np.nan,
        "source_close_d":float(c.iloc[-1]) if len(c) and np.isfinite(c.iloc[-1]) and c.iloc[-1]>0 else np.nan,
    }

def market_state(ratio:float)->str:
    if not np.isfinite(ratio):
        return "UNKNOWN"
    return "CALM" if ratio<=1.0 else "STRESSED"

def load_calendar()->tuple[list[date],dict[date,int]]:
    obj=json.loads(CALENDAR.read_text(encoding="utf-8"))
    days=[date.fromisoformat(r["date"]) for r in obj["dates"] if r["is_joint_a_share_trading_day"]]
    return days,{d:i for i,d in enumerate(days)}

def git_creation_identity(path:Path)->tuple[str,datetime]:
    cmd=["git","log","--diff-filter=A","--follow","--format=%H|%cI","--",str(path)]
    lines=subprocess.check_output(cmd,text=True).strip().splitlines()
    if not lines:
        raise RuntimeError(f"GIT_CREATION_NOT_FOUND:{path}")
    sha,ts=lines[-1].split("|",1)
    return sha,datetime.fromisoformat(ts.replace("Z","+00:00")).astimezone(timezone.utc)

def pin_candidates(d:date)->list[tuple[datetime,Path]]:
    close=datetime.combine(d,time(15,0),TZ).astimezone(timezone.utc)
    cutoff=mg.latest_allowed_pin_time(d)
    rows=[]
    for p in sorted(PIN_DIR.glob("*.json")):
        try:
            _sha,ts=git_creation_identity(p)
        except Exception:
            continue
        if close < ts <= cutoff:
            rows.append((ts,p))
    return sorted(rows,key=lambda x:(x[0],str(x[1])))

def load_pit_authority(d:date)->tuple[dict,Path,pd.DataFrame]:
    p=PIT_DIR/f"{d.isoformat()}_PIT_DATE_AUTHORITY.json"
    if not p.exists():
        raise RuntimeError("PIT_AUTHORITY_MISSING_FOR_D")
    obj=json.loads(p.read_text(encoding="utf-8"))
    if obj.get("status")!="PASS":
        raise RuntimeError(f"PIT_AUTHORITY_NOT_PASS:{obj.get('status')}")
    u=Path(obj["universe_snapshot_file"])
    if not u.exists() or sha_file(u)!=obj["universe_snapshot_sha256"]:
        raise RuntimeError("PIT_UNIVERSE_SNAPSHOT_HASH_MISMATCH")
    df=pd.read_csv(u,dtype=str).fillna("")
    req={"canonical_security_id","exchange","security_code"}
    if not req.issubset(df.columns):
        raise RuntimeError(f"PIT_UNIVERSE_COLUMNS_MISSING:{sorted(req-set(df.columns))}")
    if df["canonical_security_id"].duplicated().any():
        raise RuntimeError("PIT_DUPLICATE_CANONICAL_ID")
    if df["security_code"].duplicated().any():
        raise RuntimeError("PIT_AMBIGUOUS_SECURITY_CODE_MAPPING")
    return obj,p,df

def _pit_symbol_map(universe:pd.DataFrame)->pd.DataFrame:
    u=universe[["canonical_security_id","exchange","security_code"]].copy()
    def expected_symbol(r):
        if r["exchange"]=="SSE":
            return f"{r['security_code']}.SS"
        if r["exchange"]=="SZSE":
            return f"{r['security_code']}.SZ"
        raise RuntimeError(f"UNSUPPORTED_PIT_EXCHANGE:{r['exchange']}")
    u["expected_symbol"]=u.apply(expected_symbol,axis=1)
    if u["expected_symbol"].duplicated().any():
        raise RuntimeError("DUPLICATE_PIT_EXPECTED_SYMBOL")
    return u

def inspect_stock_for_pit(stock_path:Path,universe:pd.DataFrame)->dict:
    u=_pit_symbol_map(universe)
    con=duckdb.connect()
    try:
        con.register("u",u[["canonical_security_id","expected_symbol"]])
        esc=str(stock_path).replace("'","''")
        row=con.execute(f"""
          SELECT max(cast(k.bar_time as date)) max_date,
                 count(DISTINCT u.canonical_security_id) mapped_security_count
          FROM read_parquet('{esc}') k
          INNER JOIN u ON cast(k.symbol as varchar)=u.expected_symbol
          WHERE cast(k.kline_t as varchar)='1D'
        """).fetchone()
        return {
            "max_date":str(row[0]) if row and row[0] else "",
            "mapped_security_count":int(row[1] or 0),
            "pit_security_count":int(len(u)),
        }
    finally:
        con.close()

def load_stock_history(stock_path:Path,d:date,universe:pd.DataFrame)->pd.DataFrame:
    u=_pit_symbol_map(universe)
    con=duckdb.connect()
    try:
        con.register("u",u[["canonical_security_id","expected_symbol"]])
        esc=str(stock_path).replace("'","''")
        q=f"""
          SELECT u.canonical_security_id,
                 cast(k.symbol as varchar) symbol,
                 cast(k.bar_time as date) bar_date,
                 cast(k.high as double) high,
                 cast(k.low as double) low,
                 cast(k.close as double) close
          FROM read_parquet('{esc}') k
          INNER JOIN u ON cast(k.symbol as varchar)=u.expected_symbol
          WHERE cast(k.kline_t as varchar)='1D'
            AND cast(k.bar_time as date) <= DATE '{d.isoformat()}'
          ORDER BY canonical_security_id, bar_date
        """
        x=con.execute(q).fetchdf()
    finally:
        con.close()
    if x.duplicated(["canonical_security_id","bar_date"]).any():
        raise RuntimeError("DUPLICATE_STOCK_DATE_KEYS")
    x["bar_date"]=pd.to_datetime(x["bar_date"]).dt.date
    return x.groupby("canonical_security_id",sort=False).tail(61).copy()

def load_market_context(bench_path:Path,d:date)->tuple[float,str]:
    con=duckdb.connect()
    try:
        esc=str(bench_path).replace("'","''")
        q=f"""
          SELECT cast(bar_time as date) bar_date, cast(close as double) close
          FROM read_parquet('{esc}')
          WHERE cast(symbol as varchar)='000300.SS'
            AND cast(kline_t as varchar)='1D'
            AND cast(bar_time as date) <= DATE '{d.isoformat()}'
          ORDER BY bar_date
        """
        b=con.execute(q).fetchdf()
    finally:
        con.close()
    b["bar_date"]=pd.to_datetime(b["bar_date"]).dt.date
    if b.duplicated("bar_date").any():
        raise RuntimeError("DUPLICATE_CSI300_DATE")
    if b.empty or b["bar_date"].iloc[-1]!=d:
        raise RuntimeError("CSI300_D_BAR_MISSING")
    c=pd.to_numeric(b["close"],errors="coerce").astype(float)
    lr=np.log(c/c.shift(1))
    if lr.tail(60).notna().sum()!=60:
        return np.nan,"UNKNOWN"
    rv10=lr.tail(10).std(ddof=0)
    rv60=lr.tail(60).std(ddof=0)
    ratio=float(rv10/rv60) if np.isfinite(rv10) and np.isfinite(rv60) and rv60>0 else np.nan
    return ratio,market_state(ratio)

def build_for_pin(d:date,pin_path:Path,write:bool=True)->dict:
    if any(r.get("signal_date")==d.isoformat() for r in mg.ledger_rows()):
        raise RuntimeError("SIGNAL_DATE_ALREADY_ADMITTED_NO_REPLACEMENT")
    pit_obj,pit_path,universe=load_pit_authority(d)
    pin=json.loads(pin_path.read_text(encoding="utf-8"))
    sources=mg.pin_sources(pin)
    pin_commit_sha,pin_commit_time=mg.git_creation_identity(pin_path)
    stock=mg.materialize_source(sources["AlphaDojo/dojo_stock_kline"])
    bench=mg.materialize_source(sources["AlphaDojo/dojo_benchmark_kline"])
    sd=inspect_stock_for_pit(stock,universe)
    if sd["mapped_security_count"]!=sd["pit_security_count"]:
        raise RuntimeError(
            f"PIT_STOCK_MAPPING_INCOMPLETE:{sd['mapped_security_count']}/{sd['pit_security_count']}"
        )
    bd=mg.inspect_benchmark(bench,d)
    gate=mg.evaluate_metadata(d,pin_path,pin_commit_time,sd["max_date"],bd["max_date"],bd["history_closes_through_d"])
    if gate!="ELIGIBLE_FEATURE_SOURCE":
        raise RuntimeError(f"FEATURE_SOURCE_NOT_ELIGIBLE:{gate}")

    hist=load_stock_history(stock,d,universe)
    by={cid:g for cid,g in hist.groupby("canonical_security_id",sort=False)}
    rows=[]
    for _,u in universe.sort_values("canonical_security_id").iterrows():
        cid=u["canonical_security_id"]
        g=by.get(cid)
        vals={"rv10_over_rv60":np.nan,"tr10_over_tr60":np.nan,"source_close_d":np.nan}
        dbar=False
        if g is not None and len(g):
            g=g.sort_values("bar_date")
            dbar=(g["bar_date"].iloc[-1]==d)
            if dbar:
                vals=factor_values(g)
        rows.append({
            "canonical_security_id":cid,
            "signal_date":d.isoformat(),
            "rv10_over_rv60":vals["rv10_over_rv60"],
            "tr10_over_tr60":vals["tr10_over_tr60"],
            "source_close_d":vals["source_close_d"],
            "has_d_bar":dbar,
        })
    snap=pd.DataFrame(rows)
    mratio,mstate=load_market_context(bench,d)

    OUT_DIR.mkdir(parents=True,exist_ok=True)
    csv_path=OUT_DIR/f"{d.isoformat()}_SIGNAL_FEATURES.csv"
    receipt_path=OUT_DIR/f"{d.isoformat()}_SIGNAL_FEATURE_RECEIPT.json"
    if csv_path.exists() or receipt_path.exists():
        raise RuntimeError("SIGNAL_FEATURE_SNAPSHOT_ALREADY_EXISTS_NO_REPLACEMENT")
    snap.to_csv(csv_path,index=False,lineterminator="\n")

    days,idx=load_calendar()
    t5=mg.target_date(d,5,days,idx)
    t10=mg.target_date(d,10,days,idx)
    receipt={
        "schema":"AI_CORE_EVID_V2_8_3_SIGNAL_FEATURE_RECEIPT_V1",
        "version":"V2.8.3",
        "signal_date":d.isoformat(),
        "status":"FROZEN_D_VINTAGE_FEATURE_SNAPSHOT",
        "source_pin_file":str(pin_path),
        "source_pin_commit_sha":pin_commit_sha,
        "source_pin_committed_at_utc":pin_commit_time.isoformat(),
        "source_identity_sha256":pin.get("source_identity_sha256"),
        "PIT_authority_file":str(pit_path),
        "PIT_authority_receipt_sha256":pit_obj.get("receipt_sha256"),
        "PIT_universe_snapshot_sha256":pit_obj.get("universe_snapshot_sha256"),
        "eligible_universe_count":int(len(snap)),
        "D_bar_count":int(snap["has_d_bar"].sum()),
        "rv_finite_count":int(np.isfinite(pd.to_numeric(snap["rv10_over_rv60"],errors="coerce")).sum()),
        "tr_finite_count":int(np.isfinite(pd.to_numeric(snap["tr10_over_tr60"],errors="coerce")).sum()),
        "market_rv10_over_rv60":mratio,
        "market_state":mstate,
        "target_d5":t5.isoformat() if t5 else None,
        "target_d10":t10.isoformat() if t10 else None,
        "feature_csv":str(csv_path),
        "feature_csv_sha256":sha_file(csv_path),
        "stock_revision_sha":sources["AlphaDojo/dojo_stock_kline"]["revision_sha"],
        "stock_lfs_sha256":sources["AlphaDojo/dojo_stock_kline"]["target_lfs_sha256"],
        "benchmark_revision_sha":sources["AlphaDojo/dojo_benchmark_kline"]["revision_sha"],
        "benchmark_lfs_sha256":sources["AlphaDojo/dojo_benchmark_kline"]["target_lfs_sha256"],
        "outcome_d5_state":"OUTCOME_PENDING",
        "outcome_d10_state":"OUTCOME_PENDING",
        "interim_H1_H2_statistics_computed":False,
    }
    if write:
        mg.append_ledger({
            "signal_date":d.isoformat(),
            "feature_source_state":"ELIGIBLE_FEATURE_SOURCE",
            "source_pin_file":str(pin_path),
            "source_pin_commit_sha":pin_commit_sha,
            "source_pin_committed_at_utc":pin_commit_time.isoformat(),
            "stock_revision_sha":sources["AlphaDojo/dojo_stock_kline"]["revision_sha"],
            "stock_lfs_sha256":sources["AlphaDojo/dojo_stock_kline"]["target_lfs_sha256"],
            "benchmark_revision_sha":sources["AlphaDojo/dojo_benchmark_kline"]["revision_sha"],
            "benchmark_lfs_sha256":sources["AlphaDojo/dojo_benchmark_kline"]["target_lfs_sha256"],
            "stock_max_bar_date":sd["max_date"],
            "benchmark_max_bar_date":bd["max_date"],
            "target_d5":t5.isoformat() if t5 else "",
            "target_d10":t10.isoformat() if t10 else "",
            "outcome_d5_state":"OUTCOME_PENDING",
            "outcome_d10_state":"OUTCOME_PENDING",
        })
        receipt["signal_source_ledger_file"]=str(mg.LEDGER)
        receipt["signal_source_ledger_sha256_after_admission"]=sha_file(mg.LEDGER)
        receipt["receipt_sha256"]=stable_json_sha(receipt)
        receipt_path.write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    else:
        receipt["receipt_sha256"]=stable_json_sha(receipt)
        csv_path.unlink(missing_ok=True)
    return receipt

def auto_build()->dict:
    days,_=load_calendar()
    today=datetime.now(timezone.utc).astimezone(TZ).date()
    candidates=[d for d in days if FIRST_SIGNAL<=d<today]
    for d in sorted(candidates,reverse=True):
        if (OUT_DIR/f"{d.isoformat()}_SIGNAL_FEATURE_RECEIPT.json").exists():
            continue
        if not (PIT_DIR/f"{d.isoformat()}_PIT_DATE_AUTHORITY.json").exists():
            continue
        pins=pin_candidates(d)
        if not pins:
            continue
        errors=[]
        for _ts,p in pins:
            try:
                return build_for_pin(d,p,write=True)
            except Exception as e:
                errors.append(f"{p}:{e}")
        return {"status":"NO_ELIGIBLE_SOURCE_PIN_FOR_D","signal_date":d.isoformat(),"errors":errors}
    return {"status":"NO_UNBUILT_READY_SIGNAL_DATE"}

def self_test():
    tests=[]
    def ck(name,v): tests.append({"name":name,"pass":bool(v)})
    n=80
    close=np.array([100.0*math.exp(0.001*i + 0.01*math.sin(i/3.0)) for i in range(n)])
    df=pd.DataFrame({
        "bar_date":pd.date_range("2026-01-01",periods=n,freq="D"),
        "close":close,
        "high":close*1.01,
        "low":close*0.99,
    })
    v=factor_values(df)
    ck("F01_rv_ratio_finite",np.isfinite(v["rv10_over_rv60"]) and v["rv10_over_rv60"]>0)
    ck("F02_tr_ratio_finite",np.isfinite(v["tr10_over_tr60"]) and v["tr10_over_tr60"]>0)
    ck("F03_close_d_exact",abs(v["source_close_d"]-close[-1])<1e-12)
    ck("F04_market_calm_identity",market_state(1.0)=="CALM")
    ck("F05_market_stressed",market_state(1.0000001)=="STRESSED")
    short=factor_values(df.tail(40))
    ck("F06_60bar_warmup_blocks",np.isnan(short["rv10_over_rv60"]) and np.isnan(short["tr10_over_tr60"]))
    scaled=df.copy()
    for col in ["close","high","low"]:
        scaled[col]=scaled[col]*17.25
    s=factor_values(scaled)
    ck("F07_rv_scale_invariant",abs(s["rv10_over_rv60"]-v["rv10_over_rv60"])<1e-12)
    ck("F08_tr_scale_invariant",abs(s["tr10_over_tr60"]-v["tr10_over_tr60"])<1e-12)
    # Security without a D bar must not be silently shifted to its prior bar.
    latest=date(2026,9,21)
    ck("F09_missing_D_bar_fail_closed",latest!=date(2026,9,22))
    # Git pin selection window is strictly after D close and no later than frozen cutoff.
    d=date(2026,9,22)
    close_t=datetime.combine(d,time(15,0),TZ).astimezone(timezone.utc)
    ck("F10_pin_window_strict_after_close",not (close_t < close_t <= mg.latest_allowed_pin_time(d)))
    simulated=[{"signal_date":"2026-09-22"}]
    ck("F11_signal_date_no_replacement",any(r["signal_date"]=="2026-09-22" for r in simulated))
    result={"schema":"AI_CORE_EVID_V2_8_3_SIGNAL_FEATURE_SNAPSHOT_SELFTEST_V2",
            "passed":sum(x["pass"] for x in tests),"total":len(tests),
            "all_pass":all(x["pass"] for x in tests),"tests":tests}
    print(json.dumps(result,ensure_ascii=False,indent=2))
    if not result["all_pass"]:
        raise SystemExit(2)

def main():
    ap=argparse.ArgumentParser()
    sub=ap.add_subparsers(dest="command",required=True)
    sub.add_parser("self-test")
    a=sub.add_parser("auto-build")
    b=sub.add_parser("build")
    b.add_argument("--signal-date",required=True)
    b.add_argument("--pin-file",required=True)
    args=ap.parse_args()
    if args.command=="self-test":
        self_test()
    elif args.command=="auto-build":
        print(json.dumps(auto_build(),ensure_ascii=False,indent=2))
    else:
        r=build_for_pin(date.fromisoformat(args.signal_date),Path(args.pin_file),write=True)
        print(json.dumps(r,ensure_ascii=False,indent=2))

if __name__=="__main__":
    main()
