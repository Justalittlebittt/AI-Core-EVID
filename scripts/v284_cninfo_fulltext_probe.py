from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from urllib.parse import urlencode

from playwright.sync_api import sync_playwright

ENDPOINT = "https://www.cninfo.com.cn/new/hisAnnouncement/query"
HOME = "https://www.cninfo.com.cn/"
TERM = "人工智能"
STREAMS = [
    ("sse", "sh"),
    ("szse", "sz"),
]
WINDOWS = [
    "2026-09-01~2026-09-07",
    "2026-09-08~2026-09-14",
    "2026-09-15~2026-09-21",
    "2026-09-22~2026-09-22",
]

def stable_sha256(obj) -> str:
    b=json.dumps(obj,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()
    return hashlib.sha256(b).hexdigest()

def one(api, column: str, plate: str, window: str) -> dict:
    payload = {
        "pageNum": "1",
        "pageSize": "30",
        "tabName": "fulltext",
        "column": column,
        "stock": "",
        "searchkey": TERM,
        "secid": "",
        "plate": plate,
        "category": "",
        "trade": "",
        "seDate": window,
        "sortName": "time",
        "sortType": "desc",
        "isHLtitle": "true",
    }
    last_status=None
    for attempt in range(3):
        r=api.post(
            ENDPOINT,
            data=urlencode(payload),
            headers={
                "Content-Type":"application/x-www-form-urlencoded; charset=UTF-8",
                "X-Requested-With":"XMLHttpRequest",
                "Referer":"https://www.cninfo.com.cn/new/fulltextSearch",
            },
            timeout=60000,
        )
        last_status=r.status
        if r.status == 200:
            break
        if r.status not in (429, 500, 502, 503, 504):
            raise RuntimeError(f"CNINFO_HTTP_{r.status}:{column}:{window}")
        time.sleep(1.5 * (attempt + 1))
    if last_status != 200:
        raise RuntimeError(f"CNINFO_HTTP_{last_status}:{column}:{window}:after_retries")

    obj=r.json()
    raw_anns=obj.get("announcements")
    total=int(obj.get("totalRecordNum") or obj.get("totalAnnouncement") or 0)
    shape_valid=isinstance(raw_anns,list) or (raw_anns is None and total==0)
    if not shape_valid:
        raise RuntimeError(f"CNINFO_RESPONSE_SHAPE_INVALID:{column}:{window}")
    anns=raw_anns or []
    sample=[]
    ids=[]
    for a in anns:
        aid=str(a.get("announcementId") or "")
        if aid:
            ids.append(aid)
    for a in anns[:5]:
        sample.append({
            "announcement_id": str(a.get("announcementId") or ""),
            "sec_code": str(a.get("secCode") or ""),
            "sec_name": str(a.get("secName") or ""),
            "announcement_title": str(a.get("announcementTitle") or ""),
            "announcement_time": a.get("announcementTime"),
            "adjunct_url": str(a.get("adjunctUrl") or ""),
        })
    return {
        "column": column,
        "plate": plate,
        "window": window,
        "query": payload,
        "http_status": last_status,
        "server_total": total,
        "first_page_count": len(anns),
        "first_page_ids": ids,
        "first_page_sample": sample,
        "response_shape_valid": shape_valid,
    }

def main():
    started=datetime.now(timezone.utc)
    with sync_playwright() as pw:
        api=pw.request.new_context(
            extra_http_headers={
                "User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/153 Safari/537.36"
            }
        )
        home=api.get(HOME,timeout=30000)
        if home.status != 200:
            raise RuntimeError(f"CNINFO_HOME_HTTP_{home.status}")
        rows=[]
        for column,plate in STREAMS:
            for window in WINDOWS:
                rows.append(one(api,column,plate,window))
        api.dispose()

    by_stream={}
    for column,_plate in STREAMS:
        part=[x for x in rows if x["column"]==column]
        ids=[]
        for x in part:
            ids.extend(x["first_page_ids"])
        by_stream[key]={
            "windows":len(part),
            "http_200_all":all(x["http_status"]==200 for x in part),
            "shape_valid_all":all(x["response_shape_valid"] for x in part),
            "server_total_sum":sum(x["server_total"] for x in part),
            "unique_first_page_announcement_ids":len(set(ids)),
        }

    checks = {
        "home_http_200": True,
        "all_partition_requests_http_200": all(x["http_status"]==200 for x in rows),
        "all_partition_shapes_valid": all(x["response_shape_valid"] for x in rows),
        "fulltext_mode_frozen": all(x["query"]["tabName"]=="fulltext" for x in rows),
        "searchkey_exact": all(x["query"]["searchkey"]==TERM for x in rows),
        "sse_candidate_results_nonempty": by_stream["sse"]["server_total_sum"] > 0,
        "szse_candidate_results_nonempty": by_stream["szse"]["server_total_sum"] > 0,
    }
    receipt={
        "schema":"AI_CORE_EVID_V2_8_4_CNINFO_FULLTEXT_PROBE_V2",
        "started_at_utc":started.isoformat(),
        "finished_at_utc":datetime.now(timezone.utc).isoformat(),
        "term":TERM,
        "partition_policy":"DETERMINISTIC_7_DAY_WINDOWS_WITH_FINAL_PARTIAL_WINDOW",
        "windows":WINDOWS,
        "streams":by_stream,
        "partition_results":rows,
        "checks":checks,
        "all_pass":all(checks.values()),
        "eligibility_effect":"NONE_CANDIDATE_HINT_TRANSPORT_ONLY",
        "real_security_classification_computed":False,
        "return_or_price_data_consumed":False,
    }
    receipt["receipt_sha256"]=stable_sha256(receipt)
    print(json.dumps(receipt,ensure_ascii=False,indent=2))
    if not receipt["all_pass"]:
        raise SystemExit(2)

if __name__=="__main__":
    main()
