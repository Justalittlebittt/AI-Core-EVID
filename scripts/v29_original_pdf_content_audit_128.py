#!/usr/bin/env python3
"""Check actual content of original FY2024 annual PDFs for the 128 frozen sample.

Reads the official URL discovery and 2026-retrospective vendor financial summary.
Separately records PDF SHA, page count, issuer-title identity, and amount token
presence. None of these grants 2025-vintage certification or BUY authorization.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import io
import json
import re
from datetime import datetime,timezone
from decimal import Decimal,ROUND_HALF_UP
from pathlib import Path

from v29_historical_universe_sampling import build_frame,INTERVALS
from v29_original_filing_pdf_proof import fetch_binary

ROOT=Path(__file__).resolve().parents[1]
DISCOVERY=ROOT/"evidence/v29_original_fy2024_discovery_128/DISCOVERY_128.json"
COVERAGE=ROOT/"research/V2.9_2025_128_FILING_SOURCE_COVERAGE.json"
RESOLUTION=ROOT/"research/V2.9_2025_600021_ANNOUNCEMENT_PDF_DISAMBIGUATION.json"

def dig(raw):
    return hashlib.sha256(raw).hexdigest()

def _compact(s):
    return re.sub(r"[\s,，]","",str(s or ""))

def _numeric_text_tokens(value):
    if value is None:
        return {}
    number=Decimal(str(value))
    result={}
    for label,scale in (("yuan",1),("thousand_yuan",1000),("ten_thousand_yuan",10000)):
        v=number/Decimal(scale)
        variants=set()
        for candidate in (v,v.quantize(Decimal("0.01"),rounding=ROUND_HALF_UP)):
            s=format(candidate,"f")
            variants.add(s)
            if "." in s:
                variants.add(s.rstrip("0").rstrip("."))
        result[label]=sorted(variants)
    return result

def verify_document(data,expected_name,financials):
    from pypdf import PdfReader
    doc=PdfReader(io.BytesIO(data),strict=True)
    pages=len(doc.pages)
    cover="\n".join(doc.pages[i].extract_text() or "" for i in range(min(5,pages)))
    c=_compact(cover)
    has_year=("2024" in c)
    has_report=("年度报告" in c)
    summary=("年度报告摘要" in c or "年度报告（摘要）" in c)
    name=bool(expected_name and _compact(expected_name) in c)
    checked=(pages>=30 and has_year and has_report and name and not summary)
    outcome={
        "pdf_sha256":dig(data),"pdf_bytes":len(data),"pdf_page_count":pages,
        "expected_short_name":expected_name,
        "cover_has_year_2024":has_year,"cover_has_annual_title":has_report,
        "cover_has_expected_issuer_name":name,"cover_indicates_summary":summary,
        "full_report_identity_pass":checked,
        "field_semantic_table_row_certified":False,
    }
    # Numeric search only, not table-row binding or verification of which year
    # and units a text occurrence represents.
    if checked:
        texts=[_compact(doc.pages[i].extract_text() or "") for i in range(min(45,pages))]
        numerical={}
        for field,number in financials.items():
            candidate=_numeric_text_tokens(number)
            hits={}
            for unit,tokens in candidate.items():
                hit_pages=[i+1 for i,txt in enumerate(texts)
                           if any(t and t in txt for t in tokens)]
                if hit_pages: hits[unit]=hit_pages
            numerical[field]=hits
        outcome["amount_text_candidate_pages_first_45"]=numerical
        outcome["both_financial_amounts_have_text_matches"]=all(bool(x) for x in numerical.values())
    else:
        outcome["amount_text_candidate_pages_first_45"]={}
        outcome["both_financial_amounts_have_text_matches"]=False
    return outcome

def _sources():
    frame=build_frame()
    d=json.loads(DISCOVERY.read_text(encoding="utf-8"))
    c=json.loads(COVERAGE.read_text(encoding="utf-8"))
    fix=json.loads(RESOLUTION.read_text(encoding="utf-8"))
    if (len(d["rows"])!=128 or len(c["rows"])!=128 or
        d["frozen_sample_sha256"]!=frame["selected_ids_sha256"] or
        c["full_selected_issuer_ids_sha256"]!=frame["selected_ids_sha256"]):
        raise ValueError("MISMATCHED_FROZEN_SAMPLE_SOURCES")
    names={r["canonical_security_id"]:r["security_name"] for r in
           csv.DictReader(INTERVALS.open(encoding="utf-8"))}
    discover={r["security_id"]:r for r in d["rows"]}
    financial={r["security_id"]:r for r in c["rows"]}
    if len(discover)!=128 or len(financial)!=128:
        raise ValueError("DUPLICATE_SAMPLE_IDENTITIES")
    return frame,names,discover,financial,fix

def target_for(sid,discovery,resolution):
    if discovery.get("chosen"):
        return discovery["chosen"]["original_pdf_url"],"UNIQUE_CNINFO_SOURCE_METADATA"
    if (sid==resolution["security_id"] and
        discovery["status"]=="MULTIPLE_SAME_DAY_ORIGINAL_PDFS_UNRESOLVED"):
        url=resolution["full_report"]["pdf_url"]
        if url not in {x["original_pdf_url"] for x in discovery["original_candidates"]}:
            raise ValueError("RESOLVED_PDF_NOT_A_FROZEN_SOURCE_CANDIDATE")
        return url,"PDF_COVER_AND_PAGE_COUNT_DISAMBIGUATED"
    return None,"SOURCE_URL_UNRESOLVED"

def collect(out,limit=128,fetch=fetch_binary):
    if not 1<=limit<=128:
        raise ValueError("INVALID_ISSUER_LIMIT")
    if out.exists():
        raise ValueError("DO_NOT_OVERWRITE_CONTENT_AUDIT")
    frame,names,discovery,financial,resolution=_sources()
    receipts=[]
    fail_streak=0
    for i,sid in enumerate(frame["selected_ids"][:limit],1):
        src=discovery[sid]
        vendor=financial[sid]
        url,how=target_for(sid,src,resolution)
        rec={
            "security_id":sid,"original_pdf_url":url,"source_resolution":how,
            "source_announcement_day":src.get("chosen",{}).get("publication_day")
                if src.get("chosen") else resolution["original_publication_day"] if sid==resolution["security_id"] else None,
            "vendor_notice_dates":vendor["vendor_announcement_dates"],
            "vendor_update_dates":vendor["vendor_update_dates"],
            "original_pdf_bytes_committed_to_main_by_this_audit":False,
            "historical_asof_financial_fields_certified":False,
            "live_buy_eligibility":"NOT_AUTHORIZED",
        }
        if not url:
            rec["status"]="UNRESOLVED_OFFICIAL_DOCUMENT_SOURCE"
        elif fail_streak>=6:
            rec["status"]="UNQUERIED_AFTER_SIX_PDF_FETCH_FAILURES"
        else:
            try:
                data=fetch(url)
                audit=verify_document(data,names[sid],{
                    "revenue_yuan":vendor["vendor_revenue_yuan"],
                    "parent_profit_yuan":vendor["vendor_parent_profit_yuan"]})
                rec.update(audit)
                rec["status"]=("FULL_ORIGINAL_REPORT_CONTENT_CHECK_PASS"
                               if audit["full_report_identity_pass"]
                               else "ORIGINAL_PDF_FULL_REPORT_IDENTITY_NOT_VERIFIED")
                fail_streak=0
            except (OSError,RuntimeError,ValueError) as exc:
                rec["status"]="PDF_RETRIEVAL_OR_DECODING_FAILED"
                rec["failure_reason"]=type(exc).__name__+":"+str(exc)[:135]
                fail_streak+=1
        receipts.append(rec)
        print(f"PDF {i:03d}/{limit:03d} {sid} {rec['status']} "
              f"AMOUNTS={rec.get('both_financial_amounts_have_text_matches',False)}",
              flush=True)
    result={
        "schema":"V29_2025_FY2024_ORIGINAL_PDF_CONTENT_AUDIT_128_V1",
        "captured_at_utc":datetime.now(timezone.utc).isoformat(),
        "frozen_sample_sha256":frame["selected_ids_sha256"],
        "requested_count":limit,"full_128_attempted":limit==128,
        "resolved_pdf_source_count":sum(x["original_pdf_url"] is not None for x in receipts),
        "complete_pdf_content_identity_pass_count":sum(x.get("full_report_identity_pass") is True for x in receipts),
        "both_vendor_amounts_text_found_count":sum(x.get("both_financial_amounts_have_text_matches") is True for x in receipts),
        "pdf_fetch_or_decode_failed_count":sum(x["status"]=="PDF_RETRIEVAL_OR_DECODING_FAILED" for x in receipts),
        "summary_or_identity_uncertain_count":sum(x["status"]=="ORIGINAL_PDF_FULL_REPORT_IDENTITY_NOT_VERIFIED" for x in receipts),
        "this_job_commits_original_pdf_bytes":False,
        "original_2025_pdf_bytes_at_release_sha_certified":False,
        "semantic_numeric_field_mapping_certified":False,
        "independent_oos_validated":False,
        "live_buy_eligibility":"NOT_AUTHORIZED",
        "rows":receipts,
    }
    out.mkdir(parents=True)
    (out/"PDF_CONTENT_AUDIT_128.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({k:v for k,v in result.items() if k!="rows"},ensure_ascii=False),flush=True)
    return result

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--out",required=True,type=Path)
    p.add_argument("--limit",type=int,default=128)
    a=p.parse_args()
    collect(a.out,a.limit)

if __name__=="__main__":
    main()
