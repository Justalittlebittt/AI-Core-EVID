from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

import pyarrow.parquet as pq

SOURCE_RECEIPT=Path("evidence/V2.8.5_BAOSTOCK_HOLDOUT_SOURCE_SNAPSHOT_RECEIPT.json")
SOURCE_DIR=Path("evidence/v285_holdout_source")
SAMPLE=Path("evidence/V2.8.5_BACKWARD_HOLDOUT_SAMPLE_MANIFEST.csv")
SAMPLE_SHA="199864ece6c02f3257647d59ba63fe261a7b478a2525b7ed8042bbf475a9fe48"
CALENDAR=Path("evidence/V2.8.5_JOINT_A_SHARE_TRADING_CALENDAR_2023_2024.json")
START="2022-09-01"
END="2024-12-31"

def sha_file(path:Path)->str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""):
            h.update(b)
    return h.hexdigest()

def bucket(cid:str)->int:
    return int(hashlib.sha256(cid.encode()).hexdigest()[:8],16)%8

def stable_sha(obj)->str:
    return hashlib.sha256(
        json.dumps(obj,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()
    ).hexdigest()

def validate(out:Path):
    if sha_file(SAMPLE)!=SAMPLE_SHA:
        raise RuntimeError("SAMPLE_SHA_BLOCKED")
    sample=list(csv.DictReader(SAMPLE.read_text(encoding="utf-8").splitlines()))
    sample_ids={r["canonical_security_id"] for r in sample}
    if len(sample)!=1031 or len(sample_ids)!=1031:
        raise RuntimeError("SAMPLE_IDENTITY_BLOCKED")

    rec=json.loads(SOURCE_RECEIPT.read_text(encoding="utf-8"))
    if rec.get("status")!="PASS" or rec.get("sample_count")!=1031:
        raise RuntimeError("SOURCE_RECEIPT_STATUS_BLOCKED")
    if rec.get("factor_or_forward_return_computed") is not False or rec.get("holdout_outcome_inspected") is not False:
        raise RuntimeError("SOURCE_RECEIPT_LEAKAGE_FLAG_BLOCKED")
    if rec.get("sample_replacement_used") is not False:
        raise RuntimeError("SOURCE_SAMPLE_REPLACEMENT_BLOCKED")

    mp=SOURCE_DIR/rec["query_manifest_file"]
    if not mp.exists() or sha_file(mp)!=rec["query_manifest_sha256"]:
        raise RuntimeError("QUERY_MANIFEST_HASH_BLOCKED")
    manifest=list(csv.DictReader(mp.read_text(encoding="utf-8").splitlines()))
    mids=[r["canonical_security_id"] for r in manifest]
    if len(manifest)!=1031 or set(mids)!=sample_ids or len(mids)!=len(set(mids)):
        raise RuntimeError("QUERY_MANIFEST_IDENTITY_BLOCKED")
    if set(r["status"] for r in manifest)-{"SUCCESS","ZERO_ROWS"}:
        raise RuntimeError("QUERY_MANIFEST_STATUS_BLOCKED")

    expected_rows={r["canonical_security_id"]:int(r["rows"]) for r in manifest}
    expected_raw_sha={r["canonical_security_id"]:r["rows_sha256"] for r in manifest}
    observed_rows={cid:0 for cid in sample_ids}
    raw_by={cid:[] for cid in sample_ids}
    raw_fields=["date","code","open","high","low","close","preclose","volume","amount","adjustflag","tradestatus"]
    total=0
    part_receipts=[]
    for pr in sorted(rec["stock_partitions"],key=lambda x:int(x["bucket"])):
        b=int(pr["bucket"])
        fp=SOURCE_DIR/pr["file"]
        if not fp.exists() or sha_file(fp)!=pr["sha256"] or fp.stat().st_size!=int(pr["bytes"]):
            raise RuntimeError(f"PARTITION_HASH_BLOCKED:{b}")
        t=pq.read_table(fp)
        cols=t.column_names
        required={"canonical_security_id","baostock_code","sample_bucket","date","code","adjustflag","tradestatus"}
        if not required.issubset(cols):
            raise RuntimeError(f"PARTITION_SCHEMA_BLOCKED:{b}")
        data=t.select(list(required)).to_pylist()
        seen=set()
        for r in data:
            cid=str(r["canonical_security_id"])
            d=str(r["date"])
            if cid not in sample_ids or int(r["sample_bucket"])!=bucket(cid) or bucket(cid)!=b:
                raise RuntimeError(f"PARTITION_IDENTITY_BUCKET_BLOCKED:{cid}")
            if str(r["adjustflag"])!="1" or str(r["code"])!=str(r["baostock_code"]):
                raise RuntimeError(f"PARTITION_SOURCE_IDENTITY_BLOCKED:{cid}")
            if not (START<=d<=END) or str(r["tradestatus"]) not in {"0","1"}:
                raise RuntimeError(f"PARTITION_DATE_STATUS_BLOCKED:{cid}:{d}")
            key=(cid,d)
            if key in seen:
                raise RuntimeError(f"PARTITION_DUPLICATE_STOCK_DATE:{cid}:{d}")
            seen.add(key)
            observed_rows[cid]+=1
            raw_by[cid].append({k:str(r.get(k) if r.get(k) is not None else "") for k in raw_fields})
        total+=len(data)
        if len(data)!=int(pr["rows"]):
            raise RuntimeError(f"PARTITION_ROW_COUNT_BLOCKED:{b}")
        part_receipts.append({"bucket":b,"rows":len(data),"sha256":pr["sha256"]})

    if total!=int(rec["stock_rows"]):
        raise RuntimeError("TOTAL_STOCK_ROWS_BLOCKED")
    mismatches=[cid for cid in sample_ids if observed_rows[cid]!=expected_rows[cid]]
    if mismatches:
        raise RuntimeError(f"PER_SYMBOL_ROW_COUNT_BLOCKED:{mismatches[:10]}")
    raw_hash_mismatch=[]
    for cid in sorted(sample_ids):
        rows=sorted(raw_by[cid],key=lambda r:r["date"])
        if stable_sha(rows)!=expected_raw_sha[cid]:
            raw_hash_mismatch.append(cid)
    if raw_hash_mismatch:
        raise RuntimeError(f"PER_SYMBOL_RAW_HASH_BLOCKED:{raw_hash_mismatch[:10]}")

    bp=SOURCE_DIR/rec["benchmark"]["file"]
    if not bp.exists() or sha_file(bp)!=rec["benchmark"]["parquet_sha256"]:
        raise RuntimeError("BENCHMARK_HASH_BLOCKED")
    bt=pq.read_table(bp).to_pylist()
    if len(bt)!=int(rec["benchmark"]["rows"]):
        raise RuntimeError("BENCHMARK_ROW_COUNT_BLOCKED")
    bdates=[]
    seen_b=set()
    for r in bt:
        d=str(r["date"])
        if r["canonical_security_id"]!="BENCHMARK:CSI300" or r["baostock_code"]!="sh.000300":
            raise RuntimeError("BENCHMARK_IDENTITY_BLOCKED")
        if str(r["adjustflag"])!="3" or str(r["tradestatus"]) not in {"0","1"}:
            raise RuntimeError("BENCHMARK_SEMANTICS_BLOCKED")
        if d in seen_b:
            raise RuntimeError("BENCHMARK_DUPLICATE_DATE")
        seen_b.add(d); bdates.append(d)
    cal=json.loads(CALENDAR.read_text(encoding="utf-8"))["trading_dates"]
    missing=[d for d in cal if d not in seen_b]
    if missing:
        raise RuntimeError(f"BENCHMARK_MISSING_OFFICIAL_JOINT_DATES:{missing[:10]}")

    zero_manifest=sorted(r["canonical_security_id"] for r in manifest if r["status"]=="ZERO_ROWS")
    if zero_manifest!=sorted(rec.get("zero_row_canonical_ids") or []):
        raise RuntimeError("ZERO_ROW_LIST_BLOCKED")

    result={
      "schema":"AI_CORE_EVID_V2_8_5_HOLDOUT_SOURCE_INTEGRITY_VALIDATION_RECEIPT_V1",
      "version":"V2.8.5","status":"PASS",
      "sample_count":1031,
      "successful_nonzero_symbols":sum(r["status"]=="SUCCESS" for r in manifest),
      "zero_row_symbols":len(zero_manifest),
      "stock_rows":total,
      "per_symbol_raw_hashes_revalidated":1031,
      "partitions":part_receipts,
      "benchmark_rows":len(bt),
      "official_joint_dates_required":len(cal),
      "official_joint_dates_missing_from_benchmark":0,
      "factor_or_forward_return_computed":False,
      "holdout_outcome_inspected":False,
      "sample_replacement_used":False
    }
    result["receipt_sha256"]=hashlib.sha256(
      json.dumps(result,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()
    ).hexdigest()
    out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(result,ensure_ascii=False,indent=2))

def self_test():
    tests=[
      {"name":"I01_bucket_deterministic","pass":bucket("SZSE:300634")==bucket("SZSE:300634")},
      {"name":"I02_bucket_range","pass":all(0<=bucket(f"SSE:{i:06d}")<8 for i in range(20))},
      {"name":"I03_frozen_sample_sha","pass":len(SAMPLE_SHA)==64},
      {"name":"I04_holdout_range_frozen","pass":START=="2022-09-01" and END=="2024-12-31"},
      {"name":"I05_stable_raw_hash","pass":stable_sha([{"date":"2023-01-03","close":"1"}])==stable_sha([{"close":"1","date":"2023-01-03"}])},
    ]
    out={"schema":"AI_CORE_EVID_V2_8_5_SOURCE_INTEGRITY_VALIDATOR_SELFTEST_V2",
         "tests":tests,"passed":sum(x["pass"] for x in tests),"total":len(tests),"all_pass":all(x["pass"] for x in tests)}
    print(json.dumps(out,ensure_ascii=False,indent=2))
    if not out["all_pass"]: raise SystemExit(2)

def main():
    ap=argparse.ArgumentParser()
    sub=ap.add_subparsers(dest="cmd",required=True)
    sub.add_parser("self-test")
    v=sub.add_parser("validate")
    v.add_argument("--out",default="evidence/V2.8.5_HOLDOUT_SOURCE_INTEGRITY_VALIDATION_RECEIPT.json")
    a=ap.parse_args()
    if a.cmd=="self-test": self_test()
    else: validate(Path(a.out))

if __name__=="__main__":
    main()
