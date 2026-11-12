"""Bounded CNINFO direct-date source check of one 2023 disclosure.

Only SZSE:002667 2023-08-31; two clean browsers and two page sizes.
Never converts a single-day result into full frozen-range completeness.
"""
import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright
import v291_negative_space_batch1 as base

DAY="2023-08-31"
TARGET="1217706310"
ORG="9900022274"  # From current official CNINFO public disclosure page; not historical PIT proof.
OUT=Path("evidence/V2.9.4_CNINFO_002667_20230831_DIRECT_DAY_1.json")


def query_day(page, size):
    payload={"column":"szse","tabName":"fulltext","plate":"sz",
             "stock":"002667,"+ORG,"searchkey":"","secid":"","category":"",
             "trade":"","seDate":DAY+"~"+DAY,"sortName":"","sortType":"",
             "isHLtitle":"true","pageNum":"1","pageSize":str(size)}
    totals=[]; page_counts=[]; ids=[]; target_rows=[]; errors=[]
    for num in range(1,12):
        response=json.loads(base.post(page,{**payload,"pageNum":str(num)}))
        total=int(response.get("totalRecordNum") or response.get("totalAnnouncement") or 0)
        rows=response.get("announcements") or []
        totals.append(total);page_counts.append(len(rows))
        for row in rows:
            aid=str(row.get("announcementId") or "").strip()
            ms=str(row.get("announcementTime") or "").strip()
            sec=str(row.get("secCode") or "").strip()
            if not aid or not re.fullmatch(r"\d{10}|\d{13}",ms) or sec!="002667":
                errors.append("MISSING_ID_TIMESTAMP_OR_WRONG_ISSUER")
                continue
            instant=datetime.fromtimestamp(int(ms)/(1000 if len(ms)==13 else 1),tz=timezone.utc)
            local=instant.astimezone(base.SH).date().isoformat()
            path,pdate=base.locator(row.get("adjunctUrl"),aid)
            if local!=DAY or pdate!=DAY:
                errors.append("OUT_OF_DAY_OR_PDF_PATH_DATE_MISMATCH:"+aid)
            ids.append(aid)
            if aid==TARGET:
                target_rows.append({"id":aid,"local_date":local,"pdf_path_day":pdate,
                                    "pdf_path":path,"stock_code":sec,
                                    "short_name":str(row.get("secName") or "").strip(),
                                    "title":str(row.get("announcementTitle") or "").strip(),
                                    "timestamp":ms})
        if len(rows)<size:
            break
    else:
        errors.append("PAGE_RUNAWAY")
    counts=Counter(ids); uniq=sorted(counts)
    closed=(len(set(totals))==1 and len(ids)==len(uniq)==totals[0]
            and not errors and bool(ids) and len(target_rows)==1)
    return {"page_size":size,"reported_totals":sorted(set(totals)),
            "page_counts":page_counts,"raw_count":len(ids),"distinct_count":len(uniq),
            "duplicate_ids":sorted(k for k,v in counts.items() if v>1),
            "ids":uniq,"sorted_id_sha256":hashlib.sha256(("\n".join(uniq)+"\n").encode()).hexdigest(),
            "target_rows":target_rows,"errors":errors,"closed":closed}


def evaluate(sessions):
    if len(sessions)!=2 or any(set(x)!={20,30} for x in sessions):
        raise ValueError("EXACT_TWO_SESSIONS_TWO_PAGE_SIZES_REQUIRED")
    runs=[r for s in sessions for r in s.values()]
    complete=all(x["closed"] for x in runs)
    repeat_equal=all(runs[0]["ids"]==r["ids"] for r in runs[1:])
    totals_equal=all(runs[0]["reported_totals"]==r["reported_totals"] for r in runs[1:])
    target=[r["target_rows"][0] for r in runs if len(r["target_rows"])==1]
    metadata_equal=len(target)==4 and all(t==target[0] for t in target)
    passed=bool(complete and repeat_equal and totals_equal and metadata_equal)
    return {"direct_day_technical_consistency_pass":passed,
            "all_runs_closed":complete,"four_exact_id_sets_equal":repeat_equal,
            "reported_totals_equal":totals_equal,"target_metadata_equal":metadata_equal,
            "target_verified_metadata":target[0] if metadata_equal else None,
            "historical_full_range_complete":False,
            "batch3_aggregation_authorized":False,
            "batch4_authorized":False,"outcomes_consumed":False}


def main():
    sessions=[]
    with sync_playwright() as pw:
        for _ in range(2):
            browser=pw.chromium.launch(headless=True)
            try:
                page=browser.new_page(locale="zh-CN")
                page.goto("https://www.cninfo.com.cn/",wait_until="domcontentloaded",timeout=90000)
                sessions.append({size:query_day(page,size) for size in (30,20)})
            finally:
                browser.close()
    verdict=evaluate(sessions)
    result={"schema":"V294_CNINFO_002667_20230831_SOURCE_DAY_AUDIT_V1",
            "security_id":"SZSE:002667","date_range":[DAY,DAY],
            "org_route_source":"CNINFO_CURRENT_PUBLIC_SEARCH_002667_ORGID_9900022274",
            "sessions":sessions,"evaluation":verdict}
    OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(verdict,ensure_ascii=False))
    if not verdict["direct_day_technical_consistency_pass"]:
        raise SystemExit("CNINFO_SINGLE_DAY_TECHNICAL_CONSISTENCY_BLOCKED")


if __name__=="__main__":
    main()
