from __future__ import annotations

import csv
import hashlib
import json
import re
from datetime import date
from pathlib import Path

INTERVALS=Path("evidence/V2.8.1_PIT_MEMBERSHIP_INTERVALS.csv")
EXPECTED_SHA="52087fa1e68577fae214f8fa18f1b20a0b30f41b6b6bf5592327c25c2800cfc1"
OUT=Path("v285_sample")
START=date(2023,1,1)
END=date(2024,12,31)

def sha_file(path:Path)->str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""):
            h.update(b)
    return h.hexdigest()

def sample_key(cid:str)->tuple[str,int]:
    h=hashlib.sha256(cid.encode()).hexdigest()
    return h,int(h[:8],16)%5

def intersects(r:dict)->bool:
    ld=date.fromisoformat(r["official_list_date"])
    raw=str(r.get("official_delist_date") or "").strip()
    dd=date.fromisoformat(raw) if raw else None
    return ld<=END and (dd is None or dd>START)

def main():
    if sha_file(INTERVALS)!=EXPECTED_SHA:
        raise RuntimeError("PIT_INTERVAL_SHA_MISMATCH")
    rows=list(csv.DictReader(INTERVALS.read_text(encoding="utf-8").splitlines()))
    if len(rows)!=5554:
        raise RuntimeError(f"PIT_INTERVAL_COUNT_MISMATCH:{len(rows)}")
    frame=[]
    sample=[]
    for r in rows:
        cid=str(r["canonical_security_id"])
        if not re.fullmatch(r"(SSE|SZSE):\d{6}",cid):
            raise RuntimeError(f"INVALID_CANONICAL_ID:{cid}")
        if not intersects(r):
            continue
        h,m=sample_key(cid)
        x={
            "canonical_security_id":cid,
            "exchange":r["exchange"],
            "security_code":r["security_code"],
            "official_list_date":r["official_list_date"],
            "official_delist_date":r.get("official_delist_date",""),
            "baostock_code":("sh." if r["exchange"]=="SSE" else "sz.")+r["security_code"],
            "sha256_identity":h,
            "sample_mod5":m,
        }
        frame.append(x)
        if m==0:
            sample.append(x)
    frame.sort(key=lambda x:x["canonical_security_id"])
    sample.sort(key=lambda x:x["canonical_security_id"])
    if len({x["canonical_security_id"] for x in sample})!=len(sample):
        raise RuntimeError("SAMPLE_DUPLICATE_ID")
    if not (800<=len(sample)<=1300):
        raise RuntimeError(f"SAMPLE_COUNT_IMPLAUSIBLE:{len(sample)}")

    OUT.mkdir(parents=True,exist_ok=True)
    p=OUT/"V2.8.5_BACKWARD_HOLDOUT_SAMPLE_MANIFEST.csv"
    fields=list(sample[0].keys())
    with p.open("w",encoding="utf-8",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,lineterminator="\n")
        w.writeheader(); w.writerows(sample)
    ids=[x["canonical_security_id"] for x in sample]
    set_hash=hashlib.sha256(("\n".join(ids)+"\n").encode()).hexdigest()
    receipt={
        "schema":"AI_CORE_EVID_V2_8_5_BACKWARD_HOLDOUT_SAMPLE_RECEIPT_V1",
        "version":"V2.8.5",
        "status":"PASS",
        "membership_interval_rows":len(rows),
        "holdout_intersecting_frame_count":len(frame),
        "sample_rule":"int(SHA256(canonical_security_id)[0:8],16) mod 5 == 0",
        "sample_count":len(sample),
        "sample_fraction_of_frame":len(sample)/len(frame),
        "sse_count":sum(x["exchange"]=="SSE" for x in sample),
        "szse_count":sum(x["exchange"]=="SZSE" for x in sample),
        "canonical_sorted_newline_sha256":set_hash,
        "manifest_file":str(p),
        "manifest_sha256":sha_file(p),
        "holdout_price_rows_read":False,
        "replacement_after_download_failure":False,
    }
    receipt["receipt_sha256"]=hashlib.sha256(
        json.dumps(receipt,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()
    ).hexdigest()
    rp=OUT/"V2.8.5_BACKWARD_HOLDOUT_SAMPLE_RECEIPT.json"
    rp.write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(receipt,ensure_ascii=False,indent=2))

if __name__=="__main__":
    main()
