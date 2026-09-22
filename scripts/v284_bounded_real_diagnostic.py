from __future__ import annotations

import argparse
import csv
import hashlib
import json
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright

import v284_candidate_collector as cc
import v284_pdf_text_extractor as te
import v284_page_scoped_classifier as pc

DATE = "2026-08-31"
MAX_SAMPLE = 4
STATIC = "https://static.cninfo.com.cn/"

def stable_sha256(obj) -> str:
    b=json.dumps(obj,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()
    return hashlib.sha256(b).hexdigest()

def deterministic_key(announcement_id:str)->str:
    return hashlib.sha256(str(announcement_id).encode()).hexdigest()

def select_candidates(rows:list[dict],n:int=MAX_SAMPLE)->list[dict]:
    unique={}
    for r in rows:
        aid=str(r.get("announcement_id") or "").strip()
        if not aid:
            raise RuntimeError("DIAGNOSTIC_BLOCKED_INVALID_CANDIDATE_ID")
        if aid in unique and unique[aid].get("adjunct_url")!=r.get("adjunct_url"):
            raise RuntimeError("DIAGNOSTIC_BLOCKED_CANDIDATE_CONFLICT")
        unique[aid]=r
    ordered=sorted(unique.values(),key=lambda r:(deterministic_key(r["announcement_id"]),r["announcement_id"]))
    return ordered[:n]

def fetch_pdf(api,row:dict,path:Path)->dict:
    aid=str(row["announcement_id"])
    adjunct=str(row["adjunct_url"])
    if not adjunct.lower().endswith(f"/{aid}.pdf".lower()):
        raise RuntimeError("INVALID_OFFICIAL_LOCATOR")
    r=api.get(
        STATIC+adjunct,
        timeout=90000,
        headers={"Referer":"https://www.cninfo.com.cn/","Accept":"application/pdf,*/*;q=0.8"}
    )
    if r.status!=200:
        raise RuntimeError(f"PDF_FETCH_HTTP_{r.status}")
    b=r.body()
    path.write_bytes(b)
    obj_sha=te.validate_pdf(path)
    return {"object_sha256":obj_sha,"bytes":len(b),"http_status":r.status}

def run(out_dir:Path):
    out_dir.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        tmp=Path(td)
        candidates=tmp/"candidates"
        cc.collect(
            __import__("datetime").date.fromisoformat(DATE),
            __import__("datetime").date.fromisoformat(DATE),
            candidates
        )
        dedup=candidates/"V2.8.4_CNINFO_CANDIDATE_DEDUPED.csv"
        rows=list(csv.DictReader(dedup.read_text(encoding="utf-8").splitlines()))
        selected=select_candidates(rows)
        if not selected:
            raise RuntimeError("DIAGNOSTIC_BLOCKED_NO_CANDIDATES")

        results=[]
        with sync_playwright() as pw:
            api=pw.request.new_context(extra_http_headers={
                "User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/153 Safari/537.36"
            })
            home=api.get("https://www.cninfo.com.cn/",timeout=30000)
            if home.status!=200:
                raise RuntimeError(f"CNINFO_HOME_HTTP_{home.status}")
            for i,row in enumerate(selected,1):
                base={
                    "sample_rank":i,
                    "selection_sha256":deterministic_key(row["announcement_id"]),
                    "announcement_id":row["announcement_id"],
                    "canonical_security_id":row["canonical_security_id"],
                    "security_name":row["security_name"],
                    "announcement_title":row["announcement_title"],
                    "adjunct_url":row["adjunct_url"],
                    "matched_terms":row["matched_terms"],
                }
                try:
                    pdf=tmp/f"{i}.pdf"
                    fetch=fetch_pdf(api,row,pdf)
                    page_rows,extract=te.extract_pdf(pdf,fetch["object_sha256"])
                    decision=pc.classify_pages(page_rows)
                    results.append({
                        **base,
                        "pipeline_status":"SUCCESS",
                        **fetch,
                        "pdf_page_count":extract["pdf_page_count"],
                        "pages_with_text":extract["pages_with_text"],
                        "total_nonwhitespace_characters":extract["total_nonwhitespace_characters"],
                        "classification_state":decision["classification_state"],
                        "evidence_page_number":decision["evidence"]["page_number"],
                        "evidence_sentence":decision["evidence"]["evidence_sentence"],
                        "classification_reason":decision["evidence"]["reason"],
                        "decision_sha256":decision["decision_sha256"],
                    })
                except Exception as e:
                    results.append({
                        **base,
                        "pipeline_status":"BLOCKED",
                        "blocker":f"{type(e).__name__}:{e}",
                    })
            api.dispose()

    success=sum(r["pipeline_status"]=="SUCCESS" for r in results)
    blocked=len(results)-success
    status=(
        "DIAGNOSTIC_COMPLETE"
        if success and not blocked else
        "DIAGNOSTIC_COMPLETE_WITH_BLOCKERS"
        if success else
        "DIAGNOSTIC_BLOCKED_ALL_FILINGS"
    )
    fields=[
        "sample_rank","selection_sha256","announcement_id","canonical_security_id","security_name",
        "announcement_title","adjunct_url","matched_terms","pipeline_status","object_sha256","bytes",
        "pdf_page_count","pages_with_text","total_nonwhitespace_characters","classification_state",
        "evidence_page_number","evidence_sentence","classification_reason","decision_sha256","blocker"
    ]
    csv_path=out_dir/"V2.8.4_BOUNDED_REAL_DIAGNOSTIC_RESULTS.csv"
    with csv_path.open("w",encoding="utf-8",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,lineterminator="\n",extrasaction="ignore")
        w.writeheader(); w.writerows(results)
    receipt={
        "schema":"AI_CORE_EVID_V2_8_4_BOUNDED_REAL_DIAGNOSTIC_RECEIPT_V1",
        "version":"V2.8.4",
        "status":status,
        "diagnostic_date":DATE,
        "candidate_rows":len(rows),
        "selected_count":len(selected),
        "successful_filings":success,
        "blocked_filings":blocked,
        "selection_rule":"SHA256(announcement_id)_ASC_FIRST_4",
        "results_file":str(csv_path),
        "results_file_sha256":te.sha_file(csv_path),
        "classification_effect":"DEVELOPMENT_DIAGNOSTIC_ONLY",
        "formal_E_layer_state_changes":False,
        "prospective_backfill":False,
        "price_or_return_data_consumed":False,
    }
    receipt["receipt_sha256"]=stable_sha256(receipt)
    rp=out_dir/"V2.8.4_BOUNDED_REAL_DIAGNOSTIC_RECEIPT.json"
    rp.write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(receipt,ensure_ascii=False,indent=2))
    print(json.dumps(results,ensure_ascii=False,indent=2))
    if success==0:
        raise SystemExit(2)

