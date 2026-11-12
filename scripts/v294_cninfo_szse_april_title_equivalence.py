"""Read-only narrow CNINFO/SZSE April 2023 original-title comparison.

Requires entire 53-ID April set in two clean CNINFO sessions and two page sizes.
Never substitutes exchange titles into frozen science or certifies whole period.
"""
import hashlib
import json
import re
from datetime import datetime,timezone
from pathlib import Path
from playwright.sync_api import sync_playwright

import v284_candidate_triage as triage
import v291_negative_space_batch1 as cninfo

SZSE=Path("evidence/V2.9.4_002667_SZSE_RAW_ROWS_RETRIEVAL_V1.json")
OUT=Path("evidence/V2.9.4_002667_CNINFO_SZSE_APRIL_TITLE_EQUIVALENCE_1.json")
ORG="9900022274"
START="2023-04-01"
END="2023-04-30"
SIZES=(20,30)
MAX_PAGES=6
TARGET="1216403319"


def query_month(page,sz):
    rows=[];totals=[];counts=[];error=None
    payload={"column":"szse","tabName":"fulltext","plate":"sz",
             "stock":"002667,"+ORG,"searchkey":"","secid":"","category":"",
             "trade":"","seDate":START+"~"+END,"sortName":"","sortType":"",
             "isHLtitle":"true","pageNum":"1","pageSize":str(sz)}
    for num in range(1,MAX_PAGES+1):
        obj=json.loads(cninfo.post(page,{**payload,"pageNum":str(num)}))
        incoming=obj.get("announcements")
        total=int(obj.get("totalRecordNum") or obj.get("totalAnnouncement") or 0)
        if not isinstance(incoming,list):
            error="MISSING_ANNOUNCEMENTS_ARRAY";break
        totals.append(total);counts.append(len(incoming))
        for item in incoming:
            aid=str(item.get("announcementId") or "").strip()
            ms=str(item.get("announcementTime") or "").strip()
            code=str(item.get("secCode") or "").strip()
            if not aid or not re.fullmatch(r"\d{10}|\d{13}",ms) or code!="002667":
                error="MALFORMED_ISSUER_ID_OR_TIMESTAMP";break
            date=datetime.fromtimestamp(int(ms)/(1000 if len(ms)==13 else 1),tz=timezone.utc).astimezone(cninfo.SH).date().isoformat()
            try:
                path,pdate=cninfo.locator(item.get("adjunctUrl"),aid)
            except Exception:
                error="INVALID_CNINFO_ORIGINAL_PDF_LOCATOR";break
            if not START<=date<=END or pdate!=date:
                error="DATE_OUTSIDE_APRIL_OR_TEMPORAL_CONFLICT";break
            title=re.sub(r"</?em>","",str(item.get("announcementTitle") or ""),flags=re.I).strip()
            name=str(item.get("secName") or "").strip()
            if not title or not name:
                error="MISSING_CNINFO_TITLE_OR_SECURITY_NAME";break
            rows.append({"ann_id":aid,"announcement_title":title,"security_name":name,
                         "announcement_time_raw":ms,"publication_day":date,
                         "cninfo_relative_pdf_path":path})
        if error:break
        if len(incoming)<sz:break
    else:error="PAGINATION_LIMIT_EXCEEDED"
    ids=[r["ann_id"] for r in rows]
    complete=not error and len(set(totals))==1 and bool(totals) and totals[0]==len(ids)==len(set(ids)) and counts[-1]<sz
    return {"size":sz,"reported_totals":sorted(set(totals)),"page_counts":counts,
            "observed_count":len(ids),"unique_count":len(set(ids)),
            "complete":bool(complete),"error":error,"rows":rows}


