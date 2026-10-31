#!/usr/bin/env python3
"""Recalculate the ALREADY COMMITTED 24 original reports' source-precision audit.

Absolutely no re-fetch, PDF download, new security selection or price data.
Preserves the original 24-issuer evidence receipt byte-for-byte and its SHA;
this is a source-precision correction layered on that earlier archive.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path

from v29_original_table_reporting_precision import reconcile_field

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/"research/v29_original_table_24_20261031/FIXED_24_ORIGINAL_YEAR_TABLE_FIELDS.json"
SCHEMA="V29_FY2022_FY2023_24_ORIGINAL_SOURCE_REPORTING_PRECISION_RECONCILIATION_V1"
FOUR=("revenue_yuan","parent_net_profit_yuan",
      "revenue_growth_yoy_pct","weighted_roe_pct")

def sha(raw):
    return hashlib.sha256(raw).hexdigest()

def audit(evidence):
    if (evidence.get("schema")!="V29_PRIOR_2023_2024_FIXED_24_PDF_CURRENT_YEAR_FIELD_AUDIT_V1"
            or evidence.get("frozen_audit_sample_count")!=24
            or evidence.get("attempted_count")!=24
            or len(evidence.get("rows",[]))!=24
            or evidence.get("current_year_table_field_extracted_count")!=63
            or evidence.get("original_pdf_full_identity_verified_count")!=19
            or evidence.get("table_field_disagrees_with_retrospective_vendor_count")!=5
            or evidence.get("live_buy_eligibility")!="NOT_AUTHORIZED"):
        raise ValueError("FROZEN_24_PRIOR_EVIDENCE_NOT_THE_ORIGINAL_UNMODIFIED_SAMPLE")
    revisions=[]
    counts=Counter()
    for row in evidence["rows"]:
        fields=row.get("field_sources") or {}
        for field in FOUR:
            current=fields.get(field)
            if current is None:
                counts["NO_FULL_PDF_OR_UNIQUE_ORIGINAL_FIELD"]+=1
                continue
            if current["financial_field"]!=field:
                raise ValueError("FIELD_LABEL_IDENTITY_MISMATCH")
            r=reconcile_field(current)
            counts[r["status"]]+=1
            revisions.append({
                "security_id":row["security_id"],
                "fiscal_year":row["fiscal_year"],
                "2026_captured_original_pdf_sha256":row["pdf_sha256_2026_retrieval"],
                "original_pdf_source_url":row["official_original_pdf_url"],
                "original_notice_date":row["official_announcement_day"],
                "original_source_row_field":field,
                **r,
            })
    if sum(counts.values())!=96 or len(revisions)!=19*4:
        raise ValueError("ORIGINAL_24_FROZEN_FIELD_DENOMINATOR_CHANGED")
    incompatible=[x for x in revisions if
                  x["status"]=="DIFFERENCE_BEYOND_PUBLISHED_PRECISION_REQUIRES_SOURCE_REVIEW"]
    # Existing 2026 vendor values differ from original two fields in FY2022
    # 600088, and one source-year attributable profit in FY2022 001896.
    expected={
        ("SSE:600088","parent_net_profit_yuan"),
        ("SSE:600088","weighted_roe_pct"),
        ("SZSE:001896","parent_net_profit_yuan"),
    }
    if {(x["security_id"],x["original_source_row_field"]) for x in incompatible}!=expected:
        raise ValueError("AFTER_PRECISION_SOURCE_CONFLICT_SET_REQUIRES_REVIEW")
    rounded_corrections=[x for x in revisions if
        x["security_id"]=="SSE:688185" and
        x["original_source_row_field"] in ("revenue_yuan","parent_net_profit_yuan")]
    if (len(rounded_corrections)!=2 or not all(
        x["status"]=="COMPATIBLE_WITH_ORIGINAL_REPORTING_PRECISION_NOT_VERSION_PROOF"
        and x["original_reporting_quantum"]=="1000"
        for x in rounded_corrections)):
        raise ValueError("THOUSAND_YUAN_ROUNDING_FALSE_POSITIVES_NOT_REPAIRED")
    return {
        "schema":SCHEMA,
        "compiled_at_utc":datetime.now(timezone.utc).isoformat(),
        "fixed_issuer_year_denominator":24,
        "fixed_original_report_full_identity_count":19,
        "four_fields_per_issuer_expected_total":96,
        "fields_with_source_table_cell_and_vendor":63,
        "previous_unqualified_exact_currency_mismatch_count":5,
        "confirmed_after_source_unit_rounding_review":len(incompatible),
        "false_vintage_conflicts_removed_by_thousand_yuan_reporting_precision":2,
        "counts_by_source_precision_reconciliation":dict(sorted(counts.items())),
        "remaining_review_issuer_field_pairs":[{
            "security_id":x["security_id"],
            "fiscal_year":x["fiscal_year"],
            "financial_field":x["original_source_row_field"],
            "original_source_value":x["original_year_value"],
            "later_vendor_value":x["retrospective_2026_vendor_value"],
            "unrounded_difference":x["later_vendor_minus_source_unrounded"],
            "reporting_quantum":x["original_reporting_quantum"],
            "pdf_sha256":x["2026_captured_original_pdf_sha256"],
            "source_table_pages":sorted({y["source_pdf_page_1based"]
                for y in x["source_pdf_evidence"]}),
        } for x in incompatible],
        "raw_original_24_pdf_table_evidence_rows_immutable":True,
        "financial_version_difference_alone_does_not_prove_later_restatement_reason":True,
        "2026_pdf_retrieval_SHA_not_contemporaneous_2023_2024_release_time":True,
        "all_2026_vendor_historical_rows_asof_PIT_verified":False,
        "no_price_or_strategy_outcome_used":True,
        "independent_untouched_oos_validated":False,
        "live_buy_eligibility":"NOT_AUTHORIZED",
        "field_results":revisions,
    }

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--out",required=True,type=Path)
    args=parser.parse_args()
    if args.out.exists():
        raise ValueError("REFUSE_OVERWRITE_HISTORICAL_PDF_SOURCE_PRECISION_AUDIT")
    raw=SOURCE.read_bytes()
    d=audit(json.loads(raw))
    d["underlying_frozen_24_current_year_source_evidence_sha256"]=sha(raw)
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(d,ensure_ascii=False,indent=2)+"\n",
                        encoding="utf-8")
    print(json.dumps({
        "original_cases":24,
        "field_cells_with_vendor":63,
        "previous_naive_mismatches":5,
        "rounding_false_positives_removed":2,
        "beyond_reporting_precision_conflicts":3,
        "BUY":"NOT_AUTHORIZED",
    },ensure_ascii=False))

if __name__=="__main__":
    main()
