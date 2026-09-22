from __future__ import annotations

import hashlib
import json
from pathlib import Path

PROBE=Path("evidence/V2.8.5_BAOSTOCK_SOURCE_PROBE_RECEIPT.json")
SAMPLE=Path("evidence/V2.8.5_BACKWARD_HOLDOUT_SAMPLE_RECEIPT.json")
CALENDAR=Path("evidence/V2.8.5_JOINT_A_SHARE_TRADING_CALENDAR_2023_2024.json")
SNAPSHOT=Path("evidence/V2.8.5_BAOSTOCK_HOLDOUT_SOURCE_SNAPSHOT_RECEIPT.json")
VALIDATION=Path("evidence/V2.8.5_LOCKED_HOLDOUT_EVALUATOR_VALIDATION_RECEIPT.json")
ACTIVATION=Path("evidence/V2.8.5_HOLDOUT_EVALUATION_ACTIVATION.json")
SOURCE_DIR=Path("evidence/v285_holdout_source")
FINAL=Path("evidence/V2.8.5_BACKWARD_HOLDOUT_FINAL_RECEIPT.json")

def sha_file(path:Path)->str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""):
            h.update(b)
    return h.hexdigest()

def load(path:Path)->dict:
    if not path.exists(): raise RuntimeError(f"MISSING:{path}")
    return json.loads(path.read_text(encoding="utf-8"))

def main():
    if load(PROBE).get("status")!="PASS": raise RuntimeError("PROBE_NOT_PASS")
    if load(SAMPLE).get("status")!="PASS": raise RuntimeError("SAMPLE_NOT_PASS")
    if load(CALENDAR).get("status")!="PASS": raise RuntimeError("CALENDAR_NOT_PASS")
    val=load(VALIDATION)
    if val.get("status")!="PASS": raise RuntimeError("EVALUATOR_VALIDATION_NOT_PASS")
    snap=load(SNAPSHOT)
    if snap.get("status")!="PASS": raise RuntimeError("SNAPSHOT_NOT_PASS")
    act=load(ACTIVATION)
    if act.get("status")!="ACTIVE_ONE_TIME_BACKWARD_HOLDOUT_EVALUATION":
        raise RuntimeError("ACTIVATION_NOT_ACTIVE")
    if act.get("source_snapshot_receipt_sha256")!=snap.get("receipt_sha256"):
        raise RuntimeError("ACTIVATION_SNAPSHOT_BINDING_MISMATCH")
    if act.get("sample_receipt_sha256")!=load(SAMPLE).get("receipt_sha256"):
        raise RuntimeError("ACTIVATION_SAMPLE_BINDING_MISMATCH")
    if act.get("calendar_receipt_sha256")!=load(CALENDAR).get("receipt_sha256"):
        raise RuntimeError("ACTIVATION_CALENDAR_BINDING_MISMATCH")
    if act.get("evaluator_validation_commit_sha")!="5c661f2a5fc5404bf72d43a2a899a13fa970305a":
        raise RuntimeError("ACTIVATION_EVALUATOR_VALIDATION_BINDING_MISMATCH")
    if FINAL.exists():
        raise RuntimeError("TERMINAL_FINAL_ALREADY_EXISTS")
    for p in snap["stock_partitions"]:
        fp=SOURCE_DIR/p["file"]
        if not fp.exists() or sha_file(fp)!=p["sha256"]:
            raise RuntimeError(f"STOCK_PARTITION_INTEGRITY:{p['file']}")
    bp=SOURCE_DIR/snap["benchmark"]["file"]
    if not bp.exists() or sha_file(bp)!=snap["benchmark"]["parquet_sha256"]:
        raise RuntimeError("BENCHMARK_INTEGRITY")
    mp=SOURCE_DIR/snap["query_manifest_file"]
    if not mp.exists() or sha_file(mp)!=snap["query_manifest_sha256"]:
        raise RuntimeError("QUERY_MANIFEST_INTEGRITY")
    print(json.dumps({
        "schema":"AI_CORE_EVID_V2_8_5_HOLDOUT_EVALUATION_GATE_CHECK_V1",
        "status":"PASS_READY_FOR_ONE_TIME_EVALUATION",
        "source_snapshot_receipt_sha256":snap["receipt_sha256"],
        "sample_count":snap["sample_count"],
        "stock_rows":snap["stock_rows"],
        "factor_or_outcome_computed_by_gate":False
    },ensure_ascii=False,indent=2))

if __name__=="__main__":
    main()
