from __future__ import annotations

import csv, hashlib, json, re
from datetime import date
from pathlib import Path

INTERVALS=Path("evidence/V2.8.1_PIT_MEMBERSHIP_INTERVALS.csv")
EXPECTED_SHA="52087fa1e68577fae214f8fa18f1b20a0b30f41b6b6bf5592327c25c2800cfc1"
OUT=Path("v286_fold1")
START=date(2023,1,1)
END=date(2024,12,31)
TARGET_FOLD=1

def sha_file(path:Path)->str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""):
            h.update(b)
    return h.hexdigest()

def fold(cid:str)->tuple[str,int]:
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
    frame=[]; sample=[]; counts={i:0 for i in range(5)}
    for r in rows:
        cid=str(r["canonical_security_id"])
        if not re.fullmatch(r"(SSE|SZSE):\d{6}",cid):
            raise RuntimeError(f"INVALID_CANONICAL_ID:{cid}")
        if not intersects(r): continue
        h,m=fold(cid); counts[m]+=1
        x={
            "canonical_security_id":cid,
            "exchange":r["exchange"],
            "security_code":r["security_code"],
            "official_list_date":r["official_list_date"],
            "official_delist_date":r.get("official_delist_date",""),
            "baostock_code":("sh." if r["exchange"]=="SSE" else "sz.")+r["security_code"],
            "sha256_identity":h,
            "identity_fold_mod5":m,
        }
        frame.append(x)
        if m==TARGET_FOLD: sample.append(x)
    frame.sort(key=lambda x:x["canonical_security_id"])
    sample.sort(key=lambda x:x["canonical_security_id"])
    if len(frame)!=5218:
        raise RuntimeError(f"FRAME_COUNT_MISMATCH:{len(frame)}")
    if sum(counts.values())!=len(frame):
        raise RuntimeError("FOLD_COUNT_SUM_MISMATCH")
    if len({x["canonical_security_id"] for x in sample})!=len(sample):
        raise RuntimeError("FOLD1_DUPLICATE")
    if any(x["identity_fold_mod5"]!=1 for x in sample):
        raise RuntimeError("FOLD1_ASSIGNMENT_DRIFT")

    OUT.mkdir(parents=True,exist_ok=True)
    p=OUT/"V2.8.6_FOLD1_MECHANISM_REPLICATION_MANIFEST.csv"
    fields=list(sample[0].keys())
    with p.open("w",encoding="utf-8",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,lineterminator="\n"); w.writeheader(); w.writerows(sample)
    ids=[x["canonical_security_id"] for x in sample]
    receipt={
        "schema":"AI_CORE_EVID_V2_8_6_FOLD1_MANIFEST_RECEIPT_V1",
        "version":"V2.8.6",
        "status":"PASS",
        "frame_count":len(frame),
        "fold_counts":{str(k):v for k,v in counts.items()},
        "target_fold":1,
        "fold1_count":len(sample),
        "sse_count":sum(x["exchange"]=="SSE" for x in sample),
        "szse_count":sum(x["exchange"]=="SZSE" for x in sample),
        "canonical_sorted_newline_sha256":hashlib.sha256(("\n".join(ids)+"\n").encode()).hexdigest(),
        "manifest_file":p.name,
        "manifest_sha256":sha_file(p),
        "fold0_overlap_count":0,
        "price_rows_read":False,
        "fold2_3_4_price_rows_read":False
    }
    rp=OUT/"V2.8.6_FOLD1_MANIFEST_RECEIPT.json"
    rp.write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(receipt,ensure_ascii=False,indent=2))

if __name__=="__main__":
    main()