def compare(exchange_rows,sessions):
    original={r["ann_id"]:r for r in exchange_rows
              if START<=r["publication_day"]<=END}
    if len(original)!=53 or len(sessions)!=2 or any(set(s)!={20,30} for s in sessions):
        raise ValueError("EXACT_APRIL_REFERENCE_AND_TWO_SESSIONS_REQUIRED")
    original_ids=set(original)
    checks=[]
    for session in sessions:
        for sz in SIZES:
            run=session[sz]
            records=run["rows"]
            ids=[r["ann_id"] for r in records]
            checks.append({"size":sz,"complete":run["complete"],
                           "observed":len(ids),"reported_totals":run["reported_totals"],
                           "ids_equal_to_exchange":set(ids)==original_ids and len(ids)==53,
                           "source_error":run["error"]})
    full=all(c["complete"] and c["ids_equal_to_exchange"] and c["reported_totals"]==[53] for c in checks)
    output={"source_runs":checks,"all_four_april_censuses_equal_to_szse":bool(full),
            "cninfo_title_observations":[],
            "cninfo_to_szse_title_triad_disagreements":[],
            "candidate_decision_mismatch_count":None,
            "verified_april_issuer_rows":53 if full else 0,
            "verified_full_486_cninfo_titles":False,
            "batch3_authorized":False,"outcomes_consumed":False,"buy_authorized":False}
    if not full:
        # Retain bounded partial source responses as diagnostics only, not a corpus.
        output["partial_source_target_sightings"]=[
            r for s in sessions for sz in SIZES for r in s[sz]["rows"]
            if r["ann_id"]==TARGET]
        return output
    validated={}
    for s in sessions:
        for sz in SIZES:
            for r in s[sz]["rows"]:
                if r["ann_id"] in validated and validated[r["ann_id"]]!=r:
                    output["all_four_april_censuses_equal_to_szse"]=False
                    output["error"]="CROSS_SESSION_TITLE_OR_TIMESTAMP_DRIFT"
                    return output
                validated[r["ann_id"]]=r
    disagreements=[]
    for aid,orig in sorted(validated.items()):
        exch=original[aid]
        a=triage.triage_title(orig["announcement_title"],orig["security_name"])
        b=triage.triage_title(exch["title"],exch["title"].split("：",1)[0])
        c=triage.triage_title(exch["title"].split("：",1)[-1],"")
        result={"ann_id":aid,"cninfo_title":orig["announcement_title"],
                "cninfo_security_name":orig["security_name"],"cninfo_result":a,
                "szse_title":exch["title"],"szse_historic_name_result":b,
                "szse_removed_prefix_result":c}
        if len({a["triage_state"],b["triage_state"],c["triage_state"]})>1:
            disagreements.append(result)
        output["cninfo_title_observations"].append(result)
    output["cninfo_to_szse_title_triad_disagreements"]=disagreements
    output["candidate_decision_mismatch_count"]=sum(
        r["cninfo_result"]["triage_state"]!=r["szse_historic_name_result"]["triage_state"]
        for r in output["cninfo_title_observations"])
    return output


def main():
    e=json.loads(SZSE.read_text(encoding="utf-8"))
    if e.get("evaluation",{}).get("full_source_row_reference_match") is not True:
        raise RuntimeError("SZSE_ROW_REFERENCE_UNVERIFIED")
    sessions=[]
    with sync_playwright() as pw:
        for _ in range(2):
            browser=pw.chromium.launch(headless=True)
            try:
                page=browser.new_page(locale="zh-CN")
                page.goto("https://www.cninfo.com.cn/",wait_until="domcontentloaded",timeout=90000)
                sessions.append({sz:query_month(page,sz) for sz in SIZES})
            finally:browser.close()
    outcome=compare(e["source_rows"],sessions)
    receipt={"schema":"V294_002667_APRIL_2023_CNINFO_ORIGINAL_TITLE_VS_SZSE_INPUT_DIAGNOSTIC_V1",
             "source_org_route":"CURRENT_CNINFO_002667_9900022274_NOT_HISTORICAL_PIT_CERTIFICATION",
             "frozen_triage_module":"scripts/v284_candidate_triage.py",
             "comparison_date_range":[START,END],"evaluation":outcome}
    OUT.write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({k:v for k,v in outcome.items() if k not in
        ("cninfo_title_observations","cninfo_to_szse_title_triad_disagreements")},ensure_ascii=False))
    if not outcome["all_four_april_censuses_equal_to_szse"]:
        raise SystemExit("CNINFO_APRIL_SOURCE_TITLE_CENSUS_UNRECONCILED")
if __name__=="__main__":main()
