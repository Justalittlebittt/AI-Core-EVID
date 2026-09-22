from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass

PDF_RE = re.compile(r"^finalpage/(\d{4}-\d{2}-\d{2})/(\d+)\.pdf$", re.I)

def stable_sha256(obj) -> str:
    b=json.dumps(obj,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()
    return hashlib.sha256(b).hexdigest()

def canonical_id(column:str, sec_code:str) -> str:
    c=str(sec_code or "").strip()
    if not re.fullmatch(r"\d{6}",c):
        raise RuntimeError("IDENTITY_BLOCKED_INVALID_SECURITY_CODE")
    if column=="sse":
        return f"SSE:{c}"
    if column=="szse":
        return f"SZSE:{c}"
    raise RuntimeError("IDENTITY_BLOCKED_UNKNOWN_STREAM")

def validate_hit(hit:dict) -> dict:
    aid=str(hit.get("announcement_id") or "").strip()
    adjunct=str(hit.get("adjunct_url") or "").strip()
    column=str(hit.get("column") or "").strip()
    sec=str(hit.get("sec_code") or "").strip()
    if not aid:
        raise RuntimeError("IDENTITY_BLOCKED_MISSING_ANNOUNCEMENT_ID")
    cid=canonical_id(column,sec)
    m=PDF_RE.fullmatch(adjunct)
    if not m:
        raise RuntimeError("LOCATOR_BLOCKED_INVALID_PDF_PATH")
    if m.group(2)!=aid:
        raise RuntimeError("LOCATOR_BLOCKED_ANNOUNCEMENT_ID_MISMATCH")
    return {
        "canonical_security_id":cid,
        "announcement_id":aid,
        "adjunct_url":adjunct,
        "disclosure_date_from_path":m.group(1),
        "official_url":"https://static.cninfo.com.cn/"+adjunct,
    }

def resolve_locator(hit:dict, inventory_rows:list[dict]) -> dict:
    loc=validate_hit(hit)
    exact=[r for r in inventory_rows if str(r.get("announcement_id") or "").strip()==loc["announcement_id"]]
    if exact:
        if len(exact)!=1:
            raise RuntimeError("LOCATOR_BLOCKED_DUPLICATE_ANNOUNCEMENT_ID_IN_INVENTORY")
        r=exact[0]
        inv_cid=str(r.get("canonical_security_id") or "").strip()
        inv_adj=str(r.get("adjunct_url") or "").strip()
        if inv_cid!=loc["canonical_security_id"]:
            raise RuntimeError("IDENTITY_BLOCKED_INVENTORY_SECURITY_MISMATCH")
        if inv_adj.lower()!=loc["adjunct_url"].lower():
            raise RuntimeError("LOCATOR_BLOCKED_INVENTORY_PATH_MISMATCH")
        return {**loc,"locator_source":"V2.7.29_PRIMARY_LOCATOR_INVENTORY","inventory_reused":True}
    return {**loc,"locator_source":"CNINFO_CANDIDATE_HIT_VALIDATED","inventory_reused":False}

def validate_pdf_bytes(b:bytes) -> dict:
    if len(b)<1024:
        raise RuntimeError("INVALID_PDF_BLOCKED_TOO_SMALL")
    off=b[:2048].find(b"%PDF-")
    if off<0:
        raise RuntimeError("INVALID_PDF_BLOCKED_HEADER_MISSING")
    return {"object_sha256":hashlib.sha256(b).hexdigest(),"bytes":len(b),"pdf_header_offset":off}

def self_test():
    inv=[{
        "canonical_security_id":"SSE:600001",
        "announcement_id":"1234567890",
        "adjunct_url":"finalpage/2026-08-20/1234567890.PDF"
    }]
    tests=[]
    def ck(name,fn,expected=None):
        try:
            out=fn()
            passed=(expected is None)
            tests.append({"name":name,"pass":passed,"actual":"PASS","detail":out})
        except RuntimeError as e:
            actual=str(e).split(":",1)[0]
            tests.append({"name":name,"pass":actual==expected,"actual":actual,"expected":expected})
    good={"column":"sse","sec_code":"600001","announcement_id":"1234567890","adjunct_url":"finalpage/2026-08-20/1234567890.PDF"}
    new={"column":"szse","sec_code":"300001","announcement_id":"2234567890","adjunct_url":"finalpage/2026-09-01/2234567890.PDF"}
    ck("M01_inventory_exact_reuse",lambda:resolve_locator(good,inv))
    ck("M02_valid_new_candidate_locator",lambda:resolve_locator(new,inv))
    ck("M03_bad_security_code",lambda:validate_hit({**good,"sec_code":"ABC"}),"IDENTITY_BLOCKED_INVALID_SECURITY_CODE")
    ck("M04_unknown_stream",lambda:validate_hit({**good,"column":"bjse"}),"IDENTITY_BLOCKED_UNKNOWN_STREAM")
    ck("M05_missing_announcement_id",lambda:validate_hit({**good,"announcement_id":""}),"IDENTITY_BLOCKED_MISSING_ANNOUNCEMENT_ID")
    ck("M06_bad_pdf_path",lambda:validate_hit({**good,"adjunct_url":"https://example.com/a.pdf"}),"LOCATOR_BLOCKED_INVALID_PDF_PATH")
    ck("M07_id_path_mismatch",lambda:validate_hit({**good,"announcement_id":"999"}),"LOCATOR_BLOCKED_ANNOUNCEMENT_ID_MISMATCH")
    ck("M08_inventory_identity_mismatch",lambda:resolve_locator({**good,"sec_code":"600002"},inv),"IDENTITY_BLOCKED_INVENTORY_SECURITY_MISMATCH")
    ck("M09_pdf_too_small",lambda:validate_pdf_bytes(b"%PDF-1.7"),"INVALID_PDF_BLOCKED_TOO_SMALL")
    ck("M10_pdf_header_missing",lambda:validate_pdf_bytes(b"x"*2048),"INVALID_PDF_BLOCKED_HEADER_MISSING")
    ck("M11_valid_pdf",lambda:validate_pdf_bytes(b"%PDF-1.7\n"+b"x"*2048))
    result={"schema":"AI_CORE_EVID_V2_8_4_CANDIDATE_MATERIALIZATION_SELFTEST_V1",
            "tests":tests,"passed":sum(x["pass"] for x in tests),"total":len(tests),
            "all_pass":all(x["pass"] for x in tests)}
    result["receipt_sha256"]=stable_sha256(result)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    if not result["all_pass"]:
        raise SystemExit(2)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("command",choices=["self-test"])
    a=ap.parse_args()
    if a.command=="self-test":
        self_test()

if __name__=="__main__":
    main()
