from __future__ import annotations

import argparse
import ast
import hashlib
import json
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

SIGNAL_DIR=Path("evidence/v283_signal_features")
OUTCOME_DIR=Path("evidence/v283_outcomes")
OUT=Path("evidence/V2.8.3_INFORMATION_GATE_STATUS.json")
HYPOTHESES=[
    ("H1_RV_COMPRESSION_CALM","rv10_over_rv60"),
    ("H2_TR_COMPRESSION_CALM","tr10_over_tr60"),
]
MIN_ROWS=50
MIN_CALM=60
MIN_STRESSED=30
MIN_QUARTERS=3
MIN_CALM_PER_QUARTER=15

def stable_json_sha(obj)->str:
    b=json.dumps(obj,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()
    return hashlib.sha256(b).hexdigest()

def sha_file(path:Path)->str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""):
            h.update(b)
    return h.hexdigest()

def quarter(d:str)->str:
    y,m=map(int,d.split("-")[:2])
    return f"{y}Q{(m-1)//3+1}"

def audit()->dict:
    signals=[]
    for rp in sorted(SIGNAL_DIR.glob("*_SIGNAL_FEATURE_RECEIPT.json")):
        r=json.loads(rp.read_text(encoding="utf-8"))
        if r.get("status")!="FROZEN_D_VINTAGE_FEATURE_SNAPSHOT":
            continue
        d=r["signal_date"]
        fp=Path(r["feature_csv"])
        if not fp.exists() or sha_file(fp)!=r["feature_csv_sha256"]:
            raise RuntimeError(f"FEATURE_HASH_MISMATCH:{d}")
        signals.append((d,r,fp))

    stats={
        hid:{
            "factor":factor,
            "valid_calm_dates":0,
            "valid_stressed_dates":0,
            "structurally_invalid_d10_dates_lt_50_rows":0,
            "calm_dates_by_quarter":defaultdict(int),
        }
        for hid,factor in HYPOTHESES
    }
    resolved_d10_dates=0

    for d,r,fp in signals:
        op=OUTCOME_DIR/f"{d}_D10_OUTCOMES.csv"
        rp=OUTCOME_DIR/f"{d}_D10_OUTCOME_RECEIPT.json"
        if not op.exists() or not rp.exists():
            continue
        ro=json.loads(rp.read_text(encoding="utf-8"))
        if ro.get("outcome_csv_sha256")!=sha_file(op):
            raise RuntimeError(f"OUTCOME_HASH_MISMATCH:{d}")
        resolved_d10_dates+=1
        state=r.get("market_state")
        if state not in {"CALM","STRESSED"}:
            continue
        feat=pd.read_csv(fp,usecols=["canonical_security_id"]+[f for _,f in HYPOTHESES])
        out=pd.read_csv(op,usecols=["canonical_security_id","fwd_return"])
        z=feat.merge(out,on="canonical_security_id",how="inner",validate="one_to_one")
        y=pd.to_numeric(z["fwd_return"],errors="coerce")
        for hid,factor in HYPOTHESES:
            x=pd.to_numeric(z[factor],errors="coerce")
            n=int((np.isfinite(x)&np.isfinite(y)).sum())
            if n<MIN_ROWS:
                stats[hid]["structurally_invalid_d10_dates_lt_50_rows"]+=1
                continue
            if state=="CALM":
                stats[hid]["valid_calm_dates"]+=1
                stats[hid]["calm_dates_by_quarter"][quarter(d)]+=1
            else:
                stats[hid]["valid_stressed_dates"]+=1

    ready_all=True
    clean={}
    for hid,_factor in HYPOTHESES:
        s=stats[hid]
        q=dict(sorted(s["calm_dates_by_quarter"].items()))
        valid_q=sum(1 for n in q.values() if n>=MIN_CALM_PER_QUARTER)
        ready=(
            s["valid_calm_dates"]>=MIN_CALM and
            s["valid_stressed_dates"]>=MIN_STRESSED and
            valid_q>=MIN_QUARTERS
        )
        ready_all &= ready
        clean[hid]={
            "factor":s["factor"],
            "valid_calm_dates":s["valid_calm_dates"],
            "required_calm_dates":MIN_CALM,
            "valid_stressed_dates":s["valid_stressed_dates"],
            "required_stressed_dates":MIN_STRESSED,
            "calm_dates_by_quarter":q,
            "valid_calm_quarters":valid_q,
            "required_valid_calm_quarters":MIN_QUARTERS,
            "required_calm_dates_per_quarter":MIN_CALM_PER_QUARTER,
            "structurally_invalid_d10_dates_lt_50_rows":s["structurally_invalid_d10_dates_lt_50_rows"],
            "readiness":"READY" if ready else "INCOMPLETE",
        }

    result={
        "schema":"AI_CORE_EVID_V2_8_3_INFORMATION_GATE_STATUS_V1",
        "version":"V2.8.3",
        "status":"READY_FOR_LOCKED_CONFIRMATORY_EVALUATION" if ready_all else "INCOMPLETE_NO_EVALUATION",
        "frozen_signal_date_count":len(signals),
        "resolved_d10_date_count":resolved_d10_dates,
        "hypotheses":clean,
        "performance_statistics_computed":False,
        "confirmatory_evaluator_authorized":bool(ready_all),
    }
    result["receipt_sha256"]=stable_json_sha(result)
    return result

