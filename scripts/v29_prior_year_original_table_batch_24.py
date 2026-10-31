#!/usr/bin/env python3
"""24 fixed source-only FY2022/FY2023 original-year issuer table checks.

First 12 frozen issuers from each of 2023/2024 cohorts, selected BEFORE this
new PDF retrieval and regardless of vendor coverage or later security returns.
Preserve all 24 names, including missing official PDFs and missing vendor
financial rows. Raw source PDFs are stored as short-lived Actions artifacts,
not in git; SHA+URL+actual parsed cell/column evidence are committed.
No vendor numbers are allowed to determine which PDF table cell is extracted.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime,timezone
from decimal import Decimal,ROUND_HALF_UP
from pathlib import Path

from v29_2023_2024_original_filing_discovery_256 import load_frozen_frames
from v29_original_filing_pdf_proof import fetch_binary
from v29_original_year_table_parser import parse_original_table,FIELDS
from v29_original_table_reporting_precision import reconcile_field

ROOT=Path(__file__).resolve().parents[1]
OFFICIAL=ROOT/"evidence/v29_original_2023_2024_reports_256/HISTORICAL_256_OFFICIAL_DISCOVERY.json"
VENDOR=ROOT/"research/v29_prior_financial_source_256/FINANCIAL_256_VENDOR_COVERAGE.json"
PILOT_N=12
SCHEMA="V29_PRIOR_2023_2024_FIXED_24_PDF_CURRENT_YEAR_FIELD_AUDIT_V1"
FIELDS_MONEY=("revenue_yuan","parent_net_profit_yuan")
PERCENT=Decimal("0.01")

def sha(raw):
    return hashlib.sha256(raw).hexdigest()

def load_pilot():
    frozen,frame_hash=load_frozen_frames()
    original=json.loads(OFFICIAL.read_bytes())
    vendor=json.loads(VENDOR.read_bytes())
    if (original.get("schema")!="V29_2023_2024_2X128_ORIGINAL_ANNUAL_REPORT_DISCOVERY_V1"
            or vendor.get("schema")!="V29_FY2022_FY2023_2X128_RETROSPECTIVE_VENDOR_FINANCIAL_SOURCE_V1"
            or original["sealed_prequery_cohorts_manifest_sha256"]!=frame_hash
            or vendor["prequery_historical_frame_sha256"]!=frame_hash):
        raise ValueError("HISTORICAL_256_FIXED_SOURCE_IDENTITIES_CHANGED")
    targets=[]
    for fr,ann,fin in zip(frozen["cohorts"],original["cohorts"],vendor["cohorts"]):
        if (fr["cohort_id"]!=ann["cohort_id"] or fr["cohort_id"]!=fin["cohort_id"] or
            len(fr["selected_ids"])!=128 or len(ann["rows"])!=128 or len(fin["rows"])!=128):
            raise ValueError("INCORRECT_SOURCE_IDENTITY_OR_COHORT_SIZE")
        a={r["security_id"]:r for r in ann["rows"]}
        v={r["security_id"]:r for r in fin["rows"]}
        for security_id in fr["selected_ids"][:PILOT_N]:
            if security_id not in a or security_id not in v:
                raise ValueError("FROZEN_ISSUER_MISSING_FROM_COMMITTED_SOURCE")
            targets.append({
                "security_id":security_id,
                "cohort_id":fr["cohort_id"],
                "fiscal_year":int(fr["report_period_end"][:4]),
                "expected_issued_year":fr["expected_issuer_publication_year"],
                "original_metadata":a[security_id],
                "retrospective_vendor":v[security_id],
            })
    if len(targets)!=2*PILOT_N or len({(x["cohort_id"],x["security_id"]) for x in targets})!=24:
        raise ValueError("SOURCE_ONLY_FIXED_24_SELECTION_CHANGED")
    return targets,{
        "frozen_original_cohorts_sha256":frame_hash,
        "official_2023_2024_metadata_sha256":sha(OFFICIAL.read_bytes()),
        "2026_retrospective_financial_source_sha256":sha(VENDOR.read_bytes()),
    }

def verify_pdf_identity(doc,raw,security_id,year):
    if (len(doc)<30 or not raw.startswith(b"%PDF-") or
            b"%%EOF" not in raw[-8192:]):
        raise ValueError("NOT_A_COMPLETE_FULL_ANNUAL_PDF")
    start="".join(doc[i].get_text("text") or "" for i in range(min(len(doc),8)))
    clean="".join(start.split())
    issuer_code=security_id.split(":")[1]
    if (str(year) not in clean or "年度报告" not in clean or
            "年度报告摘要" in clean or issuer_code not in clean):
        raise ValueError("ISSUER_SECURITY_CODE_FISCAL_YEAR_OR_FULL_REPORT_NOT_IDENTIFIED")

def compare_original_field(extracted,record,field):
    orig=extracted["fields"][field]
    vendor_value=record["retrospective_financial_field_values"].get(field)
    status=orig["status"]
    answer={
        "financial_field":field,
        "original_current_year_table_source_status":status,
        "original_current_year_table_value":orig["extracted_value"],
        "original_pdf_table_evidence":orig["evidence"],
        "original_pdf_table_candidate_count":orig["candidate_count"],
        "vendor_2026_source_value":str(vendor_value) if vendor_value is not None else None,
        "vendor_update_days":record["update_days"],
        "original_release_time_binary_hash_certified":False,
        "2026_vendor_financial_record_not_a_historical_original_vintage":True,
    }
    if orig["status"]!="UNIQUE_FISCAL_YEAR_TABLE_CELL_EXTRACTED":
        answer["comparison_status"]="UNRESOLVED_OR_AMBIGUOUS_ORIGINAL_PDF_TABLE_FIELD"
    elif record["matched_vendor_rows"]!=1 or vendor_value is None:
        answer["comparison_status"]="ORIGINAL_PDF_VALUE_FOUND_NO_UNIQUE_RETROSPECTIVE_VENDOR"
    else:
        revised=reconcile_field(answer)
        answer["original_reporting_quantum"]=revised["original_reporting_quantum"]
        answer["vendor_to_original_printed_precision"]=revised[
            "later_vendor_rounded_to_original_source_reporting_precision"]
        answer["vendor_minus_source_value"]=revised[
            "later_vendor_minus_source_unrounded"]
        answer["comparison_status"]=revised["status"]
    return answer

def one(target,fetch,raw_out=None):
    sid=target["security_id"]
    fiscal=target["fiscal_year"]
    announced=target["original_metadata"]
    vendor=target["retrospective_vendor"]
    chosen=announced.get("chosen")
    receipt={
        "security_id":sid,
        "fiscal_year":fiscal,
        "issued_year":target["expected_issued_year"],
        "source_discovery_status":announced["status"],
        "official_announcement_day":chosen["notice_day"] if chosen else None,
        "official_original_pdf_url":chosen["original_pdf_url"] if chosen else None,
        "retrospective_vendor_row_count":vendor["matched_vendor_rows"],
        "vendor_notice_days":vendor["notice_days"],
        "vendor_update_days":vendor["update_days"],
        "original_PDF_release_time_sha256_certified":False,
        "pdf_original_current_year_field_source":False,
        "live_buy_eligibility":"NOT_AUTHORIZED",
    }
    if not chosen:
        receipt["status"]="NO_UNIQUE_ORIGINAL_2023_OR_2024_PDF_SOURCE"
        return receipt
    if not chosen["original_pdf_url"].startswith(
            f"https://static.cninfo.com.cn/finalpage/{chosen['notice_day']}/"):
        raise ValueError("OFFICIAL_SOURCE_DATE_URL_INCONSISTENT")
    try:
        import pymupdf
        blob=fetch(chosen["original_pdf_url"])
        doc=pymupdf.open(stream=blob,filetype="pdf")
        verify_pdf_identity(doc,blob,sid,fiscal)
        field_data=parse_original_table(doc,fiscal)
        receipt["pdf_original_current_year_field_source"]=True
        receipt["status"]="ORIGINAL_FULL_REPORT_IDENTITY_VERIFIED_TABLE_SCAN_COMPLETE"
        receipt["pdf_sha256_2026_retrieval"]=sha(blob)
        receipt["pdf_size_bytes"]=len(blob)
        receipt["pdf_total_pages"]=len(doc)
        receipt["original_table_status"]=field_data["status"]
        receipt["field_sources"]={
            f:compare_original_field(field_data,vendor,f) for f in FIELDS}
        receipt["original_table_all_four_fields_unambiguous"]=all(
            r["original_current_year_table_source_status"]==
            "UNIQUE_FISCAL_YEAR_TABLE_CELL_EXTRACTED"
            for r in receipt["field_sources"].values())
        if raw_out is not None:
            raw_out.mkdir(parents=True,exist_ok=True)
            (raw_out/f"{sid.replace(':','-')}-FY{fiscal}.pdf").write_bytes(blob)
        doc.close()
    except Exception as exc:
        receipt["status"]="ORIGINAL_PDF_FETCH_IDENTITY_OR_TABLE_PARSING_FAILED"
        receipt["source_error"]=type(exc).__name__+":"+str(exc)[:160]
    return receipt

def collect(out,raw_out=None,fetch=fetch_binary):
    if out.exists():
        raise ValueError("NO_OVERWRITE_OF_FROZEN_24_REAL_PDF_AUDIT")
    targets,manifest_hashes=load_pilot()
    rows=[]
    for i,source in enumerate(targets,1):
        result=one(source,fetch,raw_out=raw_out)
        rows.append(result)
        print(f"ORIGINAL_TABLE {i:02d}/24 {source['security_id']} "
              f"{result['status']} "
              f"FOUR_FIELDS={result.get('original_table_all_four_fields_unambiguous',False)}",
              flush=True)
    fields=[x for r in rows for x in r.get("field_sources",{}).values()]
    out.mkdir(parents=True)
    receipt={
        "schema":SCHEMA,
        "captured_at_utc":datetime.now(timezone.utc).isoformat(),
        "frozen_source_manifests":manifest_hashes,
        "source_population_issuer_year_count":256,
        "fixed_first_twelve_per_cohort_selected_before_pdf_queries":True,
        "frozen_audit_sample_count":24,
        "attempted_count":len(rows),
        "original_pdf_full_identity_verified_count":sum(
            r["pdf_original_current_year_field_source"] for r in rows),
        "original_pdf_all_four_current_year_fields_unambiguous_count":sum(
            r.get("original_table_all_four_fields_unambiguous") is True for r in rows),
        "current_year_table_field_extracted_count":sum(
            f["original_current_year_table_source_status"]==
            "UNIQUE_FISCAL_YEAR_TABLE_CELL_EXTRACTED" for f in fields),
        "table_field_agrees_with_retrospective_vendor_count":sum(
            f["comparison_status"]=="SAME_NUMERIC_VALUE_AS_ORIGINAL_PUBLISHED_CELL"
            for f in fields),
        "table_field_disagrees_with_retrospective_vendor_count":sum(
            f["comparison_status"]==
            "DIFFERENCE_BEYOND_PUBLISHED_PRECISION_REQUIRES_SOURCE_REVIEW" for f in fields),
        "source_pdf_bytes_in_this_git_commit":False,
        "source_pdf_raw_bytes_stored_as_bounded_actions_artifact":bool(raw_out),
        "this_2026_retrospective_archive_proves_original_report_release_time_hash":False,
        "this_24_issuer_pilot_is_not_unseen_chronological_out_of_sample":True,
        "no_historical_or_future_price_outcomes_queried":True,
        "strategy_validated":False,
        "live_buy_eligibility":"NOT_AUTHORIZED",
        "rows":rows,
    }
    (out/"FIXED_24_ORIGINAL_YEAR_TABLE_FIELDS.json").write_text(
        json.dumps(receipt,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return receipt

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--out",type=Path,required=True)
    p.add_argument("--raw-out",type=Path)
    args=p.parse_args()
    r=collect(args.out,args.raw_out)
    print(json.dumps({k:v for k,v in r.items() if k!="rows"},
                     ensure_ascii=False),flush=True)

if __name__=="__main__":
    main()
