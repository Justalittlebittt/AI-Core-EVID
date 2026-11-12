"""Read-only SZSE 002667 2023-2024 frozen monthly census; no science admission.

24 disjoint month partitions, 2 isolated source sessions, sizes 30/50,
strict per-page totals, immutable announcement IDs, publication dates, and
partition-level agreement. Capture source failure rather than patching counts.
"""
import calendar
import hashlib
import json
from collections import Counter
from pathlib import Path
from playwright.sync_api import sync_playwright
from v294_szse_independent_day_list_retry_v2 import ENDPOINT, STOCK

OUT=Path("evidence/V2.9.4_002667_SZSE_FROZEN_MONTH_CENSUS_V1.json")
START="2023-01-01"
END="2024-12-30"
SIZES=(30,50)
MAX_PAGES=15


def months():
    result=[]
    for y in (2023,2024):
        for m in range(1,13):
            start=f"{y}-{m:02d}-01"
            end=min(f"{y}-{m:02d}-{calendar.monthrange(y,m)[1]:02d}",END)
            result.append((start,end))
    assert len(result)==24
    return result


def fetch_page(req, payload):
    """Retry only a transport reset, not a source contradiction."""
    for attempt in (1,2):
        try:
            response=req.post(ENDPOINT,data=payload,timeout=20000)
            if response.status!=200:
                return {"status":"HTTP_FAILURE","http_status":response.status,
                        "attempts":attempt}
            obj=response.json()
            if not isinstance(obj,dict) or not isinstance(obj.get("announceCount"),int) or not isinstance(obj.get("data"),list):
                return {"status":"SCHEMA_BLOCK"}
            return {"status":"OK","attempts":attempt,"data":obj}
        except Exception as ex:
            msg=str(ex)
            if attempt==1 and "ECONNRESET" in msg:
                continue
            return {"status":"TRANSPORT_BLOCK","error_type":type(ex).__name__,
                    "error_summary":msg[:120],"attempts":attempt}
    raise AssertionError("UNREACHABLE")


def collect(req, start, end, size):
    rows=[]; totals=[]; sizes=[]; error=None
    for page in range(1,MAX_PAGES+1):
        payload={"channelCode":["listedNotice_disc"],"pageSize":size,
                 "pageNum":page,"stock":[STOCK],"seDate":[start,end]}
        out=fetch_page(req,payload)
        if out["status"]!="OK":
            error=f"{out['status']}:page{page}"
            break
        obj=out["data"]
        count=obj["announceCount"]
        incoming=obj["data"]
        totals.append(count);sizes.append(len(incoming))
        for r in incoming:
            if not isinstance(r,dict):
                error="NON_OBJECT_ANNOUNCEMENT";break
            rawcode=r.get("secCode") or r.get("stockCode") or ""
            codes=[str(x).strip() for x in rawcode] if isinstance(rawcode,list) else [str(rawcode).strip()]
            aid=str(r.get("annId") or "").strip()
            day=str(r.get("publishTime") or "")[:10]
            loc=str(r.get("attachPath") or "")
            title=str(r.get("title") or "").strip()
            if codes!=[STOCK] or not aid or not title or not start<=day<=end or not loc.startswith("/disc/"):
                error="ROW_IDENTITY_DATE_SOURCE_BLOCK";break
            rows.append({"ann_id":aid,"publication_day":day,"title":title,
                         "exchange_relative_path":loc})
        if error:break
        if len(incoming)<size:break
    else:
        error="PAGE_LIMIT_EXCEEDED"
    ids=[r["ann_id"] for r in rows]
    same_count=len(set(totals))==1
    unique=len(ids)==len(set(ids))
    closed=(not error and bool(totals) and same_count and
            len(rows)==totals[0] and unique and
            (not sizes or sizes[-1]<size))
    # The official count may legitimately be zero in an otherwise valid month.
    fingerprint=hashlib.sha256(
        json.dumps(sorted(rows,key=lambda r:r["ann_id"]),ensure_ascii=False,sort_keys=True).encode()).hexdigest()
    return {"range":[start,end],"size":size,
            "reported_totals":sorted(set(totals)),"page_counts":sizes,
            "raw_count":len(rows),"unique_count":len(set(ids)),
            "ids":sorted(set(ids)),"id_sha256":hashlib.sha256(("\n".join(sorted(set(ids)))+"\n").encode()).hexdigest(),
            "row_fingerprint":fingerprint,"error":error,"complete":bool(closed)}


