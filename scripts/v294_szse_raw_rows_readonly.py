"""Read-only source row materialization against an immutable validated SZSE census.

Only records contemporaneous exchange response fields; never constructs CNINFO
announcement_time / finalpage locator or passes rows to frozen science.
"""
import hashlib
import json
from pathlib import Path
from playwright.sync_api import sync_playwright
from v294_szse_frozen_24_month_census import months,fetch_page,STOCK,ENDPOINT

REFERENCE=Path("evidence/V2.9.4_002667_SZSE_FROZEN_MONTH_CENSUS_V1.json")
OUT=Path("evidence/V2.9.4_002667_SZSE_RAW_ROWS_RETRIEVAL_V1.json")
SIZE=50
LIMIT=15

def digest_rows(rows):
    normalized=[{k:r[k] for k in ("ann_id","publication_day","title","exchange_relative_path")}
                for r in rows]
    return hashlib.sha256(json.dumps(sorted(normalized,key=lambda r:r["ann_id"]),
        ensure_ascii=False,sort_keys=True).encode()).hexdigest()

def capture_month(req,start,end):
    rows=[];totals=[];counts=[];failure=None
    for page in range(1,LIMIT+1):
        payload={"channelCode":["listedNotice_disc"],"pageSize":SIZE,
                 "pageNum":page,"stock":[STOCK],"seDate":[start,end]}
        response=fetch_page(req,payload)
        if response["status"]!="OK":
            failure=f"{response['status']}:page{page}"
            break
        obj=response["data"]
        totals.append(obj["announceCount"])
        records=obj["data"]
        counts.append(len(records))
        for r in records:
            if not isinstance(r,dict):
                failure="INVALID_ROW_SHAPE";break
            rawcode=r.get("secCode") or r.get("stockCode") or ""
            codes=[str(c).strip() for c in rawcode] if isinstance(rawcode,list) else [str(rawcode).strip()]
            aid=str(r.get("annId") or "").strip()
            stamp=str(r.get("publishTime") or "").strip()
            day=stamp[:10]
            title=str(r.get("title") or "").strip()
            path=str(r.get("attachPath") or "")
            if (codes!=[STOCK] or not aid or not title or not start<=day<=end or
                not path.startswith("/disc/") or not stamp.startswith(day)):
                failure="INVALID_SOURCE_ROW_IDENTITY";break
            rows.append({"ann_id":aid,"publication_day":day,"title":title,
                         "exchange_relative_path":path,"exchange_publish_time_raw":stamp,
                         "exchange_stock_codes":codes})
        if failure:break
        if len(records)<SIZE:break
    else:failure="PAGE_LIMIT_EXCEEDED"
    ids=sorted(x["ann_id"] for x in rows)
    closed=(not failure and len(set(totals))==1 and len(ids)==len(set(ids))
            and bool(totals) and len(rows)==totals[0] and counts[-1]<SIZE)
    return {"range":[start,end],"complete":bool(closed),"official_totals":sorted(set(totals)),
            "page_counts":counts,"error":failure,"rows":rows,
            "row_fingerprint":digest_rows(rows)}

def reconcile(reference,sessions):
    if len(sessions)!=2 or len(reference)!=24:
        raise ValueError("TWO_COMPLETE_SESSIONS_AND_24_MONTH_REFERENCES_REQUIRED")
    checks=[];persisted=[];seen=set();duplicate=[]
    for start,end in months():
        if start not in reference or any(start not in session for session in sessions):
            raise ValueError("MISSING_MONTH_SOURCE")
        canonical=reference[start]
        runs=[session[start] for session in sessions]
        ids=[sorted(r["ann_id"] for r in entry["rows"]) for entry in runs]
        expected=sorted(canonical["ids"])
        source_consistent=all(
            r["complete"] and r["range"]==[start,end] and
            r["row_fingerprint"]==canonical["row_fingerprint"] and
            values==expected and
            r["official_totals"]==canonical["reported_totals"]
            for r,values in zip(runs,ids))
        passed=bool(source_consistent and runs[0]["row_fingerprint"]==runs[1]["row_fingerprint"])
        checks.append({"month":start[:7],"pass":passed,
                       "row_count":len(ids[0]),"expected_count":len(expected),
                       "source_errors":[r["error"] for r in runs]})
        if passed:
            for aid in ids[0]:
                if aid in seen:duplicate.append(aid)
                seen.add(aid)
            persisted.extend(runs[0]["rows"])
    success=len(checks)==24 and all(c["pass"] for c in checks) and not duplicate and len(seen)==486
    return {"full_source_row_reference_match":success,"passed_months":sum(c["pass"] for c in checks),
            "expected_months":24,"candidate_rows_if_pass":len(persisted),
            "cross_month_duplicates":sorted(set(duplicate)),"months":checks,
            "rows":sorted(persisted,key=lambda r:(r["publication_day"],r["ann_id"])) if success else [],
            "cninfo_temporal_provenance_verified":False,
            "cninfo_pdf_locator_compatible":False,
            "original_batch3_source_substitution_authorized":False,
            "original_batch3_scientifically_complete":False,
            "protected_outcomes_consumed":False,"trade_authorized":False}

def main():
    frozen=json.loads(REFERENCE.read_text(encoding="utf-8"))
    if frozen.get("evaluation",{}).get("frozen_range_month_source_consistency_pass") is not True:
        raise RuntimeError("FROZEN_SOURCE_REFERENCE_NOT_VERIFIED")
    reference={start:entry[str(SIZE)]
               for start,entry in frozen["source_sessions"][0].items()}
    sessions=[]
    with sync_playwright() as pw:
        for _ in range(2):
            req=pw.request.new_context(extra_http_headers={
                "User-Agent":"Mozilla/5.0",
                "Referer":"https://www.szse.cn/disclosure/listed/notice/index.html",
                "Origin":"https://www.szse.cn","Content-Type":"application/json",
                "X-Requested-With":"XMLHttpRequest"})
            try:
                sessions.append({start:capture_month(req,start,end) for start,end in months()})
            finally:req.dispose()
    result=reconcile(reference,sessions)
    # Do not represent incomplete attempts as an authoritative row-level corpus.
    output={"schema":"V294_SZSE_002667_486_SOURCE_ROWS_READ_ONLY_V1",
            "issuer":"SZSE:002667","frozen_range":["2023-01-01","2024-12-30"],
            "source_api":ENDPOINT,
            "reference_path":str(REFERENCE),
            "source_rows":result.pop("rows"),
            "evaluation":result}
    OUT.write_text(json.dumps(output,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({k:v for k,v in result.items() if k!="months"},ensure_ascii=False))
    if not result["full_source_row_reference_match"]:
        raise SystemExit("SZSE_RAW_SOURCE_ROWS_NOT_ALL_RECONCILED")

if __name__=="__main__":
    main()
