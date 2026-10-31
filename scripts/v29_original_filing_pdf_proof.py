#!/usr/bin/env python3
"""Capture two ORIGINAL 2025-issued FY2024 PDFs from the frozen 128-issuer frame.

Binary preservation proves the exact 2026-retrieved document bytes. It cannot
prove 2025-era vendor versions, release-time hashes, OOS alpha, or BUY eligibility.
No frozen E-layer / fold data, outcome prices or cost thresholds are accessed.
"""
from __future__ import annotations
import argparse
import hashlib
import io
import json
import re
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from urllib.request import Request, urlopen

from v29_historical_universe_sampling import build_frame

ROOT=Path(__file__).resolve().parents[1]
COVERAGE=ROOT/"research/V2.9_2025_128_FILING_SOURCE_COVERAGE.json"
PDF_LIMIT_BYTES=28_000_000
TARGETS=(
    {
      "security_id":"SSE:601009", "name":"南京银行",
      "publication_day":"2025-04-22",
      "url":"https://static.cninfo.com.cn/finalpage/2025-04-22/1223197865.PDF",
      "numbers_in_pdf_units":{"revenue":"50273070","parent_profit":"20176728"},
      "pdf_unit_multiplier_yuan":"1000",
    },
    {
      "security_id":"SZSE:002493", "name":"荣盛石化",
      "publication_day":"2025-04-25",
      "url":"https://static.cninfo.com.cn/finalpage/2025-04-25/1223285131.PDF",
      "numbers_in_pdf_units":{"revenue":"326475162608.88","parent_profit":"724484686.45"},
      "pdf_unit_multiplier_yuan":"1",
    },
)

def sha(b):
    return hashlib.sha256(b).hexdigest()

def validate_targets(targets, frame, coverage):
    if coverage["schema"]!="V29_2025_128_ISSUER_RETROSPECTIVE_FINANCIAL_SOURCE_COVERAGE_V1":
        raise ValueError("WRONG_COVERAGE_SCHEMA")
    if (len(frame["selected_ids"])!=128 or
        coverage["full_selected_issuer_ids_sha256"]!=frame["selected_ids_sha256"]):
        raise ValueError("FROZEN_128_SAMPLE_MISMATCH")
    indexed={x["security_id"]:x for x in coverage["rows"]}
    checked=[]
    for target in targets:
        sid=target["security_id"]
        if sid not in frame["selected_ids"] or sid not in indexed:
            raise ValueError("NOT_A_FIXED_SAMPLE_ID")
        row=indexed[sid]
        if (target["publication_day"] not in row["vendor_announcement_dates"] or
            row["matched_vendor_rows"]!=1):
            raise ValueError("PUBLICATION_DAY_OR_VENDOR_IDENTITY_CONFLICT")
        if not target["url"].startswith(
            "https://static.cninfo.com.cn/finalpage/"+target["publication_day"]+"/"):
            raise ValueError("UNEXPECTED_ORIGINAL_DOCUMENT_URL")
        if not re.fullmatch(r"\d+\.PDF",target["url"].rsplit("/",1)[-1]):
            raise ValueError("INVALID_ORIGINAL_DOCUMENT_SUFFIX")
        unit=Decimal(target["pdf_unit_multiplier_yuan"])
        expected=target["numbers_in_pdf_units"]
        if Decimal(expected["revenue"])*unit!=Decimal(str(row["vendor_revenue_yuan"])):
            raise ValueError("REVENUE_EXPECTATION_NOT_FROM_FROZEN_COVERAGE")
        if Decimal(expected["parent_profit"])*unit!=Decimal(str(row["vendor_parent_profit_yuan"])):
            raise ValueError("PROFIT_EXPECTATION_NOT_FROM_FROZEN_COVERAGE")
        checked.append((target,row))
    return checked

def fetch_binary(url, opener=urlopen):
    req=Request(url,headers={
        "User-Agent":"Mozilla/5.0",
        "Accept":"application/pdf",
        "Referer":"https://www.cninfo.com.cn/",
    })
    chunks=[]
    total=0
    with opener(req,timeout=25) as response:
        while True:
            block=response.read(65536)
            if not block:
                break
            total+=len(block)
            if total>PDF_LIMIT_BYTES:
                raise ValueError("ORIGINAL_PDF_EXCEEDS_BOUNDED_REPOSITORY_LIMIT")
            chunks.append(block)
    data=b"".join(chunks)
    if not data.startswith(b"%PDF-") or b"%%EOF" not in data[-8192:]:
        raise ValueError("INVALID_OR_INCOMPLETE_PDF_BYTES")
    return data

