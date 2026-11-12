"""Source-only time semantics census and one original-PDF parity probe.

Do not equate exchange midnight display or UUID folder dates with frozen
CNINFO announcement timestamp/finalpage date semantics. No scientific use.
"""
import hashlib
import json
import re
from collections import Counter
from datetime import date
from pathlib import Path

import fitz
from playwright.sync_api import sync_playwright

INFILE=Path("evidence/V2.9.4_002667_SZSE_RAW_ROWS_RETRIEVAL_V1.json")
OUT=Path("evidence/V2.9.4_002667_SZSE_TIME_SEMANTICS_PDF_PARITY_1.json")
TARGET="1217706310"
CNINFO="https://static.cninfo.com.cn/finalpage/2023-08-31/1217706310.PDF"
SZSE_BASE="https://disc.static.szse.cn/download"
PDF_LIMIT=12_000_000


def time_audit(rows):
    if len(rows)!=486 or len({str(r["ann_id"]) for r in rows})!=486:
        raise ValueError("EXACT_SOURCE_486_ROWS_REQUIRED")
    differences=Counter()
    titles=Counter()
    non_midnight=[]
    unsafe=[]
    mismatches=[]
    for r in rows:
        aid=str(r["ann_id"])
        when=str(r["exchange_publish_time_raw"])
        day=str(r["publication_day"])
        loc=str(r["exchange_relative_path"])
        codes=r["exchange_stock_codes"]
        stamp=re.fullmatch(r"(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2})",when)
        path=re.fullmatch(r"/disc/disk\d+/finalpage/(\d{4}-\d{2}-\d{2})/([a-f0-9-]{36})\.PDF",loc,re.I)
        if not stamp or not path or stamp.group(1)!=day or codes!=["002667"]:
            unsafe.append(aid)
            continue
        delta=(date.fromisoformat(day)-date.fromisoformat(path.group(1))).days
        differences[str(delta)]+=1
        if stamp.group(2)!="00:00:00":
            non_midnight.append(aid)
        titles[r["title"].split("：",1)[0]]+=1
        if delta!=0:
            mismatches.append({"ann_id":aid,"official_publication_day":day,
                               "exchange_attachment_folder_day":path.group(1),
                               "folder_day_delta":delta})
    return {"row_count":len(rows),"schema_unsafe_ids":unsafe,
            "exchange_midnight_display_count":len(rows)-len(non_midnight)-len(unsafe),
            "non_midnight_ids":non_midnight,"date_folder_delta_days":dict(sorted(differences.items())),
            "title_prefix_counts":dict(sorted(titles.items())),
            "folder_day_mismatch_count":len(mismatches),
            "folder_day_mismatch_rows":mismatches,
            "all_source_rows_structurally_valid":not unsafe,
            "exact_publication_timestamp_proven":False,
            "cninfo_original_locator_temporal_semantics_proven":False}


def inspect_pdf(blob):
    if len(blob)>PDF_LIMIT or not blob.startswith(b"%PDF-"):
        raise ValueError("NOT_BOUNDED_ORIGINAL_PDF")
    d=fitz.open(stream=blob,filetype="pdf")
    if d.is_encrypted or not 1<=d.page_count<=25:
        raise ValueError("UNSUPPORTED_SOURCE_PDF")
    raw="\n".join(page.get_text() for page in d)
    normalized="".join(raw.split())
    fields={s:s in normalized for s in
            ("威领新能源股份有限公司","002667","关于控股股东部分股份质押的公告","2023-138")}
    return {"sha256":hashlib.sha256(blob).hexdigest(),
            "byte_count":len(blob),"page_count":d.page_count,
            "content_field_checks":fields,
            "content_match":all(fields.values()),
            "normalized_extracted_text_sha256":hashlib.sha256(normalized.encode()).hexdigest()}


def pdf_pair(target):
    if target["ann_id"]!=TARGET or target["publication_day"]!="2023-08-31":
        raise ValueError("TARGET_CROSSWALK_NOT_VERIFIED")
    url=SZSE_BASE+target["exchange_relative_path"]
    results=[]
    with sync_playwright() as pw:
        req=pw.request.new_context(user_agent="Mozilla/5.0")
        try:
            for name,uri in (("cninfo_original",CNINFO),("szse_exchange_original",url)):
                record={"source":name,"official_url":uri,"content_verified":False}
                try:
                    response=req.get(uri,timeout=45000)
                    record["http_status"]=response.status
                    if response.status==200:
                        record.update(inspect_pdf(response.body()))
                        record["content_verified"]=record["content_match"]
                    else:
                        record["error"]="OFFICIAL_PDF_HTTP_NOT_200"
                except Exception as ex:
                    record["error"]=type(ex).__name__+":"+str(ex)[:160]
                results.append(record)
        finally:req.dispose()
    ok=len(results)==2 and all(x["content_verified"] for x in results)
    return {"source_attempts":results,"both_official_pdfs_content_verified":ok,
            "same_pdf_bytes":ok and results[0]["sha256"]==results[1]["sha256"],
            "same_normalized_extracted_text":ok and
             results[0]["normalized_extracted_text_sha256"]==
             results[1]["normalized_extracted_text_sha256"],
            "all_486_original_pdfs_verified":False}


def main():
    file=json.loads(INFILE.read_text(encoding="utf-8"))
    if file["evaluation"]["full_source_row_reference_match"] is not True:
        raise RuntimeError("PERSISTED_SOURCE_ROW_REFERENCE_NOT_VERIFIED")
    rows=file["source_rows"]
    summary=time_audit(rows)
    target=next((r for r in rows if r["ann_id"]==TARGET),None)
    if not target:
        raise RuntimeError("TARGET_ID_NOT_IN_FROZEN_SOURCE_ROWS")
    comparison=pdf_pair(target)
    result={"schema":"V294_002667_SOURCE_DAY_FOLDER_AND_ONE_PDF_PAIR_DIAGNOSTIC_V1",
            "source_rows_path":str(INFILE),"frozen_range":["2023-01-01","2024-12-30"],
            "time_field_audit":summary,"target_sample_pdf_comparison":comparison,
            "research_gate":{"source_metadata_diagnostic_only":True,
                "scientific_source_migration_authorized":False,
                "batch3_authorized":False,"batch4_authorized":False,
                "protected_outcomes_consumed":False,"trading_authorized":False}}
    OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"date_folder_delta_days":summary["date_folder_delta_days"],
        "title_prefix_counts":summary["title_prefix_counts"],
        "two_pdf_content_verified":comparison["both_official_pdfs_content_verified"],
        "two_pdf_bytes_equal":comparison["same_pdf_bytes"]},ensure_ascii=False))
    if not summary["all_source_rows_structurally_valid"] or not comparison["both_official_pdfs_content_verified"]:
        raise SystemExit("SOURCE_SEMANTICS_AND_PDF_PAIR_NOT_FULLY_ATTESTED")

if __name__=="__main__":main()
