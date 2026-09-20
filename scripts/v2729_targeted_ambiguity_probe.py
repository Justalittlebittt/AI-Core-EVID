from __future__ import annotations
import csv, hashlib, json
from pathlib import Path
from playwright.sync_api import sync_playwright

CAT=Path("evidence/V2.7.28_PERIODIC_CATALOG.csv")
OUT=Path("v2729_ambiguity_probe"); RAW=OUT/"raw"
OUT.mkdir(exist_ok=True); RAW.mkdir(parents=True,exist_ok=True)
TARGETS={
"SSE:600119","SSE:600259","SSE:600611","SSE:600821","SSE:600847",
"SSE:600860","SSE:601992","SSE:603203","SZSE:300188"
}
PIT="2026-09-17"

def sha(b:bytes): return hashlib.sha256(b).hexdigest()

def full_candidate(r):
    return (
      r["canonical_security_id"] in TARGETS and
      r.get("report_period_end")=="2026-06-30" and
      r.get("announcement_date_beijing","") < PIT and
      r.get("is_summary")=="false" and
      r.get("is_english")=="false"
    )

def main():
    rows=list(csv.DictReader(CAT.open(encoding="utf-8")))
    groups={cid:[] for cid in TARGETS}
    for r in rows:
        if full_candidate(r):
            groups[r["canonical_security_id"]].append(r)
    receipt={"schema":"AI_CORE_EVID_V2_7_29_TARGETED_AMBIGUITY_MATERIALIZATION_V1","groups":{}}
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True)
        ctx=browser.new_context(
          user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/153 Safari/537.36",
          locale="zh-CN")
        for cid in sorted(TARGETS):
            cands=groups[cid]
            # Only latest disclosure day for latest period participates in ambiguity.
            maxd=max(r["announcement_date_beijing"] for r in cands)
            cands=[r for r in cands if r["announcement_date_beijing"]==maxd]
            out=[]
            for r in cands:
                adj=r["adjunct_url"].lstrip("/")
                url="https://static.cninfo.com.cn/"+adj
                resp=ctx.request.get(url,headers={"Referer":"https://www.cninfo.com.cn/"},timeout=90000)
                b=resp.body()
                off=b[:2048].find(b"%PDF-")
                rec={
                  "announcement_id":r["announcement_id"],
                  "title":r["announcement_title"],
                  "disclosure_date":r["announcement_date_beijing"],
                  "adjunct_url":r["adjunct_url"],
                  "url":url,
                  "status":resp.status,
                  "content_type":resp.headers.get("content-type"),
                  "bytes":len(b),
                  "sha256":sha(b),
                  "pdf_header_offset":off
                }
                out.append(rec)
                p=RAW/f"{cid.replace(':','_')}_{r['announcement_id']}.pdf"
                if resp.status==200 and off>=0:
                    p.write_bytes(b)
                else:
                    (RAW/f"{cid.replace(':','_')}_{r['announcement_id']}.bin").write_bytes(b)
            valid=all(x["status"]==200 and x["pdf_header_offset"]>=0 for x in out)
            hashes={x["sha256"] for x in out} if valid else set()
            classification=(
              "BYTE_IDENTICAL_DUPLICATE" if valid and len(hashes)==1
              else "CONTENT_DISTINCT_AMBIGUITY" if valid
              else "MATERIALIZATION_BLOCKED"
            )
            canonical=None
            if classification=="BYTE_IDENTICAL_DUPLICATE":
                canonical=sorted(out,key=lambda x:x["announcement_id"])[0]["announcement_id"]
            receipt["groups"][cid]={
              "candidate_count":len(out),
              "classification":classification,
              "canonical_representative_announcement_id":canonical,
              "candidates":out
            }
            print(cid,classification,flush=True)
        browser.close()
    counts={}
    for g in receipt["groups"].values():
        counts[g["classification"]]=counts.get(g["classification"],0)+1
    receipt["classification_counts"]=counts
    receipt["all_materialized"]=counts.get("MATERIALIZATION_BLOCKED",0)==0
    canonical=json.dumps(receipt,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()
    receipt["receipt_sha256"]=sha(canonical)
    (OUT/"V2.7.29_TARGETED_AMBIGUITY_RECEIPT.json").write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(receipt,ensure_ascii=False,indent=2))
    return 0

if __name__=="__main__": raise SystemExit(main())
