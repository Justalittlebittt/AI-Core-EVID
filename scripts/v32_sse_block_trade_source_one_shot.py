#!/usr/bin/env python3
"""One-shot official SSE bulk-trade source admission: bounded, no stock outcomes.

Must demonstrate requested historical date actually respected, pagination
fully exhausted, and stock identity; otherwise SOURCE_NOT_ADMISSIBLE.
"""
from __future__ import annotations
import hashlib,json,urllib.parse,urllib.request
from pathlib import Path

ENDPOINT="https://query.sse.com.cn/commonQuery.do"
DATES=("20260814","20260915")
SQL_ID="COMMON_SSE_XXPL_JYXXPL_DZJY"

def check(day):
    query={"sqlId":SQL_ID,"isPagination":"true",
           "tradeDate":day,"beginDate":day,"endDate":day,
           "pageHelp.pageSize":"2000","pageHelp.pageNo":"1",
           "pageHelp.beginPage":"1","pageHelp.endPage":"1",
           "pageHelp.cacheSize":"1"}
    url=ENDPOINT+"?"+urllib.parse.urlencode(query)
    report={"requested_trade_day":day,"source":ENDPOINT,"sqlId":SQL_ID,
            "status":"UNVERIFIED","complete":False}
    try:
        req=urllib.request.Request(url,headers={
          "User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
          "Referer":"https://www.sse.com.cn/disclosure/diclosure/block/deal/dzjyxx/",
          "Accept":"application/json,text/plain,*/*"})
        with urllib.request.urlopen(req,timeout=18) as res:
            raw=res.read(1500001)
            report["http_status"]=res.status
        if len(raw)>1500000:raise ValueError("OVER_BOUNDED_RESPONSE")
        report["response_sha256"]=hashlib.sha256(raw).hexdigest()
        report["response_bytes"]=len(raw)
        doc=json.loads(raw)
        if not isinstance(doc,dict):raise ValueError("NOT_JSON_OBJECT")
        report["response_keys"]=list(doc.keys())[:15]
        payload=doc.get("result")
        report["result_type"]=type(payload).__name__
        report["result_len"]=len(payload) if isinstance(payload,list) else None
        report["result_sample"]=payload[:2] if isinstance(payload,list) else None
        meta=doc.get("pageHelp")
        report["page_help"]=meta
        if not isinstance(payload,list) or not isinstance(meta,dict):
            report["status"]="SCHEMA_NOT_CONFIRMED"
        else:
            report["status"]="RETURNED_BUT_DATE_AND_PAGE_COMPLETENESS_UNPROVEN"
            # Do not claim date is respected without explicitly verified
            # row day field and exact meta total/unique identities.
    except Exception as e:
        report["status"]="OFFICIAL_SOURCE_REQUEST_FAILED"
        report["error_type"]=type(e).__name__
        report["error_message"]=str(e)[:160]
    print("BULK_DAY",json.dumps(report,ensure_ascii=False),flush=True)
    return report

def main():
    days=[check(d) for d in DATES]
    result={"schema":"V32_SSE_BLOCK_2DAY_SOURCE_PROBE_V1",
      "dates":days,"date_filter_reliability_proven":False,
      "full_historical_event_census_proven":False,
      "20session_forecast_experiment_authorized":False,
      "stock_return_outcomes_read":False,"trade_authorized":False}
    Path("/tmp/v32_sse_block_trade_probe.json").write_text(
        json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    print("BLOCK_SOURCE_CONCLUSION",json.dumps({
      "date_status":[r["status"] for r in days],
      "cannot_claim_source_census":True,"buy":False},ensure_ascii=False),flush=True)
if __name__=="__main__":main()
