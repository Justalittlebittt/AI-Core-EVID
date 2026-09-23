from __future__ import annotations
import csv,hashlib,json,re
from datetime import date
from pathlib import Path

INTERVALS=Path("evidence/V2.8.1_PIT_MEMBERSHIP_INTERVALS.csv")
EXPECTED_SHA="52087fa1e68577fae214f8fa18f1b20a0b30f41b6b6bf5592327c25c2800cfc1"
OUT=Path("v287_fold2")
START=date(2023,1,1); END=date(2024,12,31); TARGET=2

def sha_file(p):
    h=hashlib.sha256()
    with Path(p).open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""): h.update(b)
    return h.hexdigest()

def fold(cid):
    h=hashlib.sha256(cid.encode()).hexdigest()
    return h,int(h[:8],16)%5

def intersects(r):
    ld=date.fromisoformat(r["official_list_date"])
    raw=str(r.get("official_delist_date") or "").strip()
    dd=date.fromisoformat(raw) if raw else None
    return ld<=END and (dd is None or dd>START)

def main():
    if sha_file(INTERVALS)!=EXPECTED_SHA: raise RuntimeError("PIT_INTERVAL_SHA_BLOCK")
    rows=list(csv.DictReader(INTERVALS.read_text(encoding="utf-8").splitlines()))
    frame=[]; sample=[]; counts={i:0 for i in range(5)}
    for r in rows:
        cid=str(r["canonical_security_id"])
        if not re.fullmatch(r"(SSE|SZSE):\d{6}",cid): raise RuntimeError(f"CID:{cid}")
        if not intersects(r): continue
        h,m=fold(cid); counts[m]+=1
        x={
          "canonical_security_id":cid,"exchange":r["exchange"],"security_code":r["security_code"],
          "official_list_date":r["official_list_date"],"official_delist_date":r.get("official_delist_date",""),
          "source_symbol":("sh" if r["exchange"]=="SSE" else "sz")+r["security_code"],
          "sha256_identity":h,"identity_fold_mod5":m
        }
        frame.append(x)
        if m==TARGET: sample.append(x)
    sample.sort(key=lambda x:x["canonical_security_id"])
    if len(frame)!=5218 or counts!={0:1031,1:1058,2:1048,3:1039,4:1042}: raise RuntimeError(f"FOLD_FRAME_DRIFT:{len(frame)}:{counts}")
    if len(sample)!=1048 or len({x["canonical_security_id"] for x in sample})!=1048: raise RuntimeError("FOLD2_COUNT_BLOCK")
    OUT.mkdir(parents=True,exist_ok=True)
    p=OUT/"V2.8.7_FOLD2_SETUP_SHAPE_MANIFEST.csv"
    fields=list(sample[0].keys())
    with p.open("w",encoding="utf-8",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,lineterminator="\n"); w.writeheader(); w.writerows(sample)
    ids=[x["canonical_security_id"] for x in sample]
    rec={
      "schema":"AI_CORE_EVID_V2_8_7_FOLD2_SETUP_SHAPE_MANIFEST_RECEIPT_V1",
      "version":"V2.8.7","status":"PASS","target_fold":2,"frame_count":5218,
      "fold_counts":{str(k):v for k,v in counts.items()},"fold2_count":1048,
      "sse_count":sum(x["exchange"]=="SSE" for x in sample),"szse_count":sum(x["exchange"]=="SZSE" for x in sample),
      "manifest_file":p.name,"manifest_sha256":sha_file(p),
      "canonical_sorted_newline_sha256":hashlib.sha256(("\n".join(ids)+"\n").encode()).hexdigest(),
      "fold0_1_overlap_count":0,"price_rows_read":False,"fold3_4_price_rows_read":False
    }
    (OUT/"V2.8.7_FOLD2_SETUP_SHAPE_MANIFEST_RECEIPT.json").write_text(json.dumps(rec,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(rec,ensure_ascii=False,indent=2))

if __name__=="__main__": main()
