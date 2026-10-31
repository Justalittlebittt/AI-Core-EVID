#!/usr/bin/env python3
"""Four original FY2022/FY2023 annual reports: source-table vs 2026 vendor values.

Four PDFs and their current SHA256 were already sealed in git. The field page,
year header and first current-year column below were read from rendered PDF
tables, not inferred by searching numeric tokens or selecting by outcome.
The code rechecks actual original binary, source name/year/notice identity,
correct field label and amount on that page; reporting precision is explicit.
A 2026 retrieval is not 2023/2024 source-byte time-machine proof. Research only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime,timezone
from decimal import Decimal,ROUND_HALF_UP
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
BINARY=ROOT/"evidence/v29_original_2023_2024_four_pdf_financial"
METADATA=BINARY/"ORIGINAL_FOUR_YEAR_FIELD_CONTEXT_RECEIPT.json"
VENDOR=ROOT/"research/v29_prior_financial_source_256/FINANCIAL_256_VENDOR_COVERAGE.json"
COHORT=ROOT/"research/V2.9_2023_2024_ORIGINAL_FILING_SOURCE_FRAMES_128.json"
SCHEMA="V29_PRIOR_FOUR_ORIGINAL_ISSUER_FINANCIAL_TABLE_CROSS_VINTAGE_V1"
PERCENT=Decimal("0.01")

# Only the four first-in-frozen-cohort issuers were visually table-checked.
# Amounts are CNY in the current fiscal year's column, as printed in each
# originally issued FY2022/FY2023 report. No vendor values set these numbers.
TABLE={
    "SSE:688416":{
        "fiscal_year":2022,
        "revenue_yuan":("433277479.71",11),
        "parent_net_profit_yuan":("21205562.13",11),
        "revenue_growth_yoy_pct":("-24.76",11),
        "weighted_roe_pct":("2.42",12),
    },
    "SSE:600088":{
        "fiscal_year":2022,
        "revenue_yuan":("1149492197.34",5),
        "parent_net_profit_yuan":("-65289963.12",5),
        "revenue_growth_yoy_pct":("-3.25",5),
        "weighted_roe_pct":("-6.32",6),
    },
    "SSE:688031":{
        "fiscal_year":2023,
        "revenue_yuan":("490805231.02",21),
        "parent_net_profit_yuan":("-288243033.17",21),
        "revenue_growth_yoy_pct":("31.72",21),
        "weighted_roe_pct":("-18.30",21),
    },
    "SZSE:000070":{
        "fiscal_year":2023,
        "revenue_yuan":("4937289689.32",8),
        "parent_net_profit_yuan":("-272482091.07",7),
        "revenue_growth_yoy_pct":("17.79",7),
        "weighted_roe_pct":("-14.27",8),
    },
}
LABELS={
    "revenue_yuan":("营业收入",),
    "parent_net_profit_yuan":("归属于上市公司股东的净利润","归属于母公司股东的净利润"),
    "revenue_growth_yoy_pct":("营业收入","本年比上年增减"),
    "weighted_roe_pct":("加权平均净资产收益率",),
}

def sha(data):
    return hashlib.sha256(data).hexdigest()

def norm(s):
    return re.sub(r"[\s,，]","",str(s)).replace("−","-").replace("－","-")

def read_sources():
    m=json.loads(METADATA.read_bytes())
    v=json.loads(VENDOR.read_bytes())
    f=json.loads(COHORT.read_bytes())
    if (m.get("archived_full_original_pdf_count")!=4 or
        m.get("frozen_target_count")!=4 or
        v.get("total_sampled_issuer_year_cases")!=256 or
        len(f.get("cohorts",[]))!=2):
        raise ValueError("EXPECTED_FROZEN_REPORTS_AND_256_VENDOR_SOURCE_MISSING")
    rows=m["rows"]
    if len(rows)!=4 or set(x["security_id"] for x in rows)!=set(TABLE):
        raise ValueError("FOUR_ORIGINAL_ISSUER_IDENTITIES_CHANGED")
    return m,v,f

def exact_value_on_original_page(page_text,value):
    # Require the actual REPORT number printed with full decimal precision.
    # This check does not alone certify the cell/year association; that
    # association was separately reviewed on the rendered current-year table.
    t=norm(page_text)
    amt=norm(format(Decimal(value),",.2f"))
    return bool(re.search(r"(?<![0-9.])"+re.escape(amt)+r"(?![0-9.])",t))

def evaluate(m,v,frames,reader=None):
    if reader is None:
        import pymupdf
        reader=lambda p:pymupdf.open(p)
    financial={(x["security_id"],c["publication_year"]):x
        for c in v["cohorts"] for x in c["rows"]}
    expected_ids={
        c["expected_issuer_publication_year"]:c["selected_ids"][:2]
        for c in frames["cohorts"]
    }
    details=[]
    for doc in m["rows"]:
        sid=doc["security_id"]
        year=TABLE[sid]["fiscal_year"]
        issued=year+1
        if (doc["fiscal_year"]!=year or doc["issue_year"]!=issued or
            sid not in expected_ids[issued] or
            doc["status"]!="FULL_ISSUER_PDF_BYTES_ARCHIVED_FIELD_ROW_EVIDENCE_ONLY" or
            not doc.get("original_full_issuer_report_identity_verified") or
            doc.get("original_release_time_binary_hash_known") is not False):
            raise ValueError("WRONG_ORIGINAL_RELEASE_YEAR_OR_UNSEALED_SOURCE_IDENTITY")
        key=(sid,issued)
        record=financial[key]
        if record["matched_vendor_rows"]!=1 or record["notice_days"]!=[doc["source_notice"]]:
            raise ValueError("OFFICIAL_REPORT_AND_VENDOR_NOTICE_DATE_MISMATCH")
        source=BINARY/doc["stored_pdf_file"]
        blob=source.read_bytes()
        if sha(blob)!=doc["2026_capture_pdf_sha256"] or len(blob)!=doc["binary_size"]:
            raise ValueError("ORIGINAL_PDF_BYTES_OR_SHA_CHANGED")
        parsed=reader(source)
        if len(parsed)!=doc["pages"]:
            raise ValueError("ORIGINAL_PDF_PAGE_COUNT_CHANGED")
        for field in ("revenue_yuan","parent_net_profit_yuan",
                      "revenue_growth_yoy_pct","weighted_roe_pct"):
            value,pageno=TABLE[sid][field]
            page=parsed[pageno-1].get_text("text",sort=True)
            if str(year) not in norm(page):
                raise ValueError("PDF_TABLE_PAGE_MISSING_CURRENT_FISCAL_YEAR_HEADER")
            if not any(norm(label) in norm(page) for label in LABELS[field]):
                raise ValueError("PDF_TABLE_FIELD_LABEL_MISSING")
            if not exact_value_on_original_page(page,value):
                raise ValueError("PDF_CURRENT_YEAR_FIELD_AMOUNT_NOT_PRESENT_ON_REVIEWED_PAGE")
            vendor_val=record["retrospective_financial_field_values"].get(field)
            if vendor_val is None:
                raise ValueError("FIXED_VENDOR_FIELD_NOT_AVAILABLE")
            published=Decimal(value)
            retrospective=Decimal(str(vendor_val))
            # Monetary values exact to cents. Growth and ROE are reported to
            # 2 decimal percentage points in original printed current-year tables.
            comparable=(retrospective.quantize(PERCENT,rounding=ROUND_HALF_UP)
                        if field.endswith("_pct") else retrospective)
            delta=comparable-published
            match=delta==0
            details.append({
                "security_id":sid,
                "fiscal_year":year,
                "original_issuer_report_announced":doc["source_notice"],
                "source_pdf_url":doc["source_url"],
                "source_pdf_sha256_2026_capture":doc["2026_capture_pdf_sha256"],
                "original_pdf_page_1based":pageno,
                "source_year_column":str(year),
                "original_annual_report_current_year_table_value":str(published),
                "retrospective_2026_vendor_financial_value":str(retrospective),
                "vendor_value_to_original_printed_precision":str(comparable),
                "vendor_update_days":record["update_days"],
                "financial_field":field,
                "unit":"CNY" if field.endswith("_yuan") else "percentage_points",
                "vendor_minus_original_at_reported_precision":str(delta),
                "same_as_original_table_printed":match,
                "classification":(
                    "SAME_TO_ORIGINAL_TABLE_PRINTED_PRECISION" if match else
                    "HISTORICAL_ORIGINAL_VS_RETROSPECTIVE_VENDOR_VERSION_DIFFERENCE"),
                "source_page_field_label_and_amount_present":True,
                "assistant_rendered_table_current_year_cell_reviewed":True,
                "independent_external_field_audit":False,
                "release_time_pdf_byte_hash_known":False,
                "original_release_time_financial_version_proven_by_contemporaneous_archive":False,
                "live_buy_eligibility":"NOT_AUTHORIZED",
            })
    # The document records EXACTLY one observed new version mismatch family.
    mismatch=[d for d in details if not d["same_as_original_table_printed"]]
    allowed={("SSE:600088","parent_net_profit_yuan"),
             ("SSE:600088","weighted_roe_pct")}
    if len(details)!=16 or {(x["security_id"],x["financial_field"]) for x in mismatch}!=allowed:
        raise ValueError("EXPECTED_16_FIELD_SOURCE_AND_2_KNOWN_VINTAGE_MISMATCH_PATTERN_CHANGED")
    return details

def collect():
    m,v,f=read_sources()
    records=evaluate(m,v,f)
    mismatch=[r for r in records if not r["same_as_original_table_printed"]]
    return {
        "schema":SCHEMA,
        "compiled_at_utc":datetime.now(timezone.utc).isoformat(),
        "original_PDF_binary_manifest_sha256":sha(METADATA.read_bytes()),
        "retrospective_financial_vendor_manifest_sha256":sha(VENDOR.read_bytes()),
        "historical_frozen_256_cohort_manifest_sha256":sha(COHORT.read_bytes()),
        "original_2023_and_2024_annual_PDFs_reviewed":4,
        "original_fiscal_years":[2022,2023],
        "current_year_field_cells_visually_mapped_in_annual_report_tables":16,
        "matching_to_vendor_at_original_report_precision":len(records)-len(mismatch),
        "nonmatching_to_vendor_at_original_report_precision":len(mismatch),
        "difference_is_known_cross_vintage_restatement_not_random_source_error":True,
        "source_of_2022_600088_subsequent_comparative_restatement":
            "https://www.ctv-media.com.cn/upload/202404/22/202404221439284692.pdf",
        "source_of_restatement_explanation":
            "2023 FY report explicitly presents 2022 adjusted and pre-adjusted columns; company applies PRC Accounting Standards Interpretation No.16 (企业会计准则解释第16号).",
        "restatement_2022_600088_net_profit_CNY_from_original_to_later_adjusted":"380405.97",
        "historical_financial_value_release_time_SHA_certified":False,
        "all_other_252_frozen_issuer_years_not_field_certified":True,
        "chronologically_unseen_oos_validated":False,
        "factor_model_promoted":False,
        "live_buy_eligibility":"NOT_AUTHORIZED",
        "rows":records,
    }

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--out",required=True,type=Path)
    args=p.parse_args()
    if args.out.exists():
        raise ValueError("REFUSE_OVERWRITE_ORIGINAL_FILING_TABLE_VINTAGE_RECONCILIATION")
    result=collect()
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({
        "original_annual_reports":4,
        "field_cells":16,
        "same":result["matching_to_vendor_at_original_report_precision"],
        "revised":result["nonmatching_to_vendor_at_original_report_precision"],
        "asof_release_time_certified":False,
        "BUY":"NOT_AUTHORIZED",
    },ensure_ascii=False))

if __name__=="__main__":
    main()
