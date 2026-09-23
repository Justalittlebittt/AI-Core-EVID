from __future__ import annotations
import argparse,csv,hashlib,json,shutil
from collections import Counter
from pathlib import Path
import pyarrow.parquet as pq

SAMPLE=Path("evidence/V2.8.7_FOLD2_SETUP_SHAPE_MANIFEST.csv")
SAMPLE_SHA="79b6a4c752a22a16f6ec7167dfb1e6b007473229d7ec6729fb03a15b3ba0fa9a"
BENCH=Path("evidence/v285_holdout_source/V2.8.5_BAOSTOCK_CSI300.parquet")
BENCH_SHA="1aee2f5af524e0f99f788166731d3c9ce3a862c6f1af9203b442f11f6d5fe272"
N=16

def sha_file(p):
    h=hashlib.sha256()
    with Path(p).open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""): h.update(b)
    return h.hexdigest()
def stable_sha(o): return hashlib.sha256(json.dumps(o,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()
def shard(cid): return int(hashlib.sha256(cid.encode()).hexdigest()[:8],16)%N
def read_csv(p): return list(csv.DictReader(Path(p).read_text(encoding="utf-8").splitlines()))
def load_sample():
    if sha_file(SAMPLE)!=SAMPLE_SHA: raise RuntimeError("SAMPLE_SHA_BLOCK")
    rows=read_csv(SAMPLE)
    if len(rows)!=1048: raise RuntimeError("SAMPLE_COUNT_BLOCK")
    return {r["canonical_security_id"]:r for r in rows}

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--artifact-root",required=True); ap.add_argument("--out",required=True); a=ap.parse_args()
    root=Path(a.artifact_root); out=Path(a.out); out.mkdir(parents=True,exist_ok=True); sample=load_sample()
    allm=[]; parts=[]; zero=[]; invalid=[]; invalid_details=[]; stock_rows=0; success=0
    for sid in range(N):
        rp=root/f"V2.8.7_FOLD2_TENCENT_SHARD_{sid}_RECEIPT.json"
        if not rp.exists(): raise RuntimeError(f"SHARD_RECEIPT_MISSING:{sid}")
        rec=json.loads(rp.read_text(encoding="utf-8"))
        if rec.get("status")!="PASS" or int(rec.get("shard",-1))!=sid: raise RuntimeError(f"SHARD_NOT_PASS:{sid}")
        mp=root/rec["query_manifest_file"]; pp=root/rec["parquet_file"]
        if sha_file(mp)!=rec["query_manifest_sha256"] or sha_file(pp)!=rec["parquet_sha256"]: raise RuntimeError(f"SHARD_HASH_BLOCK:{sid}")
        m=read_csv(mp); expected={cid for cid in sample if shard(cid)==sid}; got={r["canonical_security_id"] for r in m}
        if got!=expected or len(m)!=len(expected): raise RuntimeError(f"SHARD_SET_BLOCK:{sid}")
        t=pq.read_table(pp,columns=["canonical_security_id","acquisition_shard_mod16","source_adjustment"])
        cids=t.column("canonical_security_id").to_pylist()
        if len(cids)!=int(rec["stock_rows"]) or any(int(x)!=sid for x in t.column("acquisition_shard_mod16").to_pylist()): raise RuntimeError(f"PARQUET_ASSIGNMENT_BLOCK:{sid}")
        if t.num_rows and set(t.column("source_adjustment").to_pylist())!={"hfq"}: raise RuntimeError(f"ADJUSTMENT_BLOCK:{sid}")
        counts=Counter(cids); mcounts={r["canonical_security_id"]:int(r["rows"]) for r in m}
        if counts!={k:v for k,v in mcounts.items() if v>0}: raise RuntimeError(f"ROWCOUNT_BLOCK:{sid}")
        allm.extend(m)
        zero.extend(rec.get("zero_row_canonical_ids",[]))
        invalid.extend(rec.get("source_invalid_canonical_ids",[]))
        invalid_details.extend(rec.get("source_invalid_details",[]))
        success+=int(rec["successful_nonzero_symbols"]); stock_rows+=int(rec["stock_rows"])
        parts.append({"shard":sid,"file":rec["parquet_file"],"rows":int(rec["stock_rows"]),"bytes":int(rec["parquet_bytes"]),
                      "sha256":rec["parquet_sha256"],"shard_receipt":rp.name,"shard_receipt_sha256":rec["receipt_sha256"]})
    ids=[r["canonical_security_id"] for r in allm]
    if len(allm)!=1048 or len(ids)!=len(set(ids)) or set(ids)!=set(sample): raise RuntimeError("MERGED_COVERAGE_BLOCK")
    allm.sort(key=lambda r:r["canonical_security_id"])
    mp=out/"V2.8.7_FOLD2_TENCENT_QUERY_MANIFEST.csv"
    fields=list(allm[0].keys())
    with mp.open("w",encoding="utf-8",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,lineterminator="\n"); w.writeheader(); w.writerows(allm)
    if not BENCH.exists() or sha_file(BENCH)!=BENCH_SHA: raise RuntimeError("BENCHMARK_REUSE_BLOCK")
    bp=out/"V2.8.7_FOLD2_BAOSTOCK_CSI300.parquet"; shutil.copyfile(BENCH,bp)
    receipt={
      "schema":"AI_CORE_EVID_V2_8_7_FOLD2_SOURCE_SNAPSHOT_RECEIPT_V1","version":"V2.8.7","status":"PASS",
      "stock_provider":"Tencent Securities direct transport","stock_interface":"newfqkline/get","stock_adjustment":"hfq",
      "retrieval_start":"2022-09-01","retrieval_end":"2024-12-31","sample_manifest_sha256":SAMPLE_SHA,"sample_count":1048,
      "successful_nonzero_symbols":success,
      "zero_row_symbols":len(zero),"zero_row_canonical_ids":sorted(zero),
      "source_invalid_symbols":len(invalid),"source_invalid_canonical_ids":sorted(invalid),
      "source_invalid_details":sorted(invalid_details,key=lambda x:x["canonical_security_id"]),
      "stock_rows":stock_rows,"stock_partitions":parts,
      "benchmark":{"status":"PASS","rows":565,"file":bp.name,"parquet_sha256":BENCH_SHA,
                   "reused_from":"evidence/v285_holdout_source/V2.8.5_BAOSTOCK_CSI300.parquet"},
      "query_manifest_file":mp.name,"query_manifest_sha256":sha_file(mp),
      "factor_or_forward_return_computed":False,"mechanism_statistics_computed":False,
      "sample_replacement_used":False,"fold3_4_consumed":False
    }
    receipt["receipt_sha256"]=stable_sha(receipt)
    (out/"V2.8.7_FOLD2_SOURCE_SNAPSHOT_RECEIPT.json").write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(receipt,ensure_ascii=False,indent=2))
if __name__=="__main__": main()
