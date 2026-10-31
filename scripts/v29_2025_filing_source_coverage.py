#!/usr/bin/env python3
"""Retrospective FY2024 vendor filing-coverage acquisition for fixed 128 issuers.

Reuse the existing Eastmoney financial-summary source adapter. This is a 2026
retrieval of 2025-noticed fiscal reports, NOT genuine historical PIT evidence.
Every sampled issuer is retained; no 2025 price outcomes or BUY authority.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from v29_growth_candidate_snapshot import fetch_page, _security
from v29_historical_universe_sampling import build_frame

PERIOD = "2024-12-31"
NOTICE_BEFORE = "2025-07-01"
MAX_PAGES = 40
FIELDS = [
    "security_id", "coverage_status", "matched_vendor_rows", "vendor_announcement_dates",
    "vendor_update_dates", "source_row_hashes", "vendor_revenue_yuan",
    "vendor_parent_profit_yuan", "original_pdf_url", "original_pdf_bytes_preserved",
    "historical_pit_certified",
]

def digest(blob):
    return hashlib.sha256(blob).hexdigest()

def valid_pages(raw_pages):
    """One validation at the incoming vendor-data trust boundary."""
    if not raw_pages or len(raw_pages) > MAX_PAGES:
        raise ValueError("INVALID_SOURCE_PAGE_COUNT")
    all_rows, page_receipts, expected = [], [], None
    for page_no, raw in enumerate(raw_pages, 1):
        if not isinstance(raw, bytes):
            raise ValueError("SOURCE_PAGE_MUST_BE_RAW_BYTES")
        doc = json.loads(raw)
        block = doc.get("result")
        if doc.get("success") is False or not isinstance(block, dict):
            raise ValueError("VENDOR_SOURCE_RESPONSE_FAILED")
        count, pages, records = block.get("count"), block.get("pages"), block.get("data")
        if type(count) is not int or type(pages) is not int or not isinstance(records, list):
            raise ValueError("VENDOR_PAGINATION_SCHEMA_INVALID")
        if expected is None:
            expected = (count, pages)
        elif (count, pages) != expected:
            raise ValueError("VENDOR_PAGINATION_CHANGED_DURING_CAPTURE")
        all_rows.extend(records)
        page_receipts.append({"page": page_no, "sha256": digest(raw), "rows": len(records)})
    if len(raw_pages) != expected[1] or len(all_rows) != expected[0]:
        raise ValueError("VENDOR_PAGINATION_OR_ROW_TOTAL_INCOMPLETE")
    return all_rows, page_receipts

def match_fixed_sample(frame, source_rows, page_receipts):
    ids = frame["selected_ids"]
    grouped = defaultdict(list)
    rejected = {"non_a_share_identity": 0, "wrong_report_period": 0,
                "notice_missing_or_out_of_scope": 0}
    for row in source_rows:
        sid = _security(row)
        if sid is None:
            rejected["non_a_share_identity"] += 1
            continue
        if str(row.get("REPORTDATE", ""))[:10] != PERIOD:
            rejected["wrong_report_period"] += 1
            continue
        notice = row.get("NOTICE_DATE")
        if not isinstance(notice, str) or not ("2025-01-01" <= notice[:10] < NOTICE_BEFORE):
            rejected["notice_missing_or_out_of_scope"] += 1
            continue
        grouped[sid].append(row)
    output = []
    for sid in ids:
        matches = grouped.get(sid, [])
        dates = sorted({str(x["NOTICE_DATE"])[:10] for x in matches})
        updates = sorted({str(x["UPDATE_DATE"])[:10] for x in matches if x.get("UPDATE_DATE")})
        hashes = sorted(digest(json.dumps(x, ensure_ascii=False, sort_keys=True,
                                        separators=(",", ":")).encode()) for x in matches)
        if not matches:
            status = "NOT_FOUND_IN_VENDOR_CUTOFF_QUERY_NOT_PROOF_OF_NO_2025_REPORT"
        elif len(matches) > 1:
            status = "MULTIPLE_VENDOR_RECORDS_VERSION_NOT_UNIQUELY_RESOLVED"
        elif updates and updates[-1] >= NOTICE_BEFORE:
            status = "VENDOR_ROW_UPDATED_AFTER_2025_CUTOFF_NOT_ASOF_CERTIFIED"
        else:
            status = "SINGLE_VENDOR_SUMMARY_RECORD_NOT_OFFICIAL_PDF_CERTIFIED"
        one = matches[0] if len(matches) == 1 else {}
        output.append({
            "security_id": sid,
            "coverage_status": status,
            "matched_vendor_rows": len(matches),
            "vendor_announcement_dates": dates,
            "vendor_update_dates": updates,
            "source_row_hashes": hashes,
            "vendor_revenue_yuan": one.get("TOTAL_OPERATE_INCOME"),
            "vendor_parent_profit_yuan": one.get("PARENT_NETPROFIT"),
            "original_pdf_url": None,
            "original_pdf_bytes_preserved": False,
            "historical_pit_certified": False,
        })
    return {
        "schema": "V29_2025_128_ISSUER_RETROSPECTIVE_FINANCIAL_SOURCE_COVERAGE_V1",
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "vendor": "EASTMONEY_RPT_LICO_FN_CPD_UNOFFICIAL",
        "fiscal_period_end": PERIOD,
        "vendor_notice_date_cutoff_exclusive": NOTICE_BEFORE,
        "frame_date": frame["frame_date"],
        "frame_population_count": frame["population_count"],
        "full_selected_issuer_count": 128,
        "full_selected_issuer_ids_sha256": frame["selected_ids_sha256"],
        "total_vendor_rows": len(source_rows),
        "source_pages": page_receipts,
        "rejected_unqualified_vendor_rows": rejected,
        "fixed_sample_count": len(output),
        "vendor_metadata_matched_count": sum(x["matched_vendor_rows"]>0 for x in output),
        "unmatched_count": sum(x["matched_vendor_rows"]==0 for x in output),
        "multiple_version_count": sum(x["matched_vendor_rows"]>1 for x in output),
        "original_issuer_pdf_sha256_certified_count": 0,
        "original_report_pdf_bytes_archived": False,
        "retrospective_vendor_vintage_not_asof_certified": True,
        "stock_selection_precedes_this_source_capture_but_not_2025_outcomes": True,
        "independent_oos_validated": False,
        "trade_authorized": False,
        "live_buy_eligibility": "NOT_AUTHORIZED",
        "rows": output,
    }

def acquire_pages(fetch=fetch_page):
    first = fetch(PERIOD, 1, notice_before=NOTICE_BEFORE)
    doc=json.loads(first)
    block=doc.get("result") or {}
    total=block.get("pages")
    if type(total) is not int or not 1 <= total <= MAX_PAGES:
        raise ValueError("VENDOR_PAGE_COUNT_INVALID")
    pages=[first]+[fetch(PERIOD, p, notice_before=NOTICE_BEFORE) for p in range(2,total+1)]
    return pages

def collect(out, fetch=fetch_page):
    frame=build_frame()
    if out.exists():
        raise ValueError("NO_OVERWRITE_OF_PRIOR_SOURCE_CAPTURE")
    pages=acquire_pages(fetch)
    rows, receipts=valid_pages(pages)
    report=match_fixed_sample(frame,rows,receipts)
    if len(report["rows"])!=128:
        raise ValueError("FIXED_SAMPLE_CARDINALITY_VIOLATED")
    out.mkdir(parents=True)
    (out/"raw_vendor_pages").mkdir()
    for i, raw in enumerate(pages,1):
        (out/"raw_vendor_pages"/f"page-{i:03d}.json").write_bytes(raw)
    (out/"coverage.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    with (out/"coverage.csv").open("w",encoding="utf-8",newline="") as f:
        writer=csv.DictWriter(f,fieldnames=FIELDS)
        writer.writeheader()
        for row in report["rows"]:
            writer.writerow({**row,
                             "vendor_announcement_dates":"|".join(row["vendor_announcement_dates"]),
                             "vendor_update_dates":"|".join(row["vendor_update_dates"]),
                             "source_row_hashes":"|".join(row["source_row_hashes"])})
    print(json.dumps({k:v for k,v in report.items() if k not in ("rows","source_pages")},
                     ensure_ascii=False),flush=True)
    return report

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--out",type=Path)
    parser.add_argument("--probe",action="store_true",help="Query just page 1 and report actual source schema")
    args=parser.parse_args()
    if args.probe:
        raw=fetch_page(PERIOD,1,notice_before=NOTICE_BEFORE)
        x=json.loads(raw)
        d=x.get("result") or {}
        print(json.dumps({"real_source_response":x.get("success"),
                          "pages":d.get("pages"),"total_rows":d.get("count"),
                          "page1_rows":len(d.get("data") or []),
                          "not_an_original_PDF_or_OOS":True},ensure_ascii=False))
    elif args.out:
        collect(args.out)
    else:
        parser.error("--out required unless --probe")

if __name__=="__main__":
    main()
