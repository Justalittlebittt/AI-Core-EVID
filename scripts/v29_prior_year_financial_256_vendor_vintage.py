#!/usr/bin/env python3
"""Retrospectively collect two fiscal years of financial source versions, 256 IDs.

Consumes frozen issuer frames, does NOT choose candidates or calculate returns.
Historical FY2022/FY2023 values returned in 2026 are not original-time PIT,
even when notice date is 2023/2024. Preserves missing issuers / duplicate
versions and hashes exact current vendor source bytes for later PDF crosscheck.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from collections import defaultdict
from datetime import datetime,timezone
from pathlib import Path

from v29_2023_2024_original_filing_discovery_256 import load_frozen_frames
from v29_2025_filing_source_coverage import valid_pages
from v29_growth_candidate_snapshot import fetch_page,_security

ROOT=Path(__file__).resolve().parents[1]
SCHEMA="V29_FY2022_FY2023_2X128_RETROSPECTIVE_VENDOR_FINANCIAL_SOURCE_V1"
DATA_FIELDS={
    "revenue_yuan":"TOTAL_OPERATE_INCOME",
    "parent_net_profit_yuan":"PARENT_NETPROFIT",
    "revenue_growth_yoy_pct":"YSTZ",
    "weighted_roe_pct":"WEIGHTAVG_ROE",
}
MAX_PAGES=40

def sha(b):
    return hashlib.sha256(b).hexdigest()

def acquire_year(fiscal,notice_before,fetch=fetch_page):
    first=fetch(fiscal,1,notice_before=notice_before)
    obj=json.loads(first)
    details=obj.get("result") or {}
    pages=details.get("pages")
    if type(pages) is not int or not 1<=pages<=MAX_PAGES:
        raise ValueError("HISTORICAL_VENDOR_PAGE_COUNT_INVALID")
    raw=[first]+[fetch(fiscal,p,notice_before=notice_before)
                 for p in range(2,pages+1)]
    data,receipts=valid_pages(raw)
    return data,raw,receipts

def match_frame(frame,vendor_rows):
    issue_year=frame["expected_issuer_publication_year"]
    fiscal=frame["report_period_end"]
    selected=frame["selected_ids"]
    grouped=defaultdict(list)
    for row in vendor_rows:
        sid=_security(row)
        if sid is None or sid not in selected:
            continue
        if str(row.get("REPORTDATE") or "")[:10]!=fiscal:
            raise ValueError("FROZEN_FISCAL_YEAR_VENDOR_MISMATCH")
        notice=str(row.get("NOTICE_DATE") or "")[:10]
        if not f"{issue_year}-01-01"<=notice<f"{issue_year+1}-01-01":
            raise ValueError("VENDOR_ISSUER_REPORT_NOTICE_DATE_OUTSIDE_YEAR")
        grouped[sid].append(row)
    receipts=[]
    for sid in selected:
        hits=grouped[sid]
        status=("NO_MATCHING_VENDOR_YEAR_ROW" if not hits else
                "MULTIPLE_VENDOR_VINTAGES_UNRESOLVED" if len(hits)>1 else
                "SINGLE_2026_RETROSPECTIVE_VENDOR_RECORD")
        row=hits[0] if len(hits)==1 else {}
        receipts.append({
            "security_id":sid,
            "coverage_status":status,
            "matched_vendor_rows":len(hits),
            "notice_days":sorted({str(x["NOTICE_DATE"])[:10] for x in hits}),
            "update_days":sorted({str(x.get("UPDATE_DATE") or "")[:10] for x in hits}),
            "source_record_sha256":[sha(json.dumps(x,ensure_ascii=False,sort_keys=True,
                                                   separators=(",",":")).encode()) for x in hits],
            "retrospective_financial_field_values":{
                field:row.get(raw_name) for field,raw_name in DATA_FIELDS.items()},
            "exact_original_2023_or_2024_pdf_line_items_crosschecked":False,
            "financial_record_2023_or_2024_vintage_certified":False,
            "financial_data_used_as_predictor":False,
            "live_buy_eligibility":"NOT_AUTHORIZED",
        })
    return receipts

def collect(out,fetch=fetch_page):
    if out.exists():
        raise ValueError("NO_OVERWRITE_OF_2026_RETROSPECTIVE_SOURCE_CAPTURE")
    frames,frame_sha=load_frozen_frames()
    cohorts=[]
    raw_files={}
    for frame in frames["cohorts"]:
        issued=frame["expected_issuer_publication_year"]
        fiscal=frame["report_period_end"]
        cutoff=f"{issued+1}-01-01"
        data,pages,page_receipts=acquire_year(fiscal,cutoff,fetch)
        matches=match_frame(frame,data)
        for index,blob in enumerate(pages,1):
            raw_files[f"{frame['cohort_id']}/page-{index:03d}.json"]=blob
        cohort={
            "cohort_id":frame["cohort_id"],
            "report_period_end":fiscal,
            "publication_year":issued,
            "vendor_cutoff_notice_exclusive":cutoff,
            "frozen_128_selected_id_sha256":frame["selected_ids_sha256"],
            "vendor_full_year_source_rows":len(data),
            "vendor_pages":page_receipts,
            "sample_count":len(matches),
            "vendor_single_record_matched_count":
                sum(x["matched_vendor_rows"]==1 for x in matches),
            "vendor_missing_count":sum(x["matched_vendor_rows"]==0 for x in matches),
            "vendor_multiple_count":sum(x["matched_vendor_rows"]>1 for x in matches),
            "vendor_updated_after_original_publication_year_count":sum(
                bool(x["update_days"]) and x["update_days"][-1]>=cutoff
                for x in matches),
            "rows":matches,
        }
        cohorts.append(cohort)
        print(f"FISCAL {fiscal} TOTAL_VENDOR={len(data)} "
              f"FROZEN_MATCHES={cohort['vendor_single_record_matched_count']}/128 "
              f"LATE_UPDATED={cohort['vendor_updated_after_original_publication_year_count']}",
              flush=True)
    out.mkdir(parents=True)
    with zipfile.ZipFile(out/"RAW_EASTMONEY_2022_2023_FINANCIAL_PAGES.zip",
                         "w",zipfile.ZIP_DEFLATED,compresslevel=8) as archive:
        for name,blob in sorted(raw_files.items()):
            archive.writestr(name,blob)
    result={
        "schema":SCHEMA,
        "captured_at_utc":datetime.now(timezone.utc).isoformat(),
        "prequery_historical_frame_sha256":frame_sha,
        "source":"EASTMONEY_RETROSPECTIVE_FINANCIAL_SUMMARY_NOT_OFFICIAL",
        "raw_financial_page_zip_sha256":
            sha((out/"RAW_EASTMONEY_2022_2023_FINANCIAL_PAGES.zip").read_bytes()),
        "total_sampled_issuer_year_cases":sum(len(x["rows"]) for x in cohorts),
        "both_issuer_years_outcome_data_not_read":True,
        "2023_2024_filing_document_numbers_NOT_certified":True,
        "point_in_time_financial_values_certified":False,
        "research_2026_vintage_not_genuine_2023_2024_vintage":True,
        "independent_oos_validated":False,
        "live_buy_eligibility":"NOT_AUTHORIZED",
        "cohorts":cohorts,
    }
    (out/"FINANCIAL_256_VENDOR_COVERAGE.json").write_text(
        json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"cohorts":[{k:v for k,v in c.items()
                                  if k not in ("rows","vendor_pages")}
                                 for c in cohorts],
                     "live_buy_eligibility":"NOT_AUTHORIZED"},ensure_ascii=False))
    return result

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--out",required=True,type=Path)
    a=p.parse_args()
    collect(a.out)

if __name__=="__main__":
    main()