def verify_pdf(data, target):
    # pypdf is imported here to keep the source identity tests pure and fast.
    from pypdf import PdfReader
    reader=PdfReader(io.BytesIO(data), strict=True)
    page_count=len(reader.pages)
    if page_count<30:
        raise ValueError("PDF_NOT_FULL_ANNUAL_REPORT_PAGE_COUNT")
    front="\n".join(page.extract_text() or "" for page in reader.pages[:min(6,page_count)])
    flattened=re.sub(r"\s+","",front)
    if target["name"] not in flattened or "2024" not in flattened or "年度报告" not in flattened:
        raise ValueError("PDF_ISSUER_NAME_YEAR_OR_FULL_REPORT_IDENTITY_FAILED")
    # Presence of the exact numeric tokens is a machine check, NOT a semantic
    # extraction of which financial statement row they belong to.
    excerpts=[]
    for i in range(min(42,page_count)):
        page=reader.pages[i].extract_text() or ""
        excerpts.append((i+1,re.sub(r"[\s,，]","",page)))
    numeric={}
    for label,value in target["numbers_in_pdf_units"].items():
        token=value.replace(",","")
        numeric[label]=[n for n,t in excerpts if token in t]
    return {
        "pdf_structurally_parsed":True,
        "page_count":page_count,
        "identity_first_pages_verified":True,
        "expected_financial_amount_text_pages_first_42":numeric,
        "expected_amounts_text_present":all(bool(pages) for pages in numeric.values()),
        "semantic_field_to_table_cell_automatically_certified":False,
    }

def collect(out, targets=TARGETS, opener=urlopen):
    if out.exists():
        raise ValueError("NO_OVERWRITE_OF_ORIGINAL_BINARY_EVIDENCE")
    frame=build_frame()
    coverage=json.loads(COVERAGE.read_text(encoding="utf-8"))
    pairs=validate_targets(targets,frame,coverage)
    out.mkdir(parents=True)
    receipts=[]
    for target,row in pairs:
        sid=target["security_id"]
        rec={
            "security_id":sid,"source_publication_day":target["publication_day"],
            "source_url":target["url"],"report_year":2024,
            "retrospective_vendor_2026_update_days":row["vendor_update_dates"],
            "pdf_unit_multiplier_yuan":target["pdf_unit_multiplier_yuan"],
            "expected_field_values_pdf_units":target["numbers_in_pdf_units"],
            "original_report_released_time_pdf_sha_unknown":True,
            "current_pdf_retrieved_at_utc":datetime.now(timezone.utc).isoformat(),
            "source_at_2025_asof_certified":False,
            "live_buy_eligibility":"NOT_AUTHORIZED",
        }
        try:
            data=fetch_binary(target["url"],opener=opener)
            checked=verify_pdf(data,target)
            filename=sid.replace(":","-")+"-FY2024-ISSUED2025.pdf"
            (out/filename).write_bytes(data)
            rec.update(checked)
            rec.update({"status":"FULL_ORIGINAL_PDF_BYTES_SEALED_2026_VINTAGE",
                        "saved_pdf_path":filename,
                        "sha256_pdf":sha(data),
                        "bytes_pdf":len(data)})
        except (OSError,ValueError,RuntimeError) as ex:
            # Capture the failure while preserving other fixed sample members.
            # A failed PDF is NEVER represented as a verified financial record.
            rec.update({"status":"PDF_ACQUISITION_OR_VERIFICATION_FAILED",
                        "error_type":type(ex).__name__,
                        "error_message":str(ex)[:200],
                        "sha256_pdf":None,
                        "saved_pdf_path":None})
        receipts.append(rec)
        print(json.dumps({"sid":sid,"status":rec["status"],"pages":rec.get("page_count"),
                          "sha256":rec["sha256_pdf"]},ensure_ascii=False),flush=True)
    result={
        "schema":"V29_ORIGINAL_2025_FY2024_REPORT_BINARY_SEAL_PILOT_V1",
        "capture_time_utc":datetime.now(timezone.utc).isoformat(),
        "fixed_sample_sha256":frame["selected_ids_sha256"],
        "sample_count":128,
        "attempted_original_reports":len(receipts),
        "original_full_pdf_verified":sum(r["sha256_pdf"] is not None for r in receipts),
        "field_numeric_text_present":sum(r.get("expected_amounts_text_present") is True for r in receipts),
        "unverified_or_failed_count":sum(r["sha256_pdf"] is None for r in receipts),
        "historical_vendor_rows_retrospectively_updated_not_pit_certified":True,
        "full_128_original_report_complete":False,
        "no_prices_or_outcomes_read":True,
        "oos_validated":False,
        "live_buy_eligibility":"NOT_AUTHORIZED",
        "receipts":receipts,
    }
    (out/"BINARY_SOURCE_MANIFEST.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return result

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--out",type=Path,required=True)
    args=ap.parse_args()
    result=collect(args.out)
    if result["original_full_pdf_verified"]==0:
        raise SystemExit("NO_VERIFIED_ORIGINAL_PDF_BYTES")

if __name__=="__main__":
    main()
