#!/usr/bin/env python3
"""Acquire FY2024 ORIGINAL annual-report evidence for the frozen 128-name 2025 frame.

2025 filings are queried retrospectively in 2026: NO pristine PIT, OOS, or BUY.
Unknown / blocked / missing cases remain explicit; never silently drop names.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from v29_historical_universe_sampling import build_frame

SEARCH_URL = "https://www.cninfo.com.cn/new/information/topSearch/query"
ANNOUNCEMENTS_URL = "https://www.cninfo.com.cn/new/hisAnnouncement/query"
PDF_BASE = "https://static.cninfo.com.cn/"
MAX_PDF_BYTES = 25_000_000
BEIJING = timezone(timedelta(hours=8))
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
    "Referer": "https://www.cninfo.com.cn/new/commonUrl/pageOfSearch?url=disclosure/list/search",
    "Origin": "https://www.cninfo.com.cn",
    "X-Requested-With": "XMLHttpRequest",
}
FIELDNAMES = [
    "security_id", "status", "query_error", "annual_report_title", "announcement_day",
    "announcement_id", "original_pdf_url", "announcement_response_sha256",
    "version_count", "version_dates", "pdf_sha256", "pdf_bytes", "pdf_status",
    "source_vintage_verified_pit", "original_pdf_bytes_durable_in_git",
]

def checksum(raw):
    return hashlib.sha256(raw).hexdigest()

def _post(url, params, opener=urlopen):
    payload = urlencode(params).encode("utf-8")
    request = Request(url, payload, headers={**HEADERS, "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"})
    with opener(request, timeout=9) as response:
        raw = response.read(2_000_001)
    if len(raw) > 2_000_000:
        raise ValueError("SOURCE_RESPONSE_TOO_LARGE")
    return json.loads(raw), raw

def _org_id(stock_id):
    exchange, code = stock_id.split(":")
    return ("gssh0" if exchange == "SSE" else "gssz0") + code

def _resolve_org_id(code, opener):
    obj, _ = _post(SEARCH_URL, {"keyWord": code, "maxNum": "10"}, opener)
    data = obj if isinstance(obj, list) else (obj.get("stockList") or obj.get("data") or [])
    ids = set()
    for item in data:
        if not isinstance(item, dict):
            continue
        candidate = item.get("orgId") or item.get("code")
        if isinstance(candidate, str) and re.fullmatch(r"(gssh|gssz)\d+|\d{8,12}", candidate):
            ids.add(candidate)
    return sorted(ids)

def _announcement_pages(stock_id, org, opener):
    exchange, code = stock_id.split(":")
    rows, blobs = [], []
    for page in range(1, 5):
        obj, raw = _post(ANNOUNCEMENTS_URL, {
            "stock": f"{code},{org}", "tabName": "fulltext",
            "column": "sse" if exchange == "SSE" else "szse",
            "category": "category_ndbg_szsh",
            "seDate": "2025-01-01~2025-12-31",
            "pageNum": str(page), "pageSize": "30", "isHLtitle": "false",
        }, opener)
        if not isinstance(obj, dict) or not isinstance(obj.get("announcements"), list):
            raise ValueError("CNINFO_ANNOUNCEMENT_SCHEMA_INVALID")
        rows.extend(obj["announcements"])
        blobs.append(raw)
        total = obj.get("totalpages", 1)
        if page >= int(total):
            return rows, blobs
    raise ValueError("MORE_THAN_FOUR_ANNOUNCEMENT_PAGES")

def _annual_versions(stock_id, announcements):
    code = stock_id.split(":")[1]
    found = []
    for x in announcements:
        if str(x.get("secCode", "")) != code:
            continue
        title = re.sub(r"<[^>]+>", "", str(x.get("announcementTitle", "")))
        compact = re.sub(r"\s+", "", title)
        if ("2024年年度报告" not in compact or "摘要" in compact
                or "英文" in compact or "提示性公告" in compact):
            continue
        stamp = x.get("announcementTime")
        rel = str(x.get("adjunctUrl") or "")
        if not re.fullmatch(r"finalpage/\d{4}-\d\d-\d\d/\d+\.PDF", rel):
            continue
        try:
            date_str = datetime.fromtimestamp(int(stamp) / 1000, tz=BEIJING).date().isoformat()
        except (TypeError, ValueError, OverflowError, OSError):
            continue
        if not date_str.startswith("2025-"):
            continue
        found.append({
            "title": title, "day": date_str, "id": rel.rsplit("/", 1)[-1][:-4],
            "url": PDF_BASE + rel,
        })
    found.sort(key=lambda r: (r["day"], r["url"]))
    return found

def _pdf_capture(url, destination, opener=urlopen):
    request = Request(url, headers={"User-Agent": HEADERS["User-Agent"], "Referer": HEADERS["Referer"]})
    chunks, size = [], 0
    with opener(request, timeout=20) as response:
        while True:
            chunk = response.read(65536)
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_PDF_BYTES:
                return {"pdf_status": "PDF_EXCEEDS_25MB_LIMIT", "pdf_sha256": None, "pdf_bytes": None}
            chunks.append(chunk)
    raw = b"".join(chunks)
    if not raw.startswith(b"%PDF-") or b"%%EOF" not in raw[-8192:]:
        return {"pdf_status": "PDF_SIGNATURE_OR_TRAILER_NOT_VERIFIED", "pdf_sha256": None, "pdf_bytes": None}
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(raw)
    return {"pdf_status": "FULL_PDF_BYTES_CAPTURED_IN_SHORT_LIVED_ACTIONS_ARTIFACT",
            "pdf_sha256": checksum(raw), "pdf_bytes": len(raw)}

def _row(sid, status, error=""):
    return {
        "security_id": sid, "status": status, "query_error": error,
        "annual_report_title": None, "announcement_day": None,
        "announcement_id": None, "original_pdf_url": None,
        "announcement_response_sha256": None, "version_count": 0,
        "version_dates": [], "pdf_sha256": None, "pdf_bytes": None,
        "pdf_status": "NOT_ATTEMPTED", "source_vintage_verified_pit": False,
        "original_pdf_bytes_durable_in_git": False,
    }

def evaluate_one(sid, opener=urlopen):
    """Return one row and raw JSON responses. API errors do not imply no filing."""
    try:
        announcements, blobs = _announcement_pages(sid, _org_id(sid), opener)
        if not announcements:
            org_ids = _resolve_org_id(sid.split(":")[1], opener)
            for org in org_ids:
                if org == _org_id(sid):
                    continue
                alt_rows, alt_blobs = _announcement_pages(sid, org, opener)
                if alt_rows:
                    announcements, blobs = alt_rows, alt_blobs
                    break
    except (HTTPError, URLError, TimeoutError, OSError, ValueError, TypeError, json.JSONDecodeError) as e:
        code = f"HTTP_{e.code}" if isinstance(e, HTTPError) else type(e).__name__
        return _row(sid, "QUERY_FAILED_NOT_PROOF_OF_ABSENCE", code), []
    versions = _annual_versions(sid, announcements)
    if not versions:
        r = _row(sid, "NO_MATCHING_FY2024_FULL_REPORT_IN_RETURNED_2025_METADATA")
        r["announcement_response_sha256"] = checksum(b"".join(blobs))
        return r, blobs
    original = versions[0]
    r = _row(sid, "FULL_REPORT_METADATA_IDENTIFIED_NOT_PDF_CERTIFIED")
    r.update({
        "annual_report_title": original["title"],
        "announcement_day": original["day"],
        "announcement_id": original["id"],
        "original_pdf_url": original["url"],
        "announcement_response_sha256": checksum(b"".join(blobs)),
        "version_count": len(versions),
        "version_dates": [x["day"] for x in versions],
    })
    return r, blobs

def collect(out, limit=128, pdf_limit=8, opener=urlopen):
    frame = build_frame()
    selected = frame["selected_ids"][:limit]
    if limit < 1 or limit > 128 or pdf_limit < 0 or pdf_limit > limit:
        raise ValueError("INVALID_FIXED_SAMPLE_SLICE")
    if out.exists():
        raise ValueError("CANNOT_OVERWRITE_EXISTING_CAPTURE")
    out.mkdir(parents=True)
    (out / "source_json").mkdir()
    rows = []
    consecutive_errors = 0
    for i, sid in enumerate(selected):
        if consecutive_errors >= 4:
            row, blobs = _row(sid, "UNQUERIED_SOURCE_UNAVAILABLE_CIRCUIT_BREAK"), []
        else:
            row, blobs = evaluate_one(sid, opener)
            consecutive_errors = consecutive_errors + 1 if row["status"].startswith("QUERY_FAILED") else 0
        rows.append(row)
        if blobs:
            (out / "source_json" / (sid.replace(":", "-") + ".json")).write_bytes(
                b"\n".join(blobs))
        if i < pdf_limit and row["original_pdf_url"]:
            try:
                captured = _pdf_capture(row["original_pdf_url"],
                                        out / "pdf" / (sid.replace(":", "-") + ".pdf"), opener)
                row.update(captured)
                if row["pdf_sha256"]:
                    row["status"] = "ORIGINAL_PDF_FULL_BYTES_CAPTURED"
            except (HTTPError, URLError, TimeoutError, OSError) as e:
                row["pdf_status"] = "PDF_FETCH_FAILED_" + (f"HTTP_{e.code}" if isinstance(e, HTTPError) else type(e).__name__)
        elif row["original_pdf_url"]:
            row["pdf_status"] = "NOT_REQUESTED_BOUNDED_SOURCE_PROBE"
        print(f"ISSUER {i+1}/{len(selected)} {sid} {row['status']} {row['pdf_status']}", flush=True)
        if i < len(selected)-1:
            time.sleep(0.15)
    summary = {
        "schema": "V29_128_ISSUER_FY2024_ORIGINAL_REPORT_COVERAGE_V1",
        "capture_timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "source": "CNINFO_HISTORICAL_ANNOUNCEMENTS_AND_BOUNDED_PDF",
        "report_fiscal_period_end": "2024-12-31",
        "announcement_query_range": ["2025-01-01", "2025-12-31"],
        "fixed_frame_date": frame["frame_date"],
        "frame_population_count": frame["population_count"],
        "full_sample_selection_sha256": frame["selected_ids_sha256"],
        "requested_issuer_count": len(selected),
        "full_sample_count": len(frame["selected_ids"]),
        "source_attempt_is_complete_128": limit == 128,
        "queried_issuers": sum(r["status"] != "UNQUERIED_SOURCE_UNAVAILABLE_CIRCUIT_BREAK" for r in rows),
        "metadata_identified": sum(r["original_pdf_url"] is not None for r in rows),
        "full_pdf_bytes_captured": sum(r["pdf_sha256"] is not None for r in rows),
        "failed_or_unresolved": sum(r["original_pdf_url"] is None for r in rows),
        "pdf_capture_limit_first_n": pdf_limit,
        "original_pdf_bytes_persisted_to_git": False,
        "source_capture_2026_not_original_2025_pit": True,
        "not_pristine_oos": True,
        "strategy_validated": False,
        "live_buy_eligibility": "NOT_AUTHORIZED",
        "rows": rows,
    }
    (out / "coverage.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with (out / "coverage.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDNAMES)
        w.writeheader()
        for row in rows:
            w.writerow({**row, "version_dates": "|".join(row["version_dates"])})
    print(json.dumps({k: v for k, v in summary.items() if k != "rows"}, ensure_ascii=False), flush=True)
    return summary

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--limit", type=int, default=128)
    p.add_argument("--pdf-limit", type=int, default=8)
    a = p.parse_args()
    collect(a.out, a.limit, a.pdf_limit)

if __name__ == "__main__":
    main()
