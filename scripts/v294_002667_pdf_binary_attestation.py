"""Read-only, bounded original-PDF retrieval attestation for CNINFO and STCN.

No source completeness certificate, no frozen research admission and no returns.
"""
import hashlib
import json
from pathlib import Path
import fitz
from playwright.sync_api import sync_playwright

OUT=Path("evidence/V2.9.4_002667_20230831_PDF_BINARY_ATTESTATION_1.json")
SOURCES=[
    ("cninfo_original_announcement","https://static.cninfo.com.cn/finalpage/2023-08-31/1217706310.PDF"),
    ("stcn_contemporaneous_page_B054","https://epaper.stcn.com/att/202308/31/a1aac3f8-65a1-4cfa-afca-02d690843077.pdf"),
]
MAX_BYTES=16_000_000


def check_pdf(blob, source_type):
    if len(blob)>MAX_BYTES or not blob.startswith(b"%PDF-"):
        raise ValueError("NOT_A_BOUNDED_PDF")
    doc=fitz.open(stream=blob,filetype="pdf")
    if doc.is_encrypted or doc.page_count<1 or doc.page_count>100:
        raise ValueError("UNSUPPORTED_PDF_OR_PAGE_COUNT")
    txt="\n".join(p.get_text() for p in doc)
    compact="".join(txt.split())
    fields={
        "issuer":("威领新能源股份有限公司" in compact),
        "security_code":("002667" in compact),
        "announcement_title":("关于控股股东部分股份质押的公告" in compact),
        "announcement_number":("2023-138" in compact),
        "date":("2023年8月31日" in compact or "2023年8月30日" in compact),
    }
    return {"sha256":hashlib.sha256(blob).hexdigest(),
            "bytes":len(blob),"pages":doc.page_count,
            "text_chars":len(txt),"content_fields":fields,
            "field_checks_pass":all(fields.values())}


def main():
    results=[]
    with sync_playwright() as pw:
        request=pw.request.new_context(user_agent="Mozilla/5.0")
        try:
            for name,url in SOURCES:
                item={"source_type":name,"url":url,
                      "retrieved_at":"2026-11-12_SOURCE_RETRIEVAL_RUNTIME"}
                try:
                    response=request.get(url,timeout=30000)
                    item["http_status"]=response.status
                    if not response.ok:
                        item["status"]="FETCH_HTTP_FAILURE"
                    else:
                        item.update(check_pdf(response.body(),name))
                        item["status"]="PDF_CONTENT_VERIFIED" if item["field_checks_pass"] else "PDF_FIELDS_MISMATCH"
                except Exception as exc:
                    item["status"]="SOURCE_PDF_NOT_VERIFIED"
                    item["error_type"]=type(exc).__name__
                    item["error_summary"]=str(exc)[:200]
                results.append(item)
        finally:
            request.dispose()
    result={"schema":"V294_002667_20230831_TWO_ORIGIN_PDF_ATTESTATION_V1",
            "security_id":"SZSE:002667","cninfo_id":"1217706310",
            "source_attempts":results,
            "cninfo_pdf_binary_verified":any(x["source_type"]=="cninfo_original_announcement" and x["status"]=="PDF_CONTENT_VERIFIED" for x in results),
            "independent_contemporaneous_page_pdf_verified":any(x["source_type"]=="stcn_contemporaneous_page_B054" and x["status"]=="PDF_CONTENT_VERIFIED" for x in results),
            "full_issuer_census_certified":False,
            "historical_batch3_authorized":False,
            "batch4_authorized":False,
            "protected_outcomes_consumed":False,
            "trading_authorized":False}
    OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({k:v for k,v in result.items() if k not in ("source_attempts",)},ensure_ascii=False))
    print(json.dumps([{k:v for k,v in x.items() if k not in ("url",)} for x in results],ensure_ascii=False))
    if not any(x["status"]=="PDF_CONTENT_VERIFIED" for x in results):
        raise SystemExit("NO_PDF_BINARY_CONTENT_VERIFIED")


if __name__=="__main__":
    main()