def evaluate(sessions):
    requested=months()
    if len(sessions)!=2 or any(set(x)!=set(start for start,_ in requested) for x in sessions):
        raise ValueError("EXACT_TWO_FULL_MONTH_SESSIONS_REQUIRED")
    results=[];seen={}
    for start,end in requested:
        runs=[s[start][str(sz)] for s in sessions for sz in SIZES]
        closed=all(r["complete"] and r["range"]==[start,end] for r in runs)
        ids_equal=closed and len({r["id_sha256"] for r in runs})==1
        rows_equal=closed and len({r["row_fingerprint"] for r in runs})==1
        totals_equal=closed and len({tuple(r["reported_totals"]) for r in runs})==1
        good=bool(closed and ids_equal and rows_equal and totals_equal)
        ids=runs[0]["ids"] if good else []
        if good:
            for aid in ids:
                seen.setdefault(aid,[]).append(start)
        results.append({"month":start[:7],"pass":good,
                        "closed":closed,"ids_equal":ids_equal,
                        "rows_equal":rows_equal,"totals_equal":totals_equal,
                        "independent_unique_count":len(ids),
                        "run_counts":[r["unique_count"] for r in runs],
                        "run_totals":[r["reported_totals"] for r in runs],
                        "run_errors":[r["error"] for r in runs]})
    cross={aid:times for aid,times in seen.items() if len(times)>1}
    all_pass=all(r["pass"] for r in results) and not cross and len(seen)>0
    return {"months":results,"passed_months":sum(x["pass"] for x in results),
            "total_months":len(results),"cross_month_duplicate_ids":cross,
            "conditional_unique_union_count":len(seen),
            "frozen_range_month_source_consistency_pass":bool(all_pass),
            # Even total month closure is not automatic research admission:
            "historical_full_range_scientifically_certified":False,
            "batch3_authorized":False,"batch4_authorized":False,
            "protected_outcomes_consumed":False,"trading_authorized":False}


def main():
    sessions=[]
    with sync_playwright() as pw:
        for session in range(2):
            req=pw.request.new_context(extra_http_headers={
                "User-Agent":"Mozilla/5.0",
                "Referer":"https://www.szse.cn/disclosure/listed/notice/index.html",
                "Origin":"https://www.szse.cn","Content-Type":"application/json",
                "X-Requested-With":"XMLHttpRequest"})
            try:
                records={}
                for start,end in months():
                    records[start]={str(sz):collect(req,start,end,sz) for sz in SIZES}
                sessions.append(records)
            finally:req.dispose()
    verdict=evaluate(sessions)
    receipt={"schema":"V294_SZSE_002667_FROZEN_24_MONTH_2_SESSION_2_PAGE_SIZE_AUDIT_V1",
             "official_source":ENDPOINT,"security_id":"SZSE:002667",
             "frozen_range":[START,END],
             "source_sessions":sessions,"evaluation":verdict}
    OUT.write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({k:v for k,v in verdict.items() if k not in ("months","cross_month_duplicate_ids")},ensure_ascii=False))
    print(json.dumps([r for r in verdict["months"] if not r["pass"]],ensure_ascii=False))
    if not verdict["frozen_range_month_source_consistency_pass"]:
        raise SystemExit("SZSE_FROZEN_MONTH_CENSUS_SOURCE_CONSISTENCY_BLOCKED")


if __name__=="__main__":
    main()
