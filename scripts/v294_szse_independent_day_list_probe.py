"""Read-only SZSE independent disclosure-list probe, one frozen issuer and day.

This is a source feasibility test, NOT the 2023-24 frozen full-range census.
"""
import hashlib
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

ENDPOINT="https://www.szse.cn/api/disc/announcement/annList"
OUT=Path("evidence/V2.9.4_002667_SZSE_INDEPENDENT_LIST_DAY_PROBE_1.json")
TARGET_DAY="2023-08-31"
STOCK="002667"
TARGET_TITLE="关于控股股东部分股份质押的公告"

def validate(response, size):
    if not isinstance(response,dict):
        return {"parse_valid":False,"status":"SCHEMA_NOT_OBJECT"}
    raw=response.get("data")
    rows=raw if isinstance(raw,list) else []
    count=response.get("announceCount")
    if not isinstance(count,int) or count<0 or not isinstance(raw,list):
        return {"parse_valid":False,"status":"UNEXPECTED_EXCHANGE_SCHEMA",
                "object_keys":sorted(response.keys())}
    items=[];bad=[]
    for row in rows:
        if not isinstance(row,dict):
            bad.append("NON_OBJECT_ROW");continue
        when=str(row.get("publishTime") or "")
        title=str(row.get("title") or "")
        url=str(row.get("attachPath") or "")
        code=str(row.get("secCode") or row.get("stockCode") or "")
        if not when.startswith(TARGET_DAY):bad.append("DATE_OUTSIDE_DAY")
        if code and code!=STOCK:bad.append("WRONG_STOCK")
        if url and not url.startswith("/disc/"):bad.append("NONOFFICIAL_ATTACH_PATH")
        items.append({"title":title,"publish_time":when,
                      "exchange_ann_id":str(row.get("annId") or ""),
                      "stock_field":code,"relative_file_path":url})
    normalized=[(x["title"],x["publish_time"],x["relative_file_path"]) for x in items]
    unique=len(set(normalized))==len(normalized)
    closed=not bad and unique and count==len(items) and len(items)>0 and len(items)<=size
    match=[x for x in items if TARGET_TITLE in x["title"]]
    digest=hashlib.sha256(json.dumps(sorted(normalized),ensure_ascii=False).encode()).hexdigest()
    return {"parse_valid":True,"status":"COMPLETE_SINGLE_PAGE" if closed else "SOURCE_INCOMPLETE",
            "official_total":count,"returned_count":len(items),"page_size":size,
            "duplicate_free":unique,"source_errors":bad,"row_fingerprint":digest,
            "matches_target_title":match,"all_rows":items,"single_page_closed":closed}

def compare(sessions):
    if len(sessions)!=2 or any(set(s)!={20,30} for s in sessions):
        raise ValueError("TWO_SESSIONS_TWO_SIZES_REQUIRED")
    values=[r for ses in sessions for r in ses.values()]
    ready=all(r.get("single_page_closed") for r in values)
    same=ready and len({r["row_fingerprint"] for r in values})==1
    target=same and all(len(r["matches_target_title"])==1 for r in values)
    return {"independent_szse_day_consistent":bool(ready and same and target),
            "four_single_page_censuses_closed":ready,
            "four_id_sets_identical":bool(same),
            "target_title_present_each":bool(target),
            "full_2023_2024_issuer_census_certified":False,
            "batch3_authorized":False,"batch4_authorized":False,
            "protected_outcomes_consumed":False,"trading_authorized":False}

def main():
    sessions=[]
    with sync_playwright() as pw:
        for _ in range(2):
            req=pw.request.new_context(extra_http_headers={
                "User-Agent":"Mozilla/5.0","Referer":"https://www.szse.cn/disclosure/listed/notice/index.html",
                "Origin":"https://www.szse.cn","Content-Type":"application/json",
                "X-Requested-With":"XMLHttpRequest"})
            try:
                collection={}
                for size in (20,30):
                    payload={"channelCode":["listedNotice_disc"],"pageSize":size,
                             "pageNum":1,"stock":[STOCK],
                             "seDate":[TARGET_DAY,TARGET_DAY]}
                    try:
                        response=req.post(ENDPOINT,data=payload,timeout=30000)
                        if response.status!=200:
                            collection[size]={"status":"HTTP_FAILURE","http_status":response.status,
                                              "single_page_closed":False}
                        else:
                            collection[size]={"http_status":200,**validate(response.json(),size)}
                    except Exception as exc:
                        collection[size]={"status":"TRANSPORT_OR_PARSE_FAILED",
                                          "error_type":type(exc).__name__,
                                          "error_summary":str(exc)[:150],
                                          "single_page_closed":False}
                sessions.append(collection)
            finally:req.dispose()
    verdict=compare(sessions)
    result={"schema":"V294_SZSE_002667_SINGLE_DAY_INDEPENDENT_DISCLOSURE_LIST_PROBE_V1",
            "source":"SZSE_OFFICIAL_LISTED_COMPANY_NOTICE_ENDPOINT",
            "api":ENDPOINT,"stock":STOCK,"frozen_day":[TARGET_DAY,TARGET_DAY],
            "sessions":sessions,"evaluation":verdict}
    OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(verdict,ensure_ascii=False))
    if not verdict["independent_szse_day_consistent"]:
        raise SystemExit("SZSE_OFFICIAL_DAY_CENSUS_NOT_CERTIFIED")
if __name__=="__main__":main()