def assert_blind_source():
    tree=ast.parse(Path(__file__).read_text(encoding="utf-8"))
    forbidden={"corr","cov","rank","quantile","mean","median","std","bootstrap","spearman","pearson"}
    bad=[]
    for node in ast.walk(tree):
        if isinstance(node,ast.Attribute) and node.attr.lower() in forbidden:
            bad.append(node.attr)
        if isinstance(node,ast.Name) and node.id.lower() in forbidden:
            bad.append(node.id)
    return sorted(set(bad))

def self_test():
    tests=[]
    def ck(n,v): tests.append({"name":n,"pass":bool(v)})
    ck("R01_quarter_q1",quarter("2027-01-15")=="2027Q1")
    ck("R02_quarter_q4",quarter("2027-12-15")=="2027Q4")
    fake_calm=60; fake_stressed=30; qs={"2026Q4":15,"2027Q1":15,"2027Q2":30}
    ck("R03_exact_minimum_ready",fake_calm>=MIN_CALM and fake_stressed>=MIN_STRESSED and sum(n>=15 for n in qs.values())>=3)
    ck("R04_59_calm_incomplete",not (59>=MIN_CALM))
    ck("R05_29_stressed_incomplete",not (29>=MIN_STRESSED))
    ck("R06_two_quarters_incomplete",not (sum(n>=15 for n in {"2026Q4":30,"2027Q1":30}.values())>=MIN_QUARTERS))
    ck("R07_row_minimum_exact",50>=MIN_ROWS)
    ck("R08_49_rows_invalid",not (49>=MIN_ROWS))
    bad=assert_blind_source()
    ck("R09_no_forbidden_stat_calls",bad==[])
    result={"schema":"AI_CORE_EVID_V2_8_3_BLIND_INFORMATION_GATE_SELFTEST_V1","tests":tests,
            "passed":sum(x["pass"] for x in tests),"total":len(tests),"all_pass":all(x["pass"] for x in tests),
            "forbidden_stat_call_hits":bad}
    result["receipt_sha256"]=stable_json_sha(result)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    if not result["all_pass"]:
        raise SystemExit(2)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("command",choices=["self-test","audit"])
    args=ap.parse_args()
    if args.command=="self-test":
        self_test()
    else:
        r=audit()
        OUT.write_text(json.dumps(r,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        print(json.dumps(r,ensure_ascii=False,indent=2))

if __name__=="__main__":
    main()
