from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
from collections import Counter
from pathlib import Path

import pyarrow.parquet as pq

SAMPLE=Path("evidence/V2.8.6_FOLD1_MECHANISM_REPLICATION_MANIFEST.csv")
SAMPLE_SHA="fe15777a0a3a131b58288454a0e3023503bd80ac6a22f20a2e50c45a4deed38a"
BENCHMARK_SOURCE=Path("evidence/v285_holdout_source/V2.8.5_BAOSTOCK_CSI300.parquet")
BENCHMARK_SHA="1aee2f5af524e0f99f788166731d3c9ce3a862c6f1af9203b442f11f6d5fe272"
SHARD_COUNT=16
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

def shard(cid:str)->int:
    return int(hashlib.sha256(cid.encode()).hexdigest()[:8],16)%SHARD_COUNT

def load_sample()->dict[str,dict]:
    if sha_file(SAMPLE)!=SAMPLE_SHA:
        raise RuntimeError("SAMPLE_SHA_MISMATCH")
    rows=list(csv.DictReader(SAMPLE.read_text(encoding="utf-8").splitlines()))
    if len(rows)!=1058:
        raise RuntimeError("SAMPLE_COUNT_MISMATCH")
    return {r["canonical_security_id"]:r for r in rows}

def read_csv(path:Path)->list[dict]:
    return list(csv.DictReader(path.read_text(encoding="utf-8").splitlines()))

def validate_shard(root:Path,sid:int,sample:dict[str,dict])->tuple[dict,list[dict]]:
    rp=root/f"V2.8.6_FOLD1_SOURCE_SHARD_{sid}_RECEIPT.json"
    if not rp.exists():
        raise RuntimeError(f"SHARD_RECEIPT_MISSING:{sid}")
    rec=json.loads(rp.read_text(encoding="utf-8"))
    if rec.get("status")!="PASS" or int(rec.get("shard",-1))!=sid or int(rec.get("shard_count",0))!=SHARD_COUNT:
        raise RuntimeError(f"SHARD_RECEIPT_NOT_PASS:{sid}")
    mp=root/rec["query_manifest_file"]; pp=root/rec["parquet_file"]
    if not mp.exists() or sha_file(mp)!=rec["query_manifest_sha256"]:
        raise RuntimeError(f"SHARD_MANIFEST_INTEGRITY:{sid}")
    if not pp.exists() or sha_file(pp)!=rec["parquet_sha256"]:
        raise RuntimeError(f"SHARD_PARQUET_INTEGRITY:{sid}")
    if pp.stat().st_size>=MAX_GIT_OBJECT_BYTES:
        raise RuntimeError(f"SHARD_PARQUET_TOO_LARGE:{sid}")
    manifest=read_csv(mp)
    expected={cid for cid in sample if shard(cid)==sid}
    got={r["canonical_security_id"] for r in manifest}
    if got!=expected or len(manifest)!=len(expected):
        raise RuntimeError(f"SHARD_SAMPLE_SET_MISMATCH:{sid}:{len(got)}:{len(expected)}")
    if int(rec["shard_sample_count"])!=len(expected):
        raise RuntimeError(f"SHARD_SAMPLE_COUNT_MISMATCH:{sid}")
    for r in manifest:
        if int(r["acquisition_shard_mod16"])!=sid:
            raise RuntimeError(f"SHARD_MANIFEST_ASSIGNMENT_DRIFT:{sid}:{r['canonical_security_id']}")
        if r["status"] not in {"SUCCESS","ZERO_ROWS"}:
            raise RuntimeError(f"SHARD_MANIFEST_STATUS:{sid}:{r['canonical_security_id']}")
        f3=int(r.get("flag3_rows") or 0); xc=int(r.get("flag3_crosschecked_rows") or 0)
        if f3!=xc:
            raise RuntimeError(f"FLAG3_NOT_FULLY_CROSSCHECKED:{r['canonical_security_id']}:{f3}:{xc}")
    table=pq.read_table(pp,columns=["canonical_security_id","acquisition_shard_mod16"])
    cids=table.column("canonical_security_id").to_pylist()
    sids=table.column("acquisition_shard_mod16").to_pylist()
    if len(cids)!=int(rec["stock_rows"]):
        raise RuntimeError(f"SHARD_PARQUET_ROWCOUNT:{sid}")
    if any(int(x)!=sid for x in sids):
        raise RuntimeError(f"SHARD_PARQUET_ASSIGNMENT_DRIFT:{sid}")
    counts=Counter(cids)
    manifest_counts={r["canonical_security_id"]:int(r["rows"]) for r in manifest}
    if counts!={k:v for k,v in manifest_counts.items() if v>0}:
        raise RuntimeError(f"SHARD_PARQUET_SYMBOL_ROWCOUNT_MISMATCH:{sid}")
    return rec,manifest

