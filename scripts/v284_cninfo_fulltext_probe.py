from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from urllib.parse import urlencode

from playwright.sync_api import sync_playwright

ENDPOINT = "https://www.cninfo.com.cn/new/hisAnnouncement/query"
HOME = "https://www.cninfo.com.cn/"
TERM = "人工智能"
WINDOW = "2026-09-01~2026-09-22"
STREAMS = [
    ("sse", "sh"),
    ("szse", "sz"),
]

def stable_sha256(obj) -> str:
    b=json.dumps(obj,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()
    return hashlib.sha256(b).hexdigest()

def one(api, column: str, plate: str, term: str = TERM) -> dict:
    payload = {
        "pageNum": "1",
        "pageSize": "30",
        "tabName": "fulltext",
        "column": column,
        "stock": "",
        "searchkey": term,
        "secid": "",
        "plate": plate,
        "category": "",
        "trade": "",
        "seDate": WINDOW,
        "sortName": "time",
        "sortType": "desc",
        "isHLtitle": "true",
    }
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
    if r.status != 200:
        raise RuntimeError(f"CNINFO_HTTP_{r.status}:{column}")
    obj=r.json()
    anns=obj.get("announcements") or []
    total=int(obj.get("totalRecordNum") or obj.get("totalAnnouncement") or 0)
    sample=[]
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
        "query": payload,
        "http_status": r.status,
        "server_total": total,
        "first_page_count": len(anns),
        "first_page_sample": sample,
        "response_shape_has_announcements": isinstance(obj.get("announcements"), list),
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
        rows=[one(api,c,p) for c,p in STREAMS]
        api.dispose()

    checks = {
        "home_http_200": True,
        "both_streams_http_200": all(x["http_status"]==200 for x in rows),
        "both_response_shapes_valid": all(x["response_shape_has_announcements"] for x in rows),
        "fulltext_mode_frozen": all(x["query"]["tabName"]=="fulltext" for x in rows),
        "searchkey_exact": all(x["query"]["searchkey"]==TERM for x in rows),
        "candidate_results_nonempty": sum(x["server_total"] for x in rows) > 0,
    }
    receipt={
        "schema":"AI_CORE_EVID_V2_8_4_CNINFO_FULLTEXT_PROBE_V1",
        "started_at_utc":started.isoformat(),
        "finished_at_utc":datetime.now(timezone.utc).isoformat(),
        "term":TERM,
        "window":WINDOW,
        "streams":rows,\n        "szse_transport_matrix_control_term": CONTROL_TERM,\n        "szse_transport_matrix": sz_transport_matrix,
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
