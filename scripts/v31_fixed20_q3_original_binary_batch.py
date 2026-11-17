#!/usr/bin/env python3
"""Single bounded original-Q3 document acquisition for the 20 frozen 2021/22 picks.

Reads original CNINFO metadata and PDF bytes only, plus ONE already published SSE
PDF URL for 603392. NO prices, returns, H00300 evaluation window, or strategy changes.
PDF token presence is a diagnostic, NOT semantic account-row authentication.
"""
import argparse
import hashlib
import io
import json
import re
from collections import Counter
from pathlib import Path
from v31_fixed_top10_official_q3_pdf_metadata import discover
from v29_original_filing_pdf_proof import fetch_binary

RECEIPT=Path("research/V3.1_2021_2022_FIXED_TOP10_SOURCE_ONLY_RECEIPT_20261117.json")
SSE_603392="https://static.sse.com.cn/disclosure/listedinfo/announcement/c/new/2021-10-28/603392_20211028_1_CwDXAYXG.pdf"
MAX_SIZE=28_000_000

def pdf_check(raw, symbol, year, values):
    from pypdf import PdfReader
    doc=PdfReader(io.BytesIO(raw),strict=True)
    if not 2<=len(doc.pages)<=250:
        raise ValueError("UNEXPECTED_Q3_PAGE_COUNT")
    texts=[p.extract_text() or "" for p in doc.pages[:min(8,len(doc.pages))]]
    normalized=[re.sub(r"[\s,，]","",v) for v in texts]
    joined="".join(normalized)
    identity=bool(symbol[:6] in joined and str(year) in joined and
                  ("第三季度报告" in joined or "三季度报告" in joined))
    expected={
      "revenue_yoy_pct": f"{values[2]:.2f}".rstrip("0").rstrip("."),
      "roe_waa_pct": f"{values[3]:g}",
      "deducted_profit_yuan": f"{values[4]:.2f}",
    }
    token_pages={}
    for field,token in expected.items():
        variants={token, token.rstrip("0").rstrip(".")}
        token_pages[field]=[idx+1 for idx,v in enumerate(normalized)
                            if any(t and t in v for t in variants)]
    # Capture tightly bounded exact-token context for manual semantic inspection.
    # Presence next to a label is not enough to tell standalone-Q3 from YTD;
    # do not set a semantic pass flag from text proximity.
    token_context={}
    for field,token in expected.items():
        hits=[]
        for page_no, page_text in enumerate(normalized,1):
            index=page_text.find(token)
            if index>=0:
                hits.append({"page":page_no,
                             "preceding_100_chars":page_text[max(0,index-100):index],
                             "token":token,
                             "following_80_chars":page_text[index+len(token):index+len(token)+80]})
        token_context[field]=hits[:2]
    # Extract exact section-local opening tokens to identify which header columns
    # actually occur in the original filing; never infer from another issuer.
    headings=[]
    for page_no,page_text in enumerate(normalized,1):
        for anchor in ("主要会计数据和财务指标","主要财务数据","年初至报告期末","本报告期"):
            start=page_text.find(anchor)
            if start>=0:
                headings.append({"page":page_no,"anchor":anchor,
                                 "context":page_text[max(0,start-40):start+180]})
    return {"page_count":len(doc.pages),"pdf_issuer_year_title_identity":identity,
            "field_token_pages_first_8":token_pages,
            "field_token_context_first_8":token_context,
            "reported_section_headers_first_8":headings[:8],
            "three_numeric_tokens_somewhere_in_first_8":all(token_pages.values()),
            "table_row_semantics_certified":False}

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    frozen_raw=RECEIPT.read_bytes();fixed=json.loads(frozen_raw)
    assert fixed["schema"]=="V31_FIXED_Q3_EVALUATION_CANDIDATE_SOURCE_ONLY_RECEIPT_V1"
    rows=[]
    for year in (2021,2022):
        for values in fixed[f"year_{year}"]:
            sid,notice=values[0],str(values[1])
            row={"security_id":sid,"year":year,"vendor_notice":notice,
                 "original_pdf_retrieved":False,"original_fields_semantically_authenticated":False,
                 "source_status":"NOT_DISCOVERED"}
            discovery,_=discover(sid,year)
            row["discovery_status"]=discovery["status"]
            candidates=discovery.get("candidates",[])
            if len(candidates)==1 and candidates[0]["publication_day"].replace("-","")==notice:
                row["original_pdf_url"]=candidates[0]["original_pdf_url"]
                row["source"]="CNINFO_OFFICIAL_HISTORICAL_METADATA"
            elif sid=="603392.SH" and year==2021:
                row["original_pdf_url"]=SSE_603392
                row["source"]="SSE_EXPLICIT_PRIOR_PUBLIC_SOURCE_LEAD"
            else:
                row["source_status"]="OFFICIAL_PDF_SOURCE_UNRESOLVED"
            if row.get("original_pdf_url"):
                try:
                    binary=fetch_binary(row["original_pdf_url"])
                    if len(binary)>MAX_SIZE:raise ValueError("EXCEEDED_PDF_BOUND")
                    row["pdf_sha256"]=hashlib.sha256(binary).hexdigest()
                    row["pdf_bytes"]=len(binary)
                    row.update(pdf_check(binary,sid,year,values))
                    row["original_pdf_retrieved"]=True
                    row["source_status"]=("ORIGINAL_PDF_IDENTITY_AND_TOKEN_PRESENCE"
                                          if row["pdf_issuer_year_title_identity"] else "PDF_IDENTITY_UNCERTAIN")
                except Exception as exc:
                    row["source_status"]="OFFICIAL_PDF_RETRIEVAL_OR_PARSE_FAILURE"
                    row["failure_type"]=type(exc).__name__
                    row["failure_detail"]=str(exc)[:180]
            rows.append(row)
            print("FROZEN_Q3_ORIGINAL",year,sid,row["source_status"],flush=True)
    summary=Counter(r["source_status"] for r in rows)
    result={"schema":"V31_20_Q3_ORIGINAL_PDF_BINARY_BATCH_V1",
            "frozen_candidate_receipt_sha256":hashlib.sha256(frozen_raw).hexdigest(),
            "source_counts":dict(summary),"original_pdf_binary_count":sum(r["original_pdf_retrieved"] for r in rows),
            "issuer_title_identity_count":sum(r.get("pdf_issuer_year_title_identity") is True for r in rows),
            "numeric_token_presence_count":sum(r.get("three_numeric_tokens_somewhere_in_first_8") is True for r in rows),
            "original_issuer_field_row_semantics_all_verified":False,
            "published_time_pdf_bytes_sha_certified":False,
            "historical_source_vintages_all_certified":False,
            "outcomes_or_prices_read":False,"trade_authorized":False,
            "rows":rows}
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("FROZEN_Q3_ORIGINAL_BATCH_SUMMARY="+json.dumps({
        "count":len(rows),"statuses":dict(summary),"original_pdf_binary_count":result["original_pdf_binary_count"],
        "identity":result["issuer_title_identity_count"],"token_presence":result["numeric_token_presence_count"],
        "outcomes_or_prices_read":False,"trade_authorized":False},ensure_ascii=False),flush=True)

if __name__=="__main__":main()
