from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import tempfile
from pathlib import Path

import fitz

MIN_CHARS = 20

def sha_file(path: Path) -> str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""):
            h.update(b)
    return h.hexdigest()

def stable_sha256(obj) -> str:
    b=json.dumps(obj,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()
    return hashlib.sha256(b).hexdigest()

def normalize_text(s: str) -> str:
    lines=[]
    for line in str(s or "").replace("\r\n","\n").replace("\r","\n").split("\n"):
        z=re.sub(r"[ \t\u3000]+"," ",line).strip()
        if z:
            lines.append(z)
    return "\n".join(lines)

def validate_pdf(path: Path, expected_sha256: str | None = None) -> str:
    b=path.read_bytes()
    if len(b)<1024:
        raise RuntimeError("BLOCKED_INPUT_INTEGRITY:PDF_TOO_SMALL")
    if b[:2048].find(b"%PDF-")<0:
        raise RuntimeError("BLOCKED_INPUT_INTEGRITY:PDF_HEADER_MISSING")
    actual=hashlib.sha256(b).hexdigest()
    if expected_sha256 and actual!=expected_sha256:
        raise RuntimeError("BLOCKED_INPUT_INTEGRITY:OBJECT_SHA256_MISMATCH")
    return actual

def extract_pdf(path: Path, expected_sha256: str | None = None) -> tuple[list[dict],dict]:
    object_sha=validate_pdf(path,expected_sha256)
    try:
        doc=fitz.open(path)
    except Exception as e:
        raise RuntimeError(f"BLOCKED_TEXT_EXTRACTION:PDF_OPEN_FAILED:{type(e).__name__}")
    rows=[]
    try:
        page_count=doc.page_count
        for i in range(page_count):
            page=doc.load_page(i)
            text=normalize_text(page.get_text("text"))
            rows.append({
                "object_sha256":object_sha,
                "page_number":i+1,
                "text":text,
            })
    finally:
        doc.close()
    chars=sum(len(re.sub(r"\s+","",r["text"])) for r in rows)
    pages_with_text=sum(bool(r["text"]) for r in rows)
    if chars<MIN_CHARS:
        raise RuntimeError("BLOCKED_TEXT_EXTRACTION:INSUFFICIENT_EMBEDDED_TEXT")
    receipt={
        "object_sha256":object_sha,
        "pdf_page_count":len(rows),
        "pages_with_text":pages_with_text,
        "total_nonwhitespace_characters":chars,
        "page_text_sha256":stable_sha256(rows),
        "status":"TEXT_EXTRACTION_PASS",
        "ocr_used":False,
    }
    return rows,receipt

def write_outputs(pdf_path:Path,out_dir:Path,canonical_security_id:str,announcement_id:str,expected_sha256:str|None):
    rows,rec=extract_pdf(pdf_path,expected_sha256)
    out_dir.mkdir(parents=True,exist_ok=True)
    stem=f"{canonical_security_id.replace(':','_')}_{announcement_id}"
    text_path=out_dir/f"{stem}_PAGE_TEXT.csv"
    with text_path.open("w",encoding="utf-8",newline="") as f:
        w=csv.DictWriter(f,fieldnames=["object_sha256","page_number","text"],lineterminator="\n")
        w.writeheader(); w.writerows(rows)
    rec={
        "schema":"AI_CORE_EVID_V2_8_4_OFFICIAL_PDF_TEXT_EXTRACTION_RECEIPT_V1",
        "version":"V2.8.4",
        "canonical_security_id":canonical_security_id,
        "announcement_id":announcement_id,
        **rec,
        "page_text_file":str(text_path),
        "page_text_file_sha256":sha_file(text_path),
        "real_security_classification_computed":False,
        "price_or_return_data_consumed":False,
    }
    rec["receipt_sha256"]=stable_sha256(rec)
    rp=out_dir/f"{stem}_TEXT_EXTRACTION_RECEIPT.json"
    rp.write_text(json.dumps(rec,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(rec,ensure_ascii=False,indent=2))

def make_pdf(path:Path,pages:list[str]):
    doc=fitz.open()
    for txt in pages:
        p=doc.new_page()
        if txt:
            p.insert_text((72,72),txt,fontsize=11)
    doc.save(path)
    doc.close()

def self_test():
    tests=[]
    def ck(name,fn,expected=None,validator=None):
        try:
            out=fn()
            passed=(expected is None) and (validator(out) if validator else True)
            tests.append({"name":name,"pass":bool(passed),"actual":"PASS"})
        except RuntimeError as e:
            actual=str(e).split(":",1)[0]
            tests.append({"name":name,"pass":actual==expected,"actual":actual,"expected":expected})
    with tempfile.TemporaryDirectory() as td:
        root=Path(td)
        p=root/"good.pdf"
        make_pdf(p,[
            "第一页：公司人工智能芯片已经量产并实现销售收入。",
            "",
            "第三页：本页用于验证页码与文本提取的一致性。"
        ])
        rows,rec=extract_pdf(p,sha_file(p))
        ck("E01_page_count",lambda:(rows,rec),validator=lambda x:x[1]["pdf_page_count"]==3)
        ck("E02_page_numbers_1_based",lambda:(rows,rec),validator=lambda x:[r["page_number"] for r in x[0]]==[1,2,3])
        ck("E03_empty_page_allowed",lambda:(rows,rec),validator=lambda x:x[0][1]["text"]=="")
        ck("E04_text_pages_count",lambda:(rows,rec),validator=lambda x:x[1]["pages_with_text"]==2)
        ck("E05_no_ocr",lambda:(rows,rec),validator=lambda x:x[1]["ocr_used"] is False)
        ck("E06_sha_revalidation",lambda:extract_pdf(p,"0"*64),"BLOCKED_INPUT_INTEGRITY")
        tiny=root/"tiny.pdf"; tiny.write_bytes(b"%PDF-1.7")
        ck("E07_tiny_blocks",lambda:extract_pdf(tiny),"BLOCKED_INPUT_INTEGRITY")
        fake=root/"fake.pdf"; fake.write_bytes(b"x"*2048)
        ck("E08_header_blocks",lambda:extract_pdf(fake),"BLOCKED_INPUT_INTEGRITY")
        blank=root/"blank.pdf"; make_pdf(blank,["",""])
        ck("E09_all_blank_blocks",lambda:extract_pdf(blank),"BLOCKED_TEXT_EXTRACTION")
        ck("E10_page_text_hash_deterministic",lambda:(rows,rec),validator=lambda x:stable_sha256(x[0])==x[1]["page_text_sha256"])
    result={
        "schema":"AI_CORE_EVID_V2_8_4_PDF_TEXT_EXTRACTION_SELFTEST_V1",
        "tests":tests,
        "passed":sum(x["pass"] for x in tests),
        "total":len(tests),
        "all_pass":all(x["pass"] for x in tests),
    }
    result["receipt_sha256"]=stable_sha256(result)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    if not result["all_pass"]:
        raise SystemExit(2)

def main():
    ap=argparse.ArgumentParser()
    sub=ap.add_subparsers(dest="cmd",required=True)
    sub.add_parser("self-test")
    e=sub.add_parser("extract")
    e.add_argument("--pdf",required=True)
    e.add_argument("--out",required=True)
    e.add_argument("--canonical-security-id",required=True)
    e.add_argument("--announcement-id",required=True)
    e.add_argument("--expected-sha256")
    a=ap.parse_args()
    if a.cmd=="self-test":
        self_test()
    else:
        write_outputs(Path(a.pdf),Path(a.out),a.canonical_security_id,a.announcement_id,a.expected_sha256)

if __name__=="__main__":
    main()