def self_test():
    rows=[
        {"announcement_id":"2","adjunct_url":"a"},
        {"announcement_id":"1","adjunct_url":"b"},
        {"announcement_id":"4","adjunct_url":"c"},
        {"announcement_id":"3","adjunct_url":"d"},
        {"announcement_id":"5","adjunct_url":"e"},
    ]
    a=select_candidates(rows,4)
    b=select_candidates(list(reversed(rows)),4)
    tests=[
        {"name":"D01_selection_size","pass":len(a)==4},
        {"name":"D02_order_invariant","pass":[x["announcement_id"] for x in a]==[x["announcement_id"] for x in b]},
        {"name":"D03_selection_hash_sorted","pass":[deterministic_key(x["announcement_id"]) for x in a]==sorted(deterministic_key(x["announcement_id"]) for x in rows)[:4]},
        {"name":"D04_fixed_date","pass":DATE=="2026-08-31"},
        {"name":"D05_max_sample_four","pass":MAX_SAMPLE==4},
    ]
    result={"schema":"AI_CORE_EVID_V2_8_4_BOUNDED_REAL_DIAGNOSTIC_SELFTEST_V1",
            "tests":tests,"passed":sum(x["pass"] for x in tests),"total":len(tests),
            "all_pass":all(x["pass"] for x in tests)}
    result["receipt_sha256"]=stable_sha256(result)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    if not result["all_pass"]: raise SystemExit(2)

def main():
    ap=argparse.ArgumentParser()
    sub=ap.add_subparsers(dest="cmd",required=True)
    sub.add_parser("self-test")
    r=sub.add_parser("run")
    r.add_argument("--out",default="v284_real_diagnostic")
    a=ap.parse_args()
    if a.cmd=="self-test": self_test()
    else: run(Path(a.out))

if __name__=="__main__":
    main()
