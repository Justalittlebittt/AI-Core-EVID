"""Read-only two-session August 2023 CNINFO query partition consistency audit.

No frozen Batch-3 rerun, scientific admission, returns, or quote collection.
"""
import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright
import v291_negative_space_batch1 as base

OUT=Path("evidence/V2.9.4_CNINFO_002667_AUGUST_SPLIT_AUDIT_1.json")
PARTS={
    "first_half":("2023-08-01","2023-08-15"),
    "second_half":("2023-08-16","2023-08-31"),
    "full_august":("2023-08-01","2023-08-31"),
    "left_boundary":("2023-07-31","2023-07-31"),
    "right_boundary":("2023-09-01","2023-09-01"),
}
TARGETS=("1217598366","1217706310")


def inspect_pages(page, org, date_range):
    start,end=date_range
    payload={"column":"szse","tabName":"fulltext","plate":"sz",
             "stock":"002667,"+org,"searchkey":"","secid":"",
             "category":"","trade":"","seDate":start+"~"+end,
             "sortName":"","sortType":"","isHLtitle":"true",
             "pageNum":"1","pageSize":"30"}
    ids=[]; totals=[]; rows=[]; page_counts=[]
    for n in range(1,50):
        response=json.loads(base.post(page,{**payload,"pageNum":str(n)}))
        total=int(response.get("totalRecordNum") or response.get("totalAnnouncement") or 0)
        current=response.get("announcements") or []
        totals.append(total);page_counts.append(len(current))
        for entry in current:
            aid=str(entry.get("announcementId") or "").strip()
            ms=str(entry.get("announcementTime") or "").strip()
            if not aid or not re.fullmatch(r"\d{10}|\d{13}",ms):
                raise RuntimeError("MISSING_ANNOUNCEMENT_ID_OR_TIMESTAMP")
            instant=datetime.fromtimestamp(int(ms)/(1000 if len(ms)==13 else 1),tz=timezone.utc)
            local_day=instant.astimezone(base.SH).date().isoformat()
            ids.append(aid)
            if aid in TARGETS:
                rows.append({"announcement_id":aid,"timestamp_utc":instant.isoformat(),
                             "local_date":local_day,
                             "source_url":str(entry.get("adjunctUrl") or "")})
            if not start<=local_day<=end:
                rows.append({"announcement_id":aid,"local_date":local_day,
                             "error":"ANNOUNCEMENT_DATE_OUTSIDE_PARTITION"})
        if len(current)<30:
            break
    else:
        raise RuntimeError("PARTITION_PAGE_RUNAWAY")
    counts=Counter(ids)
    unique=sorted(counts)
    stable_total=len(set(totals))==1
    complete=(stable_total and len(ids)==len(unique)==totals[0]
              and all(ids) and not any(r.get("error") for r in rows))
    return {"range":[start,end],"reported_totals":sorted(set(totals)),
            "page_counts":page_counts,"raw_count":len(ids),
            "unique_count":len(unique),
            "duplicate_ids":sorted(k for k,v in counts.items() if v>1),
            "ids":unique,"ids_sha256":hashlib.sha256(("\n".join(unique)+"\n").encode()).hexdigest(),
            "tracked_announcements":rows,"complete":complete}


def evaluate_sessions(sessions):
    if len(sessions)!=2 or any(set(s)!=set(PARTS) for s in sessions):
        raise ValueError("EXACT_TWO_COMPLETE_SESSIONS_REQUIRED")
    stable={key:(sessions[0][key]["complete"] and sessions[1][key]["complete"]
                 and sessions[0][key]["ids"]==sessions[1][key]["ids"]
                 and sessions[0][key]["reported_totals"]==sessions[1][key]["reported_totals"])
            for key in PARTS}
    left=set(sessions[0]["first_half"]["ids"])
    right=set(sessions[0]["second_half"]["ids"])
    full=set(sessions[0]["full_august"]["ids"])
    boundaries=set(sessions[0]["left_boundary"]["ids"])|set(sessions[0]["right_boundary"]["ids"])
    partitions_match_full=(not left.intersection(right) and left|right==full)
    no_boundary_overlap=not full.intersection(boundaries)
    passed=all(stable.values()) and partitions_match_full and no_boundary_overlap
    return {"stable_partitions":stable,"halves_equal_full_august":partitions_match_full,
            "no_boundary_overlap":no_boundary_overlap,
            "august_unique_count":len(full),
            "tracked_id_presence":{x:{
                "august":x in full,"left_boundary":x in sessions[0]["left_boundary"]["ids"],
                "right_boundary":x in sessions[0]["right_boundary"]["ids"]}
                for x in TARGETS},
            "technical_consistency_pass":passed,
            "scientific_completeness_certified":False,
            "batch3_aggregation_authorized":False,
            "batch4_authorized":False,
            "outcomes_consumed":False}


def main():
    mapping={x["canonical_security_id"]:x for x in base.read_rows(base.MAP)}
    entry=mapping["SZSE:002667"]
    sessions=[]
    with sync_playwright() as pw:
        for session_index in (1,2):
            browser=pw.chromium.launch(headless=True)
            try:
                page=browser.new_page(locale="zh-CN")
                page.goto("https://www.cninfo.com.cn/",wait_until="domcontentloaded",timeout=90000)
                org=entry.get("validated_org_id") or base.resolve_org(page,"002667")
                if not org:raise RuntimeError("OFFICIAL_ISSUER_ID_UNKNOWN")
                parts={key:inspect_pages(page,org,interval) for key,interval in PARTS.items()}
                sessions.append(parts)
            finally:
                browser.close()
    evaluation=evaluate_sessions(sessions)
    result={"schema":"V294_CNINFO_002667_AUGUST_TWO_SESSION_READ_ONLY_V1",
            "security_id":"SZSE:002667",
            "frozen_original_range":["2023-01-01","2024-12-30"],
            "audit_partitions":PARTS,"sessions":sessions,"evaluation":evaluation}
    OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(evaluation,ensure_ascii=False))
    if not evaluation["technical_consistency_pass"]:
        raise SystemExit("AUGUST_PARTITION_CONSISTENCY_BLOCKED")


if __name__=="__main__":
    main()
