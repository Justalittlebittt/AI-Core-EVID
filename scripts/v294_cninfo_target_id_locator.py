"""Read-only CNINFO identity/date check for one unresolved archived announcement ID.

Queries two historical page offsets in two clean sessions. No science admission.
"""
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from playwright.sync_api import sync_playwright
import v291_negative_space_batch1 as base

TARGET="1217706310"
OUT=Path("evidence/V2.9.4_CNINFO_002667_1217706310_IDENTITY_AUDIT_1.json")
OFFSETS=((30,8),(20,11))
CID="SZSE:002667"


def query_at(page,org,size,page_num):
    payload={"column":"szse","tabName":"fulltext","plate":"sz","stock":"002667,"+org,
             "searchkey":"","secid":"","category":"","trade":"",
             "seDate":base.START+"~"+base.END,"sortName":"","sortType":"",
             "isHLtitle":"true","pageNum":str(page_num),"pageSize":str(size)}
    obj=json.loads(base.post(page,payload))
    rows=obj.get("announcements") or []
    ids=[str(r.get("announcementId") or "").strip() for r in rows]
    matches=[]
    for entry in rows:
        if str(entry.get("announcementId") or "").strip()!=TARGET:
            continue
        ms=str(entry.get("announcementTime") or "").strip()
        if not re.fullmatch(r"\d{10}|\d{13}",ms):
            raise RuntimeError("TARGET_ANNOUNCEMENT_TIMESTAMP_INVALID")
        instant=datetime.fromtimestamp(int(ms)/(1000 if len(ms)==13 else 1),tz=timezone.utc)
        local=instant.astimezone(base.SH).date().isoformat()
        path,pdate=base.locator(entry.get("adjunctUrl"),TARGET)
        sec_code=str(entry.get("secCode") or "")
        if sec_code and sec_code!="002667":
            raise RuntimeError("TARGET_OFFICIAL_SECURITY_CODE_MISMATCH")
        matches.append({"announcement_id":TARGET,"announcement_time":ms,
                        "official_observed_day":local,"original_pdf_path_day":pdate,
                        "official_relative_pdf_path":path,
                        "sec_code":str(entry.get("secCode") or ""),
                        "sec_name":str(entry.get("secName") or ""),
                        "announcement_title":str(entry.get("announcementTitle") or "")})
    return {"page_size":size,"page_number":page_num,
            "reported_total":int(obj.get("totalRecordNum") or obj.get("totalAnnouncement") or 0),
            "raw_count":len(rows),
            "page_ids_sha256":hashlib.sha256(("\n".join(ids)+"\n").encode()).hexdigest(),
            "target_present":bool(matches),"target_rows":matches}


def evaluate(sessions):
    if len(sessions)!=2 or any(len(s)!=len(OFFSETS) for s in sessions):
        raise ValueError("TWO_COMPLETE_SOURCE_SESSIONS_REQUIRED")
    details=[row for s in sessions for page in s for row in page["target_rows"]]
    coherent=bool(details) and all(d==details[0] for d in details)
    # Both offsets per session are required to locate and agree, not just one.
    per_offset=all(page["target_present"] and len(page["target_rows"])==1
                   for s in sessions for page in s)
    time_path_agree=all(d["official_observed_day"]==d["original_pdf_path_day"]
                        for d in details)
    inside_range=all(base.START<=d["official_observed_day"]<=base.END for d in details)
    return {"target_id":TARGET,"source_metadata_reconciled":
            bool(coherent and per_offset and time_path_agree and inside_range),
            "all_four_offsets_found":per_offset,
            "metadata_agrees_across_queries":coherent,
            "timestamp_matches_official_path_day":time_path_agree,
            "date_inside_frozen_range":inside_range,
            "found_count":len(details),
            "verified_metadata":details[0] if coherent and details else None,
            "historical_full_range_complete":False,
            "batch3_aggregation_authorized":False,
            "batch4_authorized":False,
            "outcome_data_consumed":False}


def main():
    mapping={r["canonical_security_id"]:r for r in base.read_rows(base.MAP)}
    record=mapping[CID]
    sessions=[]
    with sync_playwright() as pw:
        for _ in range(2):
            browser=pw.chromium.launch(headless=True)
            try:
                page=browser.new_page(locale="zh-CN")
                page.goto("https://www.cninfo.com.cn/",wait_until="domcontentloaded",timeout=90000)
                # Reuse the exact issuer route preserved in the prior V2.9.4
                # scoped diagnostic source; live org autocomplete may return [].
                # This is a historical query binding, NOT identity certification.
                org=record.get("validated_org_id") or "9900036460"
                if str(record.get("security_code") or "002667")!="002667":
                    raise RuntimeError("FROZEN_SECURITY_CODE_MISMATCH")
                sessions.append([query_at(page,org,size,num) for size,num in OFFSETS])
            finally:
                browser.close()
    verdict=evaluate(sessions)
    result={"schema":"V294_CNINFO_002667_TARGET_ID_READ_ONLY_V1",
            "security_id":CID,"frozen_query_range":[base.START,base.END],
            "provenance":"TWO_INDEPENDENT_BROWSER_SESSIONS_TWO_HISTORICAL_PAGE_OFFSETS",
            "org_route_source":"PRIOR_V294_SCOPED_DIAGNOSTIC_9900036460_NOT_INDEPENDENT_IDENTITY_PROOF",
            "sessions":sessions,"evaluation":verdict}
    OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(verdict,ensure_ascii=False))
    if not verdict["source_metadata_reconciled"]:
        raise SystemExit("TARGET_ANNOUNCEMENT_IDENTITY_UNRECONCILED")


if __name__=="__main__":
    main()
