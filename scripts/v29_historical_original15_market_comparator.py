#!/usr/bin/env python3
"""Retrospective matched CSI300 PRICE-index sensitivity for archived original15.
Never substitutes for the separate 2026 H00300 total-return benchmark.
"""
import argparse
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
DIR=ROOT/"research/v29_historical_original15_price_pair"
RECEIPT=DIR/"PRICE_PAIR_COVERAGE_15.json"
QUOTES=DIR/"RAW_15_MARKET_AND_CALENDAR.json"
FIELDS="date,code,close"
CODE="sh.000300"

def read_source():
    receipt=json.loads(RECEIPT.read_text(encoding="utf-8"))
    raw=QUOTES.read_bytes()
    if (hashlib.sha256(raw).hexdigest()!=receipt["raw_market_and_calendar_sha256"]
            or len(receipt["rows"])!=15 or receipt["number_of_fixed_selected_issuer_years"]!=15
            or receipt["live_buy_eligibility"]!="NOT_AUTHORIZED"):
        raise ValueError("ARCHIVED_15_SOURCE_IDENTITY_FAILED")
    return receipt,json.loads(raw)

def index_by_year(raw_by_year):
    clean={}
    for y in ("2023","2024"):
        rows=raw_by_year[y]
        bars={}
        for r in rows:
            day=r["date"]
            if r["code"]!=CODE or not day.startswith(y+"-") or day in bars:
                raise ValueError("INDEX_CODE_YEAR_OR_DUPLICATE_CHANGED")
            try:
                px=float(r["close"])
            except (ValueError,TypeError):
                px=float("nan")
            if not math.isfinite(px) or px<=0:
                raise ValueError("INDEX_CLOSE_INVALID")
            bars[day]=px
        clean[y]=bars
    return clean

def compute(receipt,stock_sources,index_source):
    index=index_by_year(index_source)
    output=[]
    for row in receipt["rows"]:
        sid=row["security_id"]
        fy=row["fiscal_year"]
        key=str(fy)+"|"+sid
        start,end=row["entry_session"],row["twentieth_session"]
        bars=index[str(fy+1)]
        entry,exit=bars.get(start),bars.get(end)
        reasons=[]
        if entry is None or exit is None:
            reasons.append("INDEX_ENDPOINT_MISSING")
        adjusted=stock_sources["quotes"][key]["forward_adjusted"]
        prices={}
        for r in adjusted:
            if r["date"] in (start,end):
                if r["adjustflag"]!="2" or r["date"] in prices:
                    raise ValueError("STOCK_ADJUSTED_PRICE_IDENTITY_CHANGED")
                prices[r["date"]]=float(r["close"])
        if start not in prices or end not in prices or any(not math.isfinite(v) or v<=0 for v in prices.values()):
            reasons.append("STOCK_PRICE_ENDPOINT_MISSING")
        stock_net=prices[end]/prices[start]-1-0.003 if not reasons else None
        index_return=exit/entry-1 if not reasons else None
        output.append({
            "security_id":sid,"fiscal_year":fy,"entry_session":start,
            "twentieth_session":end,"original_nonST_filter_pass":row["status"]=="RETROSPECTIVE_PRICE_PAIR_AVAILABLE",
            "original_filter_status":row["status"],
            "csi300_price_index_return":index_return,
            "stock_later_vintage_adjusted_price_return_minus_30bps":stock_net,
            "stock_minus_csi300_price_index_sensitivity":stock_net-index_return if not reasons else None,
            "status":"HISTORICAL_PRICE_ONLY_COMPARISON" if not reasons else "INCOMPLETE_NO_SUBSTITUTION",
            "issues":reasons,"total_return_benchmark_used":False,"tradable_close_fill_certified":False,
        })
    return output

def records(result):
    if result.error_code!="0":
        raise ValueError("INDEX_VENDOR_QUERY_FAILED:"+str(result.error_msg))
    out=[]
    while result.next():
        out.append(dict(zip(result.fields,result.get_row_data())))
    return out

def capture(out,bs):
    if out.exists():
        raise ValueError("NO_OVERWRITE_OF_INDEX_COMPARATOR")
    receipt,stock=read_source()
    result=bs.login()
    if result.error_code!="0":
        raise ValueError("INDEX_VENDOR_LOGIN_FAILED")
    try:
        index={}
        for year in ("2023","2024"):
            index[year]=records(bs.query_history_k_data_plus(
                CODE,FIELDS,start_date=year+"-03-01",end_date=year+"-07-15",
                frequency="d",adjustflag="3"))
    finally:
        bs.logout()
    raw=(json.dumps({"vendor":"BAOSTOCK","index_code":CODE,"rows_by_year":index},
                    ensure_ascii=False,sort_keys=True,separators=(",",":"))+"\n").encode()
    rows=compute(receipt,stock,index)
    report={
        "schema":"V29_HISTORICAL_ORIGINAL15_MATCHED_CSI300_PRICE_ONLY_SENSITIVITY_V1",
        "captured_at_utc":datetime.now(timezone.utc).isoformat(),
        "stock_source_receipt_path":str(RECEIPT.relative_to(ROOT)),
        "index_vendor":"BAOSTOCK_RETROSPECTIVE_QUERY",
        "index_id":"000300_PRICE_NOT_H00300_TOTAL_RETURN",
        "index_raw_sha256":hashlib.sha256(raw).hexdigest(),
        "original_15_denominator":15,"paired_count":sum(x["status"]=="HISTORICAL_PRICE_ONLY_COMPARISON" for x in rows),
        "nonST_original_filter_count":sum(x["original_nonST_filter_pass"] for x in rows),
        "research_after_outcomes_existed":True,"independent_oos_validated":False,
        "economic_total_return_certified":False,"live_buy_eligibility":"NOT_AUTHORIZED",
        "rows":rows
    }
    out.mkdir(parents=True)
    (out/"RAW_CSI300_PRICE_INDEX_2023_2024.json").write_bytes(raw)
    (out/"BENCHMARK_MATCHED_15.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return report

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--out",type=Path,required=True)
    args=p.parse_args()
    import baostock
    d=capture(args.out,baostock)
    print(json.dumps({"paired_count":d["paired_count"],"original_15_denominator":15,
                      "live_buy_eligibility":"NOT_AUTHORIZED"},ensure_ascii=False))

if __name__=="__main__":
    main()
