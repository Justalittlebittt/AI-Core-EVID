from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path

import pyarrow.parquet as pq

SAMPLE=Path("evidence/V2.8.6_FOLD1_MECHANISM_REPLICATION_MANIFEST.csv")
SAMPLE_SHA="fe15777a0a3a131b58288454a0e3023503bd80ac6a22f20a2e50c45a4deed38a"
MAX_GIT_OBJECT_BYTES=95_000_000

def sha_file(path:Path)->str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""):
            h.update(b)
    return h.hexdigest()

def stable_sha(obj)->str:
    return hashlib.sha256(
        json.dumps(obj,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()
    ).hexdigest()

def bucket(cid:str)->int:
    return int(hashlib.sha256(cid.encode()).hexdigest()[:8],16)%8

def load_sample()->dict[str,dict]:
    if sha_file(SAMPLE)!=SAMPLE_SHA:
        raise RuntimeError("SAMPLE_SHA_MISMATCH")
    rows=list(csv.DictReader(SAMPLE.read_text(encoding="utf-8").splitlines()))
    if len(rows)!=1058:
        raise RuntimeError("SAMPLE_COUNT_MISMATCH")
    return {r["canonical_security_id"]:r for r in rows}

def read_csv(path:Path)->list[dict]:
    return list(csv.DictReader(path.read_text(encoding="utf-8").splitlines()))

def validate_bucket(root:Path,b:int,sample:dict[str,dict])->tuple[dict,list[dict]]:
    rp=root/f"V2.8.6_FOLD1_BAOSTOCK_BUCKET_{b}_RECEIPT.json"
    if not rp.exists():
        raise RuntimeError(f"BUCKET_RECEIPT_MISSING:{b}")
    rec=json.loads(rp.read_text(encoding="utf-8"))
    if rec.get("status")!="PASS" or int(rec.get("bucket",-1))!=b:
        raise RuntimeError(f"BUCKET_RECEIPT_NOT_PASS:{b}")

    mp=root/rec["query_manifest_file"]
    pp=root/rec["parquet_file"]
    if not mp.exists() or sha_file(mp)!=rec["query_manifest_sha256"]:
        raise RuntimeError(f"BUCKET_MANIFEST_INTEGRITY:{b}")
    if not pp.exists() or sha_file(pp)!=rec["parquet_sha256"]:
        raise RuntimeError(f"BUCKET_PARQUET_INTEGRITY:{b}")
    if pp.stat().st_size>=MAX_GIT_OBJECT_BYTES:
        raise RuntimeError(f"BUCKET_PARQUET_TOO_LARGE:{b}")

    manifest=read_csv(mp)
    expected={cid for cid in sample if bucket(cid)==b}
    got={r["canonical_security_id"] for r in manifest}
    if got!=expected or len(manifest)!=len(expected):
        raise RuntimeError(f"BUCKET_SAMPLE_SET_MISMATCH:{b}:{len(got)}:{len(expected)}")
    if int(rec["bucket_sample_count"])!=len(expected):
        raise RuntimeError(f"BUCKET_SAMPLE_COUNT_MISMATCH:{b}")

    for r in manifest:
        if int(r["sample_bucket"])!=b:
            raise RuntimeError(f"BUCKET_MANIFEST_BUCKET_DRIFT:{b}:{r['canonical_security_id']}")
        if r["status"] not in {"SUCCESS","ZERO_ROWS"}:
            raise RuntimeError(f"BUCKET_MANIFEST_STATUS:{b}:{r['canonical_security_id']}")
        f3=int(r.get("flag3_rows") or 0)
        xc=int(r.get("flag3_crosschecked_rows") or 0)
        if f3!=xc:
            raise RuntimeError(f"FLAG3_NOT_FULLY_CROSSCHECKED:{r['canonical_security_id']}:{f3}:{xc}")

    table=pq.read_table(pp,columns=["canonical_security_id","sample_bucket"])
    cids=table.column("canonical_security_id").to_pylist()
    buckets=table.column("sample_bucket").to_pylist()
    if len(cids)!=int(rec["stock_rows"]):
        raise RuntimeError(f"BUCKET_PARQUET_ROWCOUNT:{b}")
    if any(int(x)!=b for x in buckets):
        raise RuntimeError(f"BUCKET_PARQUET_BUCKET_DRIFT:{b}")
    counts=Counter(cids)
    manifest_counts={r["canonical_security_id"]:int(r["rows"]) for r in manifest}
    if counts!={k:v for k,v in manifest_counts.items() if v>0}:
        raise RuntimeError(f"BUCKET_PARQUET_SYMBOL_ROWCOUNT_MISMATCH:{b}")
    if set(counts)-expected:
        raise RuntimeError(f"BUCKET_PARQUET_NON_SAMPLE_SECURITY:{b}")
    return rec,manifest

def validate_benchmark(root:Path)->dict:
    rp=root/"V2.8.5_BAOSTOCK_BENCHMARK_RECEIPT.json"
    if not rp.exists():
        raise RuntimeError("BENCHMARK_RECEIPT_MISSING")
    rec=json.loads(rp.read_text(encoding="utf-8"))
    if rec.get("status") not in {"PASS","SUCCESS"}:
        raise RuntimeError("BENCHMARK_NOT_PASS")
    pp=root/rec["file"]
    if not pp.exists() or sha_file(pp)!=rec["parquet_sha256"]:
        raise RuntimeError("BENCHMARK_PARQUET_INTEGRITY")
    if pp.stat().st_size>=MAX_GIT_OBJECT_BYTES:
        raise RuntimeError("BENCHMARK_PARQUET_TOO_LARGE")
    table=pq.read_table(pp,columns=["canonical_security_id","baostock_code","adjustflag"])
    if table.num_rows!=int(rec["rows"]):
        raise RuntimeError("BENCHMARK_ROWCOUNT_MISMATCH")
    cids=set(table.column("canonical_security_id").to_pylist())
    codes=set(table.column("baostock_code").to_pylist())
    flags=set(table.column("adjustflag").to_pylist())
    if cids!={"BENCHMARK:CSI300"} or codes!={"sh.000300"} or flags!={"3"}:
        raise RuntimeError("BENCHMARK_IDENTITY_OR_FLAG_BLOCK")
    return rec

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--artifact-root",required=True)
    ap.add_argument("--out",required=True)
    a=ap.parse_args()
    root=Path(a.artifact_root); out=Path(a.out); out.mkdir(parents=True,exist_ok=True)
    sample=load_sample()

    all_manifest=[]; parts=[]
    zero=[]; success=0; stock_rows=0; trading_rows=0; flag3_total=0; flag3_xc=0
    for b in range(8):
        rec,manifest=validate_bucket(root,b,sample)
        all_manifest.extend(manifest)
        zero.extend(rec["zero_row_canonical_ids"])
        success+=int(rec["successful_nonzero_symbols"])
        stock_rows+=int(rec["stock_rows"])
        flag3_total+=int(rec["flag3_rows_total"])
        flag3_xc+=int(rec["flag3_crosschecked_rows_total"])
        parts.append({
            "bucket":b,
            "file":rec["parquet_file"],
            "rows":int(rec["stock_rows"]),
            "bytes":int(rec["parquet_bytes"]),
            "sha256":rec["parquet_sha256"],
            "bucket_receipt":f"V2.8.6_FOLD1_BAOSTOCK_BUCKET_{b}_RECEIPT.json",
            "bucket_receipt_sha256":rec["receipt_sha256"],
        })
        trading_rows+=sum(int(r["trading_rows"]) for r in manifest)

    ids=[r["canonical_security_id"] for r in all_manifest]
    if len(all_manifest)!=1058 or len(ids)!=len(set(ids)) or set(ids)!=set(sample):
        raise RuntimeError("MERGED_SAMPLE_COVERAGE_BLOCK")
    if flag3_total!=flag3_xc:
        raise RuntimeError("MERGED_FLAG3_CROSSCHECK_BLOCK")

    all_manifest.sort(key=lambda r:r["canonical_security_id"])
    mp=out/"V2.8.6_FOLD1_BAOSTOCK_QUERY_MANIFEST.csv"
    fields=list(all_manifest[0].keys())
    with mp.open("w",encoding="utf-8",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,lineterminator="\n")
        w.writeheader(); w.writerows(all_manifest)

    bench=validate_benchmark(root)
    receipt={
        "schema":"AI_CORE_EVID_V2_8_6_FOLD1_SOURCE_SNAPSHOT_RECEIPT_V1",
        "version":"V2.8.6",
        "status":"PASS",
        "provider":"BaoStock",
        "baostock_version":"0.9.4",
        "retrieval_start":"2022-09-01",
        "retrieval_end":"2024-12-31",
        "sample_manifest_sha256":SAMPLE_SHA,
        "sample_count":1058,
        "successful_nonzero_symbols":success,
        "zero_row_symbols":len(zero),
        "zero_row_canonical_ids":sorted(zero),
        "persistent_query_errors":0,
        "stock_rows":stock_rows,
        "stock_trading_rows":trading_rows,
        "flag3_rows_total":flag3_total,
        "flag3_crosschecked_rows_total":flag3_xc,
        "stock_partitions":parts,
        "benchmark":{
            "status":"PASS",
            "rows":int(bench["rows"]),
            "trading_rows":int(bench["trading_rows"]),
            "min_date":bench["min_date"],
            "max_date":bench["max_date"],
            "file":bench["file"],
            "bytes":int(bench["bytes"]),
            "parquet_sha256":bench["parquet_sha256"],
            "benchmark_receipt":"V2.8.5_BAOSTOCK_BENCHMARK_RECEIPT.json",
            "benchmark_receipt_sha256":bench["receipt_sha256"],
        },
        "query_manifest_file":mp.name,
        "query_manifest_sha256":sha_file(mp),
        "acquisition_architecture":"8 deterministic stock buckets plus separate benchmark; bounded max-parallel=4",
        "factor_or_forward_return_computed":False,
        "holdout_outcome_inspected":False,
        "sample_replacement_used":False,
    }
    receipt["receipt_sha256"]=stable_sha(receipt)
    rp=out/"V2.8.6_FOLD1_SOURCE_SNAPSHOT_RECEIPT.json"
    rp.write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(receipt,ensure_ascii=False,indent=2))

if __name__=="__main__":
    main()
