from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import v283_exact_vintage_materialization_gate as mg
import v283_signal_feature_snapshot as sf

SIGNAL_DIR=Path("evidence/v283_signal_features")
OUT_DIR=Path("evidence/v283_outcomes")
OUTCOME_LEDGER=Path("evidence/V2.8.3_PROSPECTIVE_OUTCOME_LEDGER.csv")
FIELDS=[
    "signal_date","horizon","target_date","outcome_state","T_source_pin_file",
    "T_source_pin_commit_sha","T_source_pin_committed_at_utc","stock_revision_sha",
    "stock_lfs_sha256","outcome_csv","outcome_csv_sha256","resolved_count",
    "unavailable_count"
]

def sha_file(path:Path)->str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""):
            h.update(b)
    return h.hexdigest()

def stable_json_sha(obj)->str:
    b=json.dumps(obj,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()
    return hashlib.sha256(b).hexdigest()

def economic_return_same_vintage(close_d,close_t):
    try:
        d=float(close_d); t=float(close_t)
    except Exception:
        return np.nan
    if not np.isfinite(d) or not np.isfinite(t) or d<=0 or t<=0:
        return np.nan
    return t/d-1.0

def ledger_rows():
    if not OUTCOME_LEDGER.exists():
        return []
    return list(csv.DictReader(OUTCOME_LEDGER.read_text(encoding="utf-8").splitlines()))

def append_ledger(row:dict):
    existing=ledger_rows()
    key=(row["signal_date"],row["horizon"])
    if any((r["signal_date"],r["horizon"])==key for r in existing):
        raise RuntimeError("OUTCOME_ALREADY_RESOLVED_NO_REPLACEMENT")
    new=not OUTCOME_LEDGER.exists()
    with OUTCOME_LEDGER.open("a",encoding="utf-8",newline="") as f:
        w=csv.DictWriter(f,fieldnames=FIELDS,lineterminator="\n")
        if new: w.writeheader()
        w.writerow({k:row.get(k,"") for k in FIELDS})

def load_signal_receipt(d:date)->dict:
    p=SIGNAL_DIR/f"{d.isoformat()}_SIGNAL_FEATURE_RECEIPT.json"
    if not p.exists():
        raise RuntimeError("SIGNAL_FEATURE_RECEIPT_MISSING")
    obj=json.loads(p.read_text(encoding="utf-8"))
    if obj.get("status")!="FROZEN_D_VINTAGE_FEATURE_SNAPSHOT":
        raise RuntimeError("SIGNAL_FEATURE_RECEIPT_NOT_FROZEN")
    feature=Path(obj["feature_csv"])
    if not feature.exists() or sha_file(feature)!=obj["feature_csv_sha256"]:
        raise RuntimeError("SIGNAL_FEATURE_CSV_HASH_MISMATCH")
    return obj

def load_d_universe(signal_receipt:dict)->pd.DataFrame:
    pit=Path(signal_receipt["PIT_authority_file"])
    pobj=json.loads(pit.read_text(encoding="utf-8"))
    if pobj.get("status")!="PASS":
        raise RuntimeError("D_PIT_AUTHORITY_NOT_PASS")
    u=Path(pobj["universe_snapshot_file"])
    if not u.exists() or sha_file(u)!=pobj["universe_snapshot_sha256"]:
        raise RuntimeError("D_PIT_UNIVERSE_HASH_MISMATCH")
    x=pd.read_csv(u,dtype=str).fillna("")
    if x["canonical_security_id"].duplicated().any() or x["security_code"].duplicated().any():
        raise RuntimeError("D_PIT_UNIVERSE_MAPPING_AMBIGUOUS")
    return x[["canonical_security_id","security_code"]].copy()

def load_endpoints(stock_path:Path,d:date,t:date,universe:pd.DataFrame)->pd.DataFrame:
    con=duckdb.connect()
    try:
        con.register("u",universe)
        esc=str(stock_path).replace("'","''")
        q=f"""
          SELECT u.canonical_security_id,
                 cast(k.bar_time as date) bar_date,
                 cast(k.close as double) close
          FROM read_parquet('{esc}') k
          INNER JOIN u ON cast(k.symbol as varchar)=u.security_code
          WHERE cast(k.kline_t as varchar)='1D'
            AND cast(k.market as varchar)='cn'
            AND cast(k.quote_type as varchar)='EQUITY'
            AND cast(k.bar_time as date) IN (DATE '{d.isoformat()}', DATE '{t.isoformat()}')
          ORDER BY canonical_security_id, bar_date
        """
        x=con.execute(q).fetchdf()
    finally:
        con.close()
    x["bar_date"]=pd.to_datetime(x["bar_date"]).dt.date
    if x.duplicated(["canonical_security_id","bar_date"]).any():
        raise RuntimeError("DUPLICATE_ENDPOINT_KEY")
    dpx=x[x["bar_date"]==d][["canonical_security_id","close"]].rename(columns={"close":"close_d_same_T_vintage"})
    tpx=x[x["bar_date"]==t][["canonical_security_id","close"]].rename(columns={"close":"close_t_same_T_vintage"})
    out=universe[["canonical_security_id"]].merge(dpx,on="canonical_security_id",how="left",validate="one_to_one")
    out=out.merge(tpx,on="canonical_security_id",how="left",validate="one_to_one")
    return out

def eligible_T_pin(t:date):
    errors=[]
    for _ts,p in sf.pin_candidates(t):
        try:
            pin=json.loads(p.read_text(encoding="utf-8"))
            sources=mg.pin_sources(pin)
            commit_sha,commit_time=mg.git_creation_identity(p)
            stock=mg.materialize_source(sources["AlphaDojo/dojo_stock_kline"])
            bench=mg.materialize_source(sources["AlphaDojo/dojo_benchmark_kline"])
            sd=mg.inspect_stock(stock)
            bd=mg.inspect_benchmark(bench,t)
            gate=mg.evaluate_metadata(t,p,commit_time,sd["max_date"],bd["max_date"],bd["history_closes_through_d"])
            if gate!="ELIGIBLE_FEATURE_SOURCE":
                errors.append(f"{p}:{gate}")
                continue
            return p,pin,sources,commit_sha,commit_time,stock
        except Exception as e:
            errors.append(f"{p}:{e}")
    return None,errors

def resolve_one(d:date,horizon:str)->dict:
    if horizon not in {"D5","D10"}:
        raise RuntimeError("INVALID_HORIZON")
    if any(r["signal_date"]==d.isoformat() and r["horizon"]==horizon for r in ledger_rows()):
        raise RuntimeError("OUTCOME_ALREADY_RESOLVED_NO_REPLACEMENT")
    sr=load_signal_receipt(d)
    target_key="target_d5" if horizon=="D5" else "target_d10"
    t=date.fromisoformat(sr[target_key])
    today=datetime.now(timezone.utc).astimezone(sf.TZ).date()
    if t>=today:
        return {"status":"OUTCOME_PENDING","signal_date":d.isoformat(),"horizon":horizon,"target_date":t.isoformat()}
    found=eligible_T_pin(t)
    if found[0] is None:
        return {"status":"OUTCOME_PENDING_NO_ELIGIBLE_T_PIN","signal_date":d.isoformat(),"horizon":horizon,"target_date":t.isoformat(),"errors":found[1]}
    p,pin,sources,commit_sha,commit_time,stock=found
    universe=load_d_universe(sr)
    x=load_endpoints(stock,d,t,universe)
    x["signal_date"]=d.isoformat()
    x["target_date"]=t.isoformat()
    x["fwd_return"]=[economic_return_same_vintage(a,b) for a,b in zip(x["close_d_same_T_vintage"],x["close_t_same_T_vintage"])]
    x["outcome_state"]=np.where(np.isfinite(x["fwd_return"]),"RESOLVED","OUTCOME_UNAVAILABLE_NO_SHIFT")
    x=x[["canonical_security_id","signal_date","target_date","close_d_same_T_vintage","close_t_same_T_vintage","fwd_return","outcome_state"]]

    OUT_DIR.mkdir(parents=True,exist_ok=True)
    csv_path=OUT_DIR/f"{d.isoformat()}_{horizon}_OUTCOMES.csv"
    receipt_path=OUT_DIR/f"{d.isoformat()}_{horizon}_OUTCOME_RECEIPT.json"
    if csv_path.exists() or receipt_path.exists():
        raise RuntimeError("OUTCOME_ARTIFACT_ALREADY_EXISTS_NO_REPLACEMENT")
    x.to_csv(csv_path,index=False,lineterminator="\n")
    resolved=int((x["outcome_state"]=="RESOLVED").sum())
    unavailable=int((x["outcome_state"]=="OUTCOME_UNAVAILABLE_NO_SHIFT").sum())
    row={
        "signal_date":d.isoformat(),
        "horizon":horizon,
        "target_date":t.isoformat(),
        "outcome_state":"RESOLVED_WITH_EXPLICIT_UNAVAILABLE_ROWS",
        "T_source_pin_file":str(p),
        "T_source_pin_commit_sha":commit_sha,
        "T_source_pin_committed_at_utc":commit_time.isoformat(),
        "stock_revision_sha":sources["AlphaDojo/dojo_stock_kline"]["revision_sha"],
        "stock_lfs_sha256":sources["AlphaDojo/dojo_stock_kline"]["target_lfs_sha256"],
        "outcome_csv":str(csv_path),
        "outcome_csv_sha256":sha_file(csv_path),
        "resolved_count":resolved,
        "unavailable_count":unavailable,
    }
    append_ledger(row)
    receipt={
        "schema":"AI_CORE_EVID_V2_8_3_OUTCOME_RESOLUTION_RECEIPT_V1",
        "version":"V2.8.3",
        **row,
        "D_feature_receipt_sha256":sr["receipt_sha256"],
        "economic_price_rule":"D_AND_T_ENDPOINTS_FROM_SAME_T_VINTAGE",
        "D_vintage_source_close_used_for_return":False,
        "target_shift_used":False,
        "outcome_ledger_sha256_after_append":sha_file(OUTCOME_LEDGER),
        "interim_H1_H2_statistics_computed":False,
    }
    receipt["receipt_sha256"]=stable_json_sha(receipt)
    receipt_path.write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return receipt

def auto_resolve()->dict:
    today=datetime.now(timezone.utc).astimezone(sf.TZ).date()
    done={(r["signal_date"],r["horizon"]) for r in ledger_rows()}
    actions=[]
    for p in sorted(SIGNAL_DIR.glob("*_SIGNAL_FEATURE_RECEIPT.json")):
        sr=json.loads(p.read_text(encoding="utf-8"))
        d=date.fromisoformat(sr["signal_date"])
        for horizon,key in (("D5","target_d5"),("D10","target_d10")):
            if (d.isoformat(),horizon) in done:
                continue
            t=date.fromisoformat(sr[key])
            if t>=today:
                continue
            r=resolve_one(d,horizon)
            actions.append(r)
    return {"status":"OUTCOME_RESOLUTION_SCAN_COMPLETE","actions":actions}

def self_test():
    tests=[]
    def ck(name,v): tests.append({"name":name,"pass":bool(v)})
    ck("O01_same_vintage_return",abs(economic_return_same_vintage(100,110)-0.10)<1e-12)
    wrong=110/50-1
    correct=economic_return_same_vintage(100,110)
    ck("O02_scale_drift_counterexample_detected",abs(wrong-1.2)<1e-12 and abs(correct-0.1)<1e-12)
    ck("O03_missing_D_unavailable",np.isnan(economic_return_same_vintage(np.nan,110)))
    ck("O04_missing_T_unavailable",np.isnan(economic_return_same_vintage(100,np.nan)))
    ck("O05_nonpositive_D_unavailable",np.isnan(economic_return_same_vintage(0,110)))
    ck("O06_nonpositive_T_unavailable",np.isnan(economic_return_same_vintage(100,0)))
    sim=[("2026-09-22","D5")]
    ck("O07_unique_signal_horizon_no_replacement",("2026-09-22","D5") in sim)
    days,idx=mg.load_calendar()
    d=date(2026,9,22)
    ck("O08_d5_target_frozen",mg.target_date(d,5,days,idx)==date(2026,9,30))
    ck("O09_d10_target_frozen",mg.target_date(d,10,days,idx)==date(2026,10,14))
    with OUTCOME_LEDGER.open("r",encoding="utf-8",newline="") as f:
        header=next(csv.reader(f))
    ck("O10_outcome_ledger_header_exact",header==FIELDS)
    result={"schema":"AI_CORE_EVID_V2_8_3_OUTCOME_RESOLVER_SELFTEST_V1","tests":tests,
            "passed":sum(x["pass"] for x in tests),"total":len(tests),"all_pass":all(x["pass"] for x in tests)}
    result["receipt_sha256"]=stable_json_sha(result)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    if not result["all_pass"]:
        raise SystemExit(2)

def main():
    ap=argparse.ArgumentParser()
    sub=ap.add_subparsers(dest="command",required=True)
    sub.add_parser("self-test")
    sub.add_parser("auto-resolve")
    r=sub.add_parser("resolve")
    r.add_argument("--signal-date",required=True)
    r.add_argument("--horizon",choices=["D5","D10"],required=True)
    a=ap.parse_args()
    if a.command=="self-test":
        self_test()
    elif a.command=="auto-resolve":
        print(json.dumps(auto_resolve(),ensure_ascii=False,indent=2))
    else:
        print(json.dumps(resolve_one(date.fromisoformat(a.signal_date),a.horizon),ensure_ascii=False,indent=2))

if __name__=="__main__":
    main()
