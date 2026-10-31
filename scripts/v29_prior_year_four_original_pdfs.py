#!/usr/bin/env python3
"""Fixed four ORIGINAL 2023/2024 annual PDFs: issuer, SHA, field-ROW evidence.

Originals are derived from two pre-frozen historical source cohorts; no price,
2023/2024 outcomes, growth rank or realized financial returns are consulted.
A numeric token anywhere in a PDF NEVER certifies its financial statement field.
A 2026-captured PDF SHA NEVER proves its original publication-time binary hash.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from datetime import datetime,timezone
from decimal import Decimal,InvalidOperation,ROUND_HALF_UP
from pathlib import Path

from v29_original_filing_pdf_proof import fetch_binary
from v29_2023_2024_original_filing_discovery_256 import load_frozen_frames

ROOT=Path(__file__).resolve().parents[1]
OFFICIAL=ROOT/"evidence/v29_original_2023_2024_reports_256/HISTORICAL_256_OFFICIAL_DISCOVERY.json"
VENDOR=ROOT/"research/v29_prior_financial_source_256/FINANCIAL_256_VENDOR_COVERAGE.json"
MEMBERS=ROOT/"evidence/V2.8.1_PIT_MEMBERSHIP_INTERVALS.csv"
SCHEMA="V29_PRIOR_YEAR_FOUR_REAL_ORIGINAL_PDF_FINANCIAL_ROW_EVIDENCE_V1"
FIXED_FIRST_N=2
FIELDS={
    "revenue_yuan":("营业收入","营业总收入"),
    "parent_net_profit_yuan":("归属于上市公司股东的净利润","归属于母公司股东的净利润",
                             "归属于母公司所有者的净利润"),
    "revenue_growth_yoy_pct":("营业收入","营业总收入"),
    "weighted_roe_pct":("加权平均净资产收益率",),
}
MONEY=("revenue_yuan","parent_net_profit_yuan")
NUMERIC_TOKEN_BOUNDARY=r"(?<![0-9.]){}(?![0-9.])"

def sha(b):
    return hashlib.sha256(b).hexdigest()

def compact(text):
    return re.sub(r"[\s,，]","",str(text or "")).replace("−","-").replace("－","-")

def numeric_candidates(value,is_percentage=False):
    if value is None:
        return []
    try:
        v=Decimal(str(value))
    except InvalidOperation:
        return []
    units=(("percentage",Decimal(1)),) if is_percentage else (
        ("yuan",Decimal(1)),("thousand_yuan",Decimal(1000)),
        ("ten_thousand_yuan",Decimal(10000)))
    values=[]
    for unit,divisor in units:
        x=v/divisor
        for number in {x,x.quantize(Decimal("0.01"),rounding=ROUND_HALF_UP)}:
            s=format(number,"f")
            values.extend([(unit,s),(unit,s.rstrip("0").rstrip(".") if "." in s else s)])
    # Longest exact tokens first to prevent a smaller 2026 value matching substring.
    return sorted({(u,s) for u,s in values if s},key=lambda x:-len(x[1]))

def nearby_labels_and_numbers(lines,label_aliases,amount,percentage=False,max_pages=45):
    """Find literal value in the line with its field name or two adjacent lines.

    The result is candidate evidence, not automated table-cell certification:
    mixed multiyear tables / units / restatements still require contextual audit.
    """
    values=numeric_candidates(amount,percentage)
    if not values:
        return {"status":"VENDOR_FIELD_UNAVAILABLE_NO_PDF_MATCH_CLAIM",
                "candidate_rows":[],"semantic_table_cell_certified":False}
    found=[]
    for pg,raw_lines in lines:
        if pg>max_pages:
            break
        for i,line in enumerate(raw_lines):
            # Annual-report table labels can wrap across two lines.
            for lookahead in (1,2,3):
                window=raw_lines[i:i+lookahead]
                norm=compact("".join(window))
                aliases=[x for x in label_aliases if compact(x) in norm]
                if not aliases:
                    continue
                for unit,token in values:
                    match=re.search(NUMERIC_TOKEN_BOUNDARY.format(re.escape(token)),norm)
                    if match:
                        label_start=min(norm.find(compact(x)) for x in aliases)
                        number_start=match.start()
                        # Do not claim same-row evidence if the amount occurs
                        # before the label or far away in a multirow text block.
                        if number_start<label_start or number_start-label_start>180:
                            continue
                        hit={"pdf_page":pg,"label":aliases[0],
                             "numeric_text":token,"provisional_unit":unit,
                             "text_lines_in_window":lookahead,
                             "excerpt":" | ".join(x.strip() for x in window)[:320],
                             "semantic_table_cell_certified":False}
                        found.append(hit)
                        break
                if any(x["pdf_page"]==pg and x["excerpt"].startswith(line.strip()[:10])
                       for x in found):
                    break
    # When multiple years/scale presentations match, retain all candidate
    # contexts. No automated pass is issued simply because a token matched.
    unique=[]
    seen=set()
    for x in found:
        key=(x["pdf_page"],x["excerpt"],x["numeric_text"])
        if key not in seen:
            unique.append(x)
            seen.add(key)
    return {
        "status":("FIELD_LABEL_AND_EXPECTED_VALUE_NEARBY_UNITS_NOT_INDEPENDENTLY_CERTIFIED"
                  if unique else "NO_FIELD_ROW_VALUE_PROXIMITY_FOUND"),
        "candidate_rows":unique[:8],
        "candidate_count":len(unique),
        "semantic_table_cell_certified":False,
    }

def sources():
    frozen,frozen_sha=load_frozen_frames()
    official=json.loads(OFFICIAL.read_bytes())
    vendor=json.loads(VENDOR.read_bytes())
    if (official.get("schema")!="V29_2023_2024_2X128_ORIGINAL_ANNUAL_REPORT_DISCOVERY_V1" or
        vendor.get("schema")!="V29_FY2022_FY2023_2X128_RETROSPECTIVE_VENDOR_FINANCIAL_SOURCE_V1" or
        official["sealed_prequery_cohorts_manifest_sha256"]!=frozen_sha or
        vendor["prequery_historical_frame_sha256"]!=frozen_sha):
        raise ValueError("FROZEN_FOUR_ISSUER_SOURCE_PROVENANCE_MISMATCH")
    names={row["canonical_security_id"]:row["security_name"]
           for row in csv.DictReader(MEMBERS.open(encoding="utf-8"))}
    targets=[]
    for f,s,v in zip(frozen["cohorts"],official["cohorts"],vendor["cohorts"]):
        if (s["cohort_id"]!=f["cohort_id"] or v["cohort_id"]!=f["cohort_id"] or
                len(s["rows"])!=len(v["rows"])!=128):
            raise ValueError("COHORT_COUNTS_OR_SOURCE_IDENTITIES_DIFFER")
        source_map={x["security_id"]:x for x in s["rows"]}
        vendor_map={x["security_id"]:x for x in v["rows"]}
        for sid in f["selected_ids"][:FIXED_FIRST_N]:
            so,vr=source_map[sid],vendor_map[sid]
            chosen=so.get("chosen")
            if (not chosen or vr["matched_vendor_rows"]!=1 or
                 vr["notice_days"]!=[chosen["notice_day"]]):
                raise ValueError("FIXED_PILOT_SOURCE_OR_VENDOR_NOTICE_NOT_UNIQUE")
            targets.append({
                "security_id":sid,
                "fiscal_year":int(f["report_period_end"][:4]),
                "issue_year":f["expected_issuer_publication_year"],
                "source_notice":chosen["notice_day"],
                "source_url":chosen["original_pdf_url"],
                "issuer_short_name_in_2026_membership":names[sid],
                "vendor_values_2026_retrieval":vr["retrospective_financial_field_values"],
                "vendor_update_days":vr["update_days"],
                "vendor_source_hashes":vr["source_record_sha256"],
            })
    if len(targets)!=4:
        raise ValueError("EXPECTED_FOUR_FIXED_SOURCE_TARGETS")
    return targets,{
        "frozen_frame_sha256":frozen_sha,
        "official_metadata_sha256":sha(OFFICIAL.read_bytes()),
        "retrospective_vendor_json_sha256":sha(VENDOR.read_bytes()),
    }

def examine_pdf(raw,target):
    import pymupdf
    doc=pymupdf.open(stream=raw,filetype="pdf")
    pages=len(doc)
    if pages<30:
        raise ValueError("ORIGINAL_PDF_TOO_SHORT_FOR_FULL_ANNUAL_REPORT")
    year=target["fiscal_year"]
    preface="".join(compact(doc[i].get_text("text",sort=True))
                    for i in range(min(7,pages)))
    name=compact(target["issuer_short_name_in_2026_membership"])
    issuer_ok=(target["security_id"].split(":")[1] in preface or
               (bool(name) and name in preface))
    year_ok=str(year) in preface
    full_report=("年度报告" in preface and "年度报告摘要" not in preface)
    if not (issuer_ok and year_ok and full_report):
        raise ValueError("ORIGINAL_PDF_ISSUER_YEAR_OR_FULL_REPORT_NOT_VERIFIED")
    text_by_page=[]
    for i in range(min(45,pages)):
        lines=(doc[i].get_text("text",sort=True) or "").splitlines()
        text_by_page.append((i+1,lines))
    findings={}
    for key,aliases in FIELDS.items():
        findings[key]=nearby_labels_and_numbers(
            text_by_page,aliases,target["vendor_values_2026_retrieval"].get(key),
            percentage=key.endswith("_pct"))
    return {
        "original_full_issuer_report_identity_verified":True,
        "pages":pages,
        "2026_capture_pdf_sha256":sha(raw),
        "binary_size":len(raw),
        "issuer_identity_in_cover_or_front_matter":True,
        "fiscal_year_report_title_in_cover":True,
        "financial_field_row_evidence":findings,
        "field_nearby_value_hits":sum(
            x["candidate_count"] for x in findings.values()
            if x.get("candidate_count")),
        "semantic_table_cell_certified":False,
        "2023_or_2024_original_release_pdf_hash_certified":False,
        "historical_year_contemporaneous_financial_vintage_certified":False,
    }

def collect(out,fetch=fetch_binary):
    if out.exists():
        raise ValueError("ORIGINAL_PDF_CAPTURE_ALREADY_EXISTS_NO_OVERWRITE")
    targets,source_sha=sources()
    out.mkdir(parents=True)
    receipts=[]
    for target in targets:
        sid=target["security_id"]
        rec={**target,
             "original_pdf_retrieved_at_utc":datetime.now(timezone.utc).isoformat(),
             "source_capture_calendar_year":2026,
             "historical_asof_filing_fields_certified":False,
             "original_release_time_binary_hash_known":False,
             "live_buy_eligibility":"NOT_AUTHORIZED"}
        try:
            raw=fetch(target["source_url"])
            audit=examine_pdf(raw,target)
            rec.update(audit)
            filename=f"{sid.replace(':','-')}-FY{target['fiscal_year']}-ISSUED{target['issue_year']}.pdf"
            (out/filename).write_bytes(raw)
            rec["stored_pdf_file"]=filename
            rec["status"]="FULL_ISSUER_PDF_BYTES_ARCHIVED_FIELD_ROW_EVIDENCE_ONLY"
        except (OSError,ValueError,RuntimeError,TypeError) as exc:
            rec["status"]="ORIGINAL_PDF_IDENTITY_FETCH_OR_PARSE_FAILED"
            rec["error_type"]=type(exc).__name__
            rec["error_detail"]=str(exc)[:180]
            rec["stored_pdf_file"]=None
        receipts.append(rec)
        print(f"ORIGINAL_PDF {sid} {rec['status']} "
              f"ROWS={rec.get('field_nearby_value_hits',0)} "
              f"PAGES={rec.get('pages')} HASH={rec.get('2026_capture_pdf_sha256')}",
              flush=True)
    result={
        "schema":SCHEMA,
        "captured_at_utc":datetime.now(timezone.utc).isoformat(),
        "source_manifests_sha256":source_sha,
        "frozen_target_count":4,
        "attempted_count":len(receipts),
        "archived_full_original_pdf_count":sum(
            x["status"]=="FULL_ISSUER_PDF_BYTES_ARCHIVED_FIELD_ROW_EVIDENCE_ONLY"
            for x in receipts),
        "field_context_candidate_only_no_automatic_semantic_certification":True,
        "complete_original_financial_field_pit_certified_count":0,
        "no_outcomes_or_return_data_read":True,
        "independent_unseen_oos_validated":False,
        "live_buy_eligibility":"NOT_AUTHORIZED",
        "rows":receipts,
    }
    (out/"ORIGINAL_FOUR_YEAR_FIELD_CONTEXT_RECEIPT.json").write_text(
        json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return result

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--out",required=True,type=Path)
    a=p.parse_args()
    report=collect(a.out)
    print(json.dumps({"attempted":report["attempted_count"],
                      "original_pdf_archived":report["archived_full_original_pdf_count"],
                      "historical_asof_semantic_certified":0,
                      "buy":"NOT_AUTHORIZED"},ensure_ascii=False))
    if report["archived_full_original_pdf_count"]==0:
        raise SystemExit("NO_ORIGINAL_REPORT_PDF_PASSED_IDENTITY_GATE")

if __name__=="__main__":
    main()
