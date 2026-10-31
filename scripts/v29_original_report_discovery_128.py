#!/usr/bin/env python3
"""Discover actual 2025-issued FY2024 original annual-report PDFs for a frozen 128-issuer cohort.

Source: CNINFO topSearch orgId + category-filtered historical announcements.
Original PDF metadata discovery is NOT financial-field validation, source-vintage
certification, OOS alpha, or BUY authority. Never drop a missing or failed issuer.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import time
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from v29_historical_universe_sampling import build_frame

ROOT = Path(__file__).resolve().parents[1]
COVERAGE_PATH = ROOT / "research/V2.9_2025_128_FILING_SOURCE_COVERAGE.json"
BEIJING = timezone(timedelta(hours=8))
BASE = "https://www.cninfo.com.cn/new/"
PDF_BASE = "https://static.cninfo.com.cn/"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
    "Referer": "https://www.cninfo.com.cn/",
    "Origin": "https://www.cninfo.com.cn",
    "X-Requested-With": "XMLHttpRequest",
    "Accept": "application/json,text/plain,*/*",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
}
FULL = re.compile(r"2024(?:年)?(?:年度报告|年报)")
PDF_PATH = re.compile(r"finalpage/(2025-\d\d-\d\d)/(\d+\.PDF)", re.IGNORECASE)
OMIT = ("摘要", "更正", "修订", "已取消", "取消", "补充", "英文", "阿拉伯", "提示性", "SUMMARY", "ENGLISH", "ANNUAL REPORT")
EXPECTED_FRAME_HASH = "ded26da069f22888455ac080fbc2593ee9477a23bb0dc619569115cf4d7f73ac"

def _sha(b):
    return hashlib.sha256(b).hexdigest()

def _post(path, fields, opener=urlopen):
    request = Request(BASE + path, urlencode(fields).encode("utf-8"), headers=HEADERS)
    with opener(request, timeout=12) as response:
        raw = response.read(2_000_001)
    if len(raw) > 2_000_000:
        raise ValueError("CNINFO_RESPONSE_EXCEEDS_LIMIT")
    return json.loads(raw), raw

def _match_originals(announcements, code):
    candidates = []
    for item in announcements:
        if str(item.get("secCode") or "") != code:
            continue
        title = re.sub(r"<[^>]*>", "", html.unescape(str(item.get("announcementTitle") or "")))
        compact = re.sub(r"\s+", "", title)
        if not FULL.search(compact) or any(x.lower() in compact.lower() for x in OMIT):
            continue
        relative = str(item.get("adjunctUrl") or "")
        path = PDF_PATH.fullmatch(relative)
        if not path:
            continue
        ts = item.get("announcementTime")
        try:
            day = datetime.fromtimestamp(int(ts) / 1000, tz=BEIJING).date().isoformat()
        except (ValueError, TypeError, OSError, OverflowError):
            continue
        if day != path.group(1):
            # Inconsistent filing day must never be silently treated as verified.
            continue
        candidates.append({
            "title": title,
            "publication_day": day,
            "document_id": path.group(2)[:-4],
            "original_pdf_url": PDF_BASE + relative,
        })
    candidates.sort(key=lambda x: (x["publication_day"], x["document_id"]))
    return candidates

def locate(sid, request=_post):
    exchange, code = sid.split(":")
    raw_responses = {}
    try:
        names, raw = request("information/topSearch/query", {"keyWord": code, "maxNum": "10"})
        raw_responses["org_search"] = raw
        entries = names if isinstance(names, list) else (
            names.get("data") or names.get("stockList") or [])
        orgs = {str(item.get("orgId")) for item in entries if isinstance(item, dict)
                and str(item.get("code")) == code and item.get("orgId")}
        if len(orgs) != 1:
            return {"security_id": sid, "status": "ORG_ID_UNRESOLVED_OR_AMBIGUOUS",
                    "org_candidates": sorted(orgs), "original_candidates": []}, raw_responses
        org = next(iter(orgs))
        announcements = []
        for page in range(1, 5):
            doc, raw = request("hisAnnouncement/query", {
                "stock": code + "," + org, "tabName": "fulltext",
                "pageNum": str(page), "pageSize": "30",
                "column": "sse" if exchange == "SSE" else "szse",
                "plate": "", "category": "category_ndbg_szsh",
                "seDate": "2025-01-01~2025-12-31",
                "isHLtitle": "true", "searchkey": "",
            })
            raw_responses[f"annual_page_{page}"] = raw
            if not isinstance(doc, dict):
                raise ValueError("ANNOUNCEMENT_RESPONSE_NOT_OBJECT")
            found = doc.get("announcements")
            if found is None and int(doc.get("totalRecordNum") or 0) == 0:
                found = []
            if not isinstance(found, list):
                raise ValueError("ANNOUNCEMENT_LIST_INVALID")
            announcements.extend(found)
            if not doc.get("hasMore"):
                break
        else:
            raise ValueError("ANNUAL_REPORT_PAGINATION_EXCEEDED_4_PAGES")
        originals = _match_originals(announcements, code)
        if not originals:
            status = "NO_MATCHING_2024_FULL_REPORT_IN_SOURCE_QUERY"
            chosen = None
        else:
            earliest = originals[0]["publication_day"]
            first = [x for x in originals if x["publication_day"] == earliest]
            chosen = first[0] if len(first) == 1 else None
            status = ("FULL_ORIGINAL_PDF_URL_DISCOVERED" if chosen
                      else "MULTIPLE_SAME_DAY_ORIGINAL_PDFS_UNRESOLVED")
        return {
            "security_id": sid, "status": status,
            "org_id": org, "annual_announcement_count": len(announcements),
            "original_candidates": originals,
            "chosen": chosen,
        }, raw_responses
    except (HTTPError, URLError, TimeoutError, OSError, ValueError, TypeError) as exc:
        return {
            "security_id": sid, "status": "SOURCE_QUERY_FAILED_NOT_PROOF_OF_NO_REPORT",
            "error_type": f"HTTP_{exc.code}" if isinstance(exc, HTTPError) else type(exc).__name__,
            "original_candidates": [],
        }, raw_responses

def collect(out, limit=128, request=_post, sleep_seconds=0.18):
    if not 1 <= limit <= 128:
        raise ValueError("INVALID_BOUNDED_SAMPLE_LIMIT")
    if out.exists():
        raise ValueError("REFUSE_TO_OVERWRITE_SOURCE_SNAPSHOT")
    frame = build_frame()
    coverage = json.loads(COVERAGE_PATH.read_text(encoding="utf-8"))
    if frame["selected_ids_sha256"] != EXPECTED_FRAME_HASH:
        raise ValueError("FROZEN_FRAME_SHA_CHANGED")
    if (coverage.get("full_selected_issuer_ids_sha256") != EXPECTED_FRAME_HASH
            or len(coverage.get("rows", [])) != 128):
        raise ValueError("FINANCIAL_COVERAGE_IDENTITY_NOT_FROZEN")
    vendor = {row["security_id"]: row for row in coverage["rows"]}
    rows = []
    raw_sets = []
    failed_streak = 0
    for i, sid in enumerate(frame["selected_ids"][:limit], 1):
        if failed_streak >= 6:
            row, raw = {"security_id": sid,
                        "status": "UNQUERIED_AFTER_SIX_SOURCE_FAILURES",
                        "original_candidates": []}, {}
        else:
            row, raw = locate(sid, request)
            failed_streak = (failed_streak + 1 if row["status"] == "SOURCE_QUERY_FAILED_NOT_PROOF_OF_NO_REPORT"
                             else 0)
        record = vendor[sid]
        row["vendor_notice_dates"] = record["vendor_announcement_dates"]
        row["vendor_update_dates"] = record["vendor_update_dates"]
        row["original_pdf_bytes_sealed"] = False
        row["historical_asof_financial_fields_certified"] = False
        row["live_buy_eligibility"] = "NOT_AUTHORIZED"
        chosen = row.get("chosen")
        row["notice_date_matches_vendor"] = (
            bool(chosen) and chosen["publication_day"] in record["vendor_announcement_dates"])
        row["raw_request_sha256"] = {k: _sha(v) for k, v in raw.items()}
        rows.append(row)
        raw_sets.append((sid, raw))
        print(f"CNINFO {i:03d}/{limit:03d} {sid} {row['status']} "
              f"NOTICE_MATCH={row['notice_date_matches_vendor']}", flush=True)
        if i < limit and sleep_seconds:
            time.sleep(sleep_seconds)
    manifest = {
        "schema": "V29_FY2024_OFFICIAL_2025_ANNUAL_PDF_DISCOVERY_128_V1",
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "original_2025_notice_window": ["2025-01-01", "2025-12-31"],
        "retrospective_2026_source_query": True,
        "frozen_population_count": frame["population_count"],
        "frozen_sample_size": 128,
        "frozen_sample_sha256": EXPECTED_FRAME_HASH,
        "attempted_sample_count": limit,
        "full_128_coverage_attempted": limit == 128,
        "original_pdf_url_discovered_count": sum(bool(x.get("chosen")) for x in rows),
        "date_matched_vendor_count": sum(x["notice_date_matches_vendor"] for x in rows),
        "no_original_url_count": sum(not x.get("chosen") for x in rows),
        "query_failed_count": sum(x["status"] == "SOURCE_QUERY_FAILED_NOT_PROOF_OF_NO_REPORT" for x in rows),
        "original_pdf_binary_captured_count": 0,
        "financial_fields_original_document_reconciled_count": 0,
        "independent_oos_validated": False,
        "live_buy_eligibility": "NOT_AUTHORIZED",
        "rows": rows,
    }
    out.mkdir(parents=True)
    (out / "DISCOVERY_128.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with zipfile.ZipFile(out / "RAW_CNINFO_RESPONSES.zip", "w", zipfile.ZIP_DEFLATED,
                         compresslevel=8) as archive:
        for sid, raw in raw_sets:
            for name, blob in raw.items():
                archive.writestr(f"{sid.replace(':','-')}/{name}.json", blob)
    manifest["raw_source_zip_sha256"] = _sha((out / "RAW_CNINFO_RESPONSES.zip").read_bytes())
    (out / "DISCOVERY_128.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in manifest.items() if k != "rows"}, ensure_ascii=False), flush=True)
    return manifest

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=128)
    args = parser.parse_args()
    collect(args.out, args.limit)

if __name__ == "__main__":
    main()
