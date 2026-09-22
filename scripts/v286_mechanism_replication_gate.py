from __future__ import annotations
import hashlib, json
from pathlib import Path

SOURCE=Path("evidence/V2.8.6_FOLD1_SOURCE_SNAPSHOT_RECEIPT.json")
SOURCE_DIR=Path("evidence/v286_fold1_source")
MANIFEST_RECEIPT=Path("evidence/V2.8.6_FOLD1_MANIFEST_RECEIPT.json")
VALIDATION=Path("evidence/V2.8.6_LOCKED_MECHANISM_REPLICATION_VALIDATION_RECEIPT.json")
ACTIVATION=Path("evidence/V2.8.6_MECHANISM_REPLICATION_ACTIVATION.json")
FINAL=Path("evidence/V2.8.6_MECHANISM_REPLICATION_FINAL_RECEIPT.json")
VALIDATION_COMMIT="5358c888408b2ebd64d3f8db3068f4a9d5690552"

def sha_file(path):
    h=hashlib.sha256()
    with Path(path).open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""): h.update(b)
    return h.hexdigest()

def load(path):
    p=Path(path)
    if not p.exists(): raise RuntimeError(f"MISSING:{p}")
    return json.loads(p.read_text(encoding="utf-8"))

def main():
    m=load(MANIFEST_RECEIPT)
    if m.get("status")!="PASS" or m.get("target_fold")!=1:
        raise RuntimeError("FOLD1_MANIFEST_NOT_PASS")
    if m.get("manifest_sha256")!="fe15777a0a3a131b58288454a0e3023503bd80ac6a22f20a2e50c45a4deed38a":
        raise RuntimeError("FOLD1_MANIFEST_SHA_BLOCK")
    v=load(VALIDATION)
    if v.get("status")!="PASS" or v.get("validated_head_sha")!="cd88566d1eb2f1979abece0935bb1841b7cf2c5c":
        raise RuntimeError("EVALUATOR_VALIDATION_BLOCK")
    s=load(SOURCE)
    if s.get("status")!="PASS" or int(s.get("sample_count",0))!=1058:
        raise RuntimeError("FOLD1_SOURCE_NOT_PASS")
    a=load(ACTIVATION)
    if a.get("status")!="ACTIVE_ONE_TIME_V2_8_6_MECHANISM_REPLICATION":
        raise RuntimeError("ACTIVATION_NOT_ACTIVE")
    if a.get("source_snapshot_receipt_sha256")!=s.get("receipt_sha256"):
        raise RuntimeError("ACTIVATION_SOURCE_BINDING_MISMATCH")
    if a.get("fold1_manifest_sha256")!=m.get("manifest_sha256"):
        raise RuntimeError("ACTIVATION_MANIFEST_BINDING_MISMATCH")
    if a.get("evaluator_validation_commit_sha")!=VALIDATION_COMMIT:
        raise RuntimeError("ACTIVATION_VALIDATION_BINDING_MISMATCH")
    if FINAL.exists():
        raise RuntimeError("TERMINAL_FINAL_ALREADY_EXISTS")
    for p in s["stock_partitions"]:
        fp=SOURCE_DIR/p["file"]
        if not fp.exists() or sha_file(fp)!=p["sha256"]:
            raise RuntimeError(f"SOURCE_PARTITION_INTEGRITY:{p['file']}")
    bp=SOURCE_DIR/s["benchmark"]["file"]
    if not bp.exists() or sha_file(bp)!=s["benchmark"]["parquet_sha256"]:
        raise RuntimeError("BENCHMARK_INTEGRITY")
    mp=SOURCE_DIR/s["query_manifest_file"]
    if not mp.exists() or sha_file(mp)!=s["query_manifest_sha256"]:
        raise RuntimeError("QUERY_MANIFEST_INTEGRITY")
    print(json.dumps({
        "schema":"AI_CORE_EVID_V2_8_6_MECHANISM_REPLICATION_GATE_CHECK_V1",
        "status":"PASS_READY_FOR_ONE_TIME_REPLICATION",
        "source_snapshot_receipt_sha256":s["receipt_sha256"],
        "sample_count":s["sample_count"],
        "stock_rows":s["stock_rows"],
        "fold2_3_4_consumed":False
    },ensure_ascii=False,indent=2))

if __name__=="__main__": main()