def copy_and_validate_benchmark(out:Path)->dict:
    if not BENCHMARK_SOURCE.exists() or sha_file(BENCHMARK_SOURCE)!=BENCHMARK_SHA:
        raise RuntimeError("REUSED_BENCHMARK_INTEGRITY_BLOCK")
    table=pq.read_table(BENCHMARK_SOURCE,columns=["canonical_security_id","baostock_code","adjustflag","date"])
    if table.num_rows!=565:
        raise RuntimeError("REUSED_BENCHMARK_ROWCOUNT_BLOCK")
    if set(table.column("canonical_security_id").to_pylist())!={"BENCHMARK:CSI300"}:
        raise RuntimeError("REUSED_BENCHMARK_IDENTITY_BLOCK")
    if set(table.column("baostock_code").to_pylist())!={"sh.000300"}:
        raise RuntimeError("REUSED_BENCHMARK_CODE_BLOCK")
    if set(table.column("adjustflag").to_pylist())!={"3"}:
        raise RuntimeError("REUSED_BENCHMARK_FLAG_BLOCK")
    dates=table.column("date").to_pylist()
    target=out/"V2.8.6_FOLD1_BAOSTOCK_CSI300.parquet"
    shutil.copyfile(BENCHMARK_SOURCE,target)
    if sha_file(target)!=BENCHMARK_SHA:
        raise RuntimeError("REUSED_BENCHMARK_COPY_HASH_BLOCK")
    return {
        "status":"PASS",
        "rows":565,
        "trading_rows":565,
        "min_date":min(dates),
        "max_date":max(dates),
        "file":target.name,
        "bytes":target.stat().st_size,
        "parquet_sha256":BENCHMARK_SHA,
        "reused_from":"evidence/v285_holdout_source/V2.8.5_BAOSTOCK_CSI300.parquet"
    }

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--artifact-root",required=True)
    ap.add_argument("--out",required=True)
    a=ap.parse_args()
    root=Path(a.artifact_root); out=Path(a.out); out.mkdir(parents=True,exist_ok=True)
    sample=load_sample()
    all_manifest=[]; parts=[]; zero=[]; success=0; stock_rows=0; trading_rows=0; flag3_total=0; flag3_xc=0
    for sid in range(SHARD_COUNT):
        rec,manifest=validate_shard(root,sid,sample)
        all_manifest.extend(manifest)
        zero.extend(rec["zero_row_canonical_ids"])
        success+=int(rec["successful_nonzero_symbols"])
        stock_rows+=int(rec["stock_rows"])
        trading_rows+=sum(int(r["trading_rows"]) for r in manifest)
        flag3_total+=int(rec["flag3_rows_total"])
        flag3_xc+=int(rec["flag3_crosschecked_rows_total"])
        parts.append({
            "shard":sid,
            "file":rec["parquet_file"],
            "rows":int(rec["stock_rows"]),
            "bytes":int(rec["parquet_bytes"]),
            "sha256":rec["parquet_sha256"],
            "shard_receipt":f"V2.8.6_FOLD1_SOURCE_SHARD_{sid}_RECEIPT.json",
            "shard_receipt_sha256":rec["receipt_sha256"]
        })
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
    bench=copy_and_validate_benchmark(out)
    receipt={
        "schema":"AI_CORE_EVID_V2_8_6_FOLD1_SOURCE_SNAPSHOT_RECEIPT_V2",
        "version":"V2.8.6","status":"PASS",
        "provider":"BaoStock","baostock_version":"0.9.4",
        "retrieval_start":"2022-09-01","retrieval_end":"2024-12-31",
        "sample_manifest_sha256":SAMPLE_SHA,"sample_count":1058,
        "successful_nonzero_symbols":success,
        "zero_row_symbols":len(zero),"zero_row_canonical_ids":sorted(zero),
        "persistent_query_errors":0,
        "stock_rows":stock_rows,"stock_trading_rows":trading_rows,
        "flag3_rows_total":flag3_total,"flag3_crosschecked_rows_total":flag3_xc,
        "stock_partitions":parts,
        "benchmark":bench,
        "query_manifest_file":mp.name,"query_manifest_sha256":sha_file(mp),
        "acquisition_architecture":"16 deterministic stock shards, max-parallel=4, proactive re-login every 25 symbols; benchmark reused from frozen V2.8.5 snapshot",
        "factor_or_forward_return_computed":False,
        "fold1_mechanism_statistics_computed":False,
        "sample_replacement_used":False,
        "fold2_3_4_consumed":False
    }
    receipt["receipt_sha256"]=stable_sha(receipt)
    rp=out/"V2.8.6_FOLD1_SOURCE_SNAPSHOT_RECEIPT.json"
    rp.write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(receipt,ensure_ascii=False,indent=2))

if __name__=="__main__":
    main()
