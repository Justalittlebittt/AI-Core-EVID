#!/usr/bin/env python3
"""Bounded 2-day SOURCE-ONLY admission of official SSE margin trading detail.

This is not all-A-share coverage (SSE margin-eligible names only); the
publish-at time is not sealed; no stock returns, no trading signal.
One request per finished day; fail visibly on malformed or truncated identity.
"""
from __future__ import annotations
import hashlib
import json
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

ENDPOINT="https://query.sse.com.cn/marketdata/tradedata/queryMargin.do"
DAYS=("20261116","20261117")

def request_day(day):
    query={
        "isPagination":"true","tabType":"mxtype","detailsDate":day,
        "stockCode":"","beginDate":"","endDate":"",
        "pageHelp.pageSize":"5000","pageHelp.pageCount":"50",
        "pageHelp.pageNo":"1","pageHelp.beginPage":"1",
        "pageHelp.cacheSize":"1","pageHelp.endPage":"21",
    }
    url=ENDPOINT+"?"+urllib.parse.urlencode(query)
    item={"date":day,"query_endpoint":ENDPOINT,"status":"SOURCE_UNAVAILABLE"}
    try:
        req=urllib.request.Request(url,headers={
            "User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
            "Accept":"application/json,text/plain,*/*",
            "Referer":"https://www.sse.com.cn/market/othersdata/margin/detail/",
        })
        with urllib.request.urlopen(req,timeout=18) as res:
            raw=res.read(4_000_001)
            item["http_status"]=res.status
        item["sha256"]=hashlib.sha256(raw).hexdigest()
        item["response_bytes"]=len(raw)
        if len(raw)>4_000_000:raise ValueError("RESPONSE_TOO_LARGE")
        obj=json.loads(raw)
        if not isinstance(obj,dict):raise ValueError("RESPONSE_NOT_OBJECT")
        item["response_keys"]=list(obj)[:15]
        item["page_help"]=obj.get("pageHelp")
        rows=obj.get("result")
        if not isinstance(rows,list):raise ValueError("RESULT_NOT_ARRAY")
        item["raw_rows"]=len(rows)
        observations={}
        for r in rows:
            if not isinstance(r,list) or len(r)<13:raise ValueError("ROW_NOT_13_FIELDS")
            trade_date=str(r[1])
            code=str(r[12])
            if trade_date!=day:raise ValueError("TRADE_DAY_DISAGREEMENT")
            if len(code)!=6 or not code.isdecimal():raise ValueError("BAD_SEC_CODE")
            if code in observations:raise ValueError("DUPLICATE_SEC_CODE")
            try:
                balance=Decimal(str(r[10]))
                buys=Decimal(str(r[8]))
                repay=Decimal(str(r[7]))
                if min(balance,buys,repay)<0:raise ValueError("NEGATIVE_MARGIN_METRIC")
            except (InvalidOperation,TypeError) as exc:raise ValueError("BAD_MARGIN_NUMBER") from exc
            observations[code]={"margin_balance_cny":str(balance),
                                "financing_buys_cny":str(buys),
                                "financing_repay_cny":str(repay)}
        item["unique_security_codes"]=len(observations)
        item["selected_codes"]={code:observations[code] for code in
                                ("603993","600362","601609") if code in observations}
        item["sum_financing_balance_cny"]=str(sum(
            (Decimal(v["margin_balance_cny"]) for v in observations.values()),Decimal(0)))
        item["status"]="PARSED_OFFICIAL_SSE_MARGIN_DAY_PAGE1_ONLY"
        item["completeness_proven"]=False
        item["all_codes_sha256"]=hashlib.sha256(
            "|".join(sorted(observations)).encode()).hexdigest()
        return item,observations
    except (OSError,ValueError,TypeError,json.JSONDecodeError) as exc:
        item["status"]="SOURCE_REQUEST_OR_SCHEMA_FAILED"
        item["error_type"]=type(exc).__name__
        item["error_message"]=str(exc)[:160]
        return item,{}

def main():
    days=[];by_date={}
    for day in DAYS:
        status,rows=request_day(day)
        days.append(status);by_date[day]=rows
        print("SSE_MARGIN_DAY",json.dumps(status,ensure_ascii=False,default=str),flush=True)
    common=set(by_date[DAYS[0]])&set(by_date[DAYS[1]])
    checked=0;failed=[]
    for code in sorted(common):
        old=by_date[DAYS[0]][code];new=by_date[DAYS[1]][code]
        # From SSE's published identity B(T)=B(T-1)+Buy(T)-Repay(T)
        delta=Decimal(new["margin_balance_cny"])-Decimal(old["margin_balance_cny"])
        net=Decimal(new["financing_buys_cny"])-Decimal(new["financing_repay_cny"])
        checked+=1
        if abs(delta-net)>Decimal("0.01"):
            failed.append({"code":code,"balance_delta":str(delta),
                           "buy_minus_repay":str(net)})
    result={
      "schema":"V32_SSE_MARGIN_TWO_DAY_SOURCE_ADMISSION_V1",
      "dates":list(DAYS),"observed_common_code_count":len(common),
      "accounting_identities_checked":checked,
      "balance_identity_violations_count":len(failed),
      "balance_identity_violation_examples":failed[:12],
      "days":days,
      "all_SSE_margin_universe_completeness_proven":False,
      "all_A_share_universe_covered":False,
      "as_originally_published_timestamp_independently_verified":False,
      "stock_outcome_returns_opened":False,
      "strategy_alpha_validated":False,
      "trade_authorized":False}
    Path("/tmp/v32_sse_margin_source_two_day.json").write_text(
      json.dumps(result,ensure_ascii=False,indent=2,default=str)+"\n",encoding="utf8")
    print("V32_SSE_MARGIN_PROBE",json.dumps({
      "dates":list(DAYS),"status":[x["status"] for x in days],
      "common":len(common),"balance_identities_failed":len(failed),
      "all_ashare_coverage":False,"alpha":False},ensure_ascii=False),flush=True)
if __name__=="__main__":main()
