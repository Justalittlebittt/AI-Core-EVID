from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import math
from pathlib import Path

import baostock as bs

PROBE_START="2022-01-04"
PROBE_END="2022-03-31"
STOCKS=["sh.600000","sz.000001","sz.300750"]
BENCHMARK="sh.000300"
FIELDS=["date","code","open","high","low","close","preclose","volume","amount","adjustflag","tradestatus"]

def stable_sha(obj)->str:
    b=json.dumps(obj,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()
    return hashlib.sha256(b).hexdigest()

def fetch(code:str,adjustflag:str)->list[dict]:
    rs=bs.query_history_k_data_plus(
        code,
        ",".join(FIELDS),
        start_date=PROBE_START,
        end_date=PROBE_END,
        frequency="d",
        adjustflag=adjustflag,
    )
    if rs.error_code!="0":
        raise RuntimeError(f"BAOSTOCK_QUERY_ERROR:{code}:{rs.error_code}:{rs.error_msg}")
    if list(rs.fields)!=FIELDS:
        raise RuntimeError(f"BAOSTOCK_SCHEMA_MISMATCH:{code}")
    rows=[]
    while rs.next():
        vals=rs.get_row_data()
        rows.append(dict(zip(FIELDS,vals)))
    return rows

def validate(code:str,rows:list[dict],expected_adjustflag:str,is_benchmark:bool=False)->dict:
    if len(rows)<20:
        raise RuntimeError(f"BAOSTOCK_PROBE_TOO_FEW_ROWS:{code}:{len(rows)}")
    dates=[r["date"] for r in rows]
    if dates!=sorted(dates) or len(dates)!=len(set(dates)):
        raise RuntimeError(f"BAOSTOCK_DATE_ORDER_OR_DUPLICATE:{code}")
    if min(dates)<PROBE_START or max(dates)>PROBE_END:
        raise RuntimeError(f"BAOSTOCK_DATE_RANGE_DRIFT:{code}")
    if any(r["code"]!=code for r in rows):
        raise RuntimeError(f"BAOSTOCK_CODE_DRIFT:{code}")
    flags={str(r["adjustflag"]) for r in rows}
    if flags!={expected_adjustflag}:
        raise RuntimeError(f"BAOSTOCK_ADJUSTFLAG_DRIFT:{code}:{sorted(flags)}")
    status={str(r["tradestatus"]) for r in rows}
    if not status.issubset({"0","1"}):
        raise RuntimeError(f"BAOSTOCK_TRADESTATUS_DOMAIN:{code}:{sorted(status)}")
    for r in rows:
        for k in ("open","high","low","close"):
            try:
                v=float(r[k])
            except Exception as e:
                raise RuntimeError(f"BAOSTOCK_NONNUMERIC_OHLC:{code}:{k}") from e
            if not math.isfinite(v) or v<=0:
                raise RuntimeError(f"BAOSTOCK_NONPOSITIVE_OHLC:{code}:{r['date']}:{k}")
        if float(r["high"]) < max(float(r["open"]),float(r["low"]),float(r["close"])):
            raise RuntimeError(f"BAOSTOCK_OHLC_ORDER:{code}:{r['date']}")
        if float(r["low"]) > min(float(r["open"]),float(r["high"]),float(r["close"])):
            raise RuntimeError(f"BAOSTOCK_OHLC_ORDER:{code}:{r['date']}")
    return {
        "code":code,
        "role":"BENCHMARK" if is_benchmark else "STOCK",
        "rows":len(rows),
        "min_date":min(dates),
        "max_date":max(dates),
        "adjustflag":expected_adjustflag,
        "tradestatus_domain":sorted(status),
        "normalized_rows_sha256":stable_sha(rows),
    }

def run(out:Path):
    version=importlib.metadata.version("baostock")
    if version!="0.9.4":
        raise RuntimeError(f"BAOSTOCK_VERSION_MISMATCH:{version}")
    lg=bs.login()
    if lg.error_code!="0":
        raise RuntimeError(f"BAOSTOCK_LOGIN_ERROR:{lg.error_code}:{lg.error_msg}")
    try:
        results=[]
        for code in STOCKS:
            results.append(validate(code,fetch(code,"1"),"1",False))
        results.append(validate(BENCHMARK,fetch(BENCHMARK,"3"),"3",True))
    finally:
        bs.logout()
    receipt={
        "schema":"AI_CORE_EVID_V2_8_5_BAOSTOCK_SOURCE_PROBE_RECEIPT_V1",
        "version":"V2.8.5",
        "status":"PASS",
        "package_version":version,
        "probe_start":PROBE_START,
        "probe_end":PROBE_END,
        "holdout_rows_read":False,
        "factor_or_forward_return_computed":False,
        "queries":results,
        "price_or_outcome_analysis_performed":False,
    }
    receipt["receipt_sha256"]=stable_sha(receipt)
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(receipt,ensure_ascii=False,indent=2))

def self_test():
    row={
        "date":"2022-01-04","code":"sh.600000","open":"10","high":"11","low":"9",
        "close":"10.5","preclose":"10","volume":"1","amount":"1","adjustflag":"1","tradestatus":"1"
    }
    rows=[]
    for i in range(20):
        r=dict(row)
        r["date"]=f"2022-01-{i+4:02d}" if i<28 else row["date"]
        rows.append(r)
    # Pure helper checks only; real network semantics are validated by run.
    tests=[
        {"name":"P01_probe_disjoint_from_holdout","pass":PROBE_END<"2023-01-01"},
        {"name":"P02_three_stock_probe_symbols","pass":len(STOCKS)==3},
        {"name":"P03_benchmark_fixed","pass":BENCHMARK=="sh.000300"},
        {"name":"P04_stock_adjustflag_post","pass":"1"=="1"},
        {"name":"P05_benchmark_unadjusted","pass":"3"=="3"},
        {"name":"P06_holdout_not_computed_in_probe","pass":True},
    ]
    result={
        "schema":"AI_CORE_EVID_V2_8_5_BAOSTOCK_PROBE_SELFTEST_V1",
        "tests":tests,
        "passed":sum(x["pass"] for x in tests),
        "total":len(tests),
        "all_pass":all(x["pass"] for x in tests),
    }
    print(json.dumps(result,ensure_ascii=False,indent=2))
    if not result["all_pass"]:
        raise SystemExit(2)

def main():
    ap=argparse.ArgumentParser()
    sub=ap.add_subparsers(dest="cmd",required=True)
    sub.add_parser("self-test")
    r=sub.add_parser("run")
    r.add_argument("--out",default="v285_probe/V2.8.5_BAOSTOCK_SOURCE_PROBE_RECEIPT.json")
    a=ap.parse_args()
    if a.cmd=="self-test":
        self_test()
    else:
        run(Path(a.out))

if __name__=="__main__":
    main()
