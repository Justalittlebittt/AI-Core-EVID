#!/usr/bin/env python3
"""Portable V2.9.3 Batch-3 launcher. No GitHub runner required.

Runs exact frozen chunk-3 and aggregator in a pre-provisioned Python environment.
Does not alter science, create a false PASS, or authorize Batch-4.
"""
from __future__ import annotations
import argparse, hashlib, json, os, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVID = ROOT / "evidence"
EXPECTED = {
    "scripts/v293_batch3_chunk3_reconstruct.py": "dd655bffa989075cec5aa490344d7797c124156a",
    "scripts/v293_batch3_reconstruct_aggregate.py": "7bee071203302dd07136c737e733c70491e7a07f",
}
PREREQUISITES = {
    "V2.9.1_COMPARISON_AUTHORITY_RECOVERY_RECEIPT_1.json": "e4874bff18bdc9524687376714ea51132074265df8623b1d6f7bd91639f4e81f",
    "V2.9.1_RECOVERED_PARENT_CANDIDATE_IDS_1.csv": "4a620188902b38f12fcc1e45431cf2ea5ced55f32aab8844299cec3776c59a9c",
    "V2.9.1_NEGATIVE_SPACE_PROBE_PHASE_A_VALIDATION_1.json": "737612813f5358c3050a37a43b1592d3d48cbb11d4d752db3c00720e781580e7",
    "V2.9_HISTORICAL_E_SOURCE_EXPANSION_FINAL_RECEIPT_1.json": "ce27e03c93562508c93d24621637944670dcc0db3adb931046b7bff7e3780119",
    "V2.9_HISTORICAL_E_SOURCE_EXPANSION_POSITIVE_EVENTS_1.csv": "ea0631371002e3c29e61c04e39e8ce9d246a2fa3df9b135229f64653e23adc5b",
}
CHUNK_RECEIPT = EVID / "V2.9.3_BATCH3_RECONSTRUCTION_CHUNK_03_RECEIPT_1.json"
AGG_RECEIPT = EVID / "V2.9.3_RECONSTRUCTED_BATCH3_RECEIPT_1.json"
LOCAL_RECEIPT = EVID / "V2.9.3_PORTABLE_EXECUTION_TERMINAL_1.json"

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def git_blob(path):
    data=path.read_bytes()
    return hashlib.sha1(b"blob "+str(len(data)).encode()+bytes([0])+data).hexdigest()

def preflight():
    for rel, expected in EXPECTED.items():
        p=ROOT/rel
        if not p.is_file() or git_blob(p)!=expected:
            raise RuntimeError("FROZEN_EXECUTOR_MISMATCH:"+rel)
    for filename, expected in PREREQUISITES.items():
        p=EVID/"v293_prerequisites"/filename
        if not p.is_file() or sha(p)!=expected:
            raise RuntimeError("PREREQUISITE_SHA_MISMATCH:"+filename)
    contract=json.loads((EVID/"V2.9.3_BATCH3_MINIMAL_RECONSTRUCTION_CONTRACT_1.json").read_text(encoding="utf-8"))
    if contract.get("status")!="FROZEN_BEFORE_IMPLEMENTATION" or contract["exact_reconstruction_scope"]["batch_ranks"]!=list(range(145,153)) or contract["immutable_reuse_chunks"]!=[1,2,4,5,6,7,8]:
        raise RuntimeError("CONTRACT_SCOPE_BLOCK")
    if contract["exact_reconstruction_scope"]["scientific_batch_index"]!=3:
        raise RuntimeError("BATCH_INDEX_BLOCK")
    return True

def run(args):
    return subprocess.run([sys.executable,*args],cwd=ROOT,check=False).returncode

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--preflight-only",action="store_true")
    args=parser.parse_args()
    phase="PREFLIGHT"
    status="BLOCKED"
    error=None
    code=1
    try:
        preflight()
        if args.preflight_only:
            print("PORTABLE_PREFLIGHT_PASS (no scientific execution)")
            return 0
        phase="CHUNK3"
        code=run(["scripts/v293_batch3_chunk3_reconstruct.py",
                  "--authority","evidence/v293_prerequisites/V2.9.1_RECOVERED_PARENT_CANDIDATE_IDS_1.csv",
                  "--recovery-receipt","evidence/v293_prerequisites/V2.9.1_COMPARISON_AUTHORITY_RECOVERY_RECEIPT_1.json",
                  "--phase-a-receipt","evidence/v293_prerequisites/V2.9.1_NEGATIVE_SPACE_PROBE_PHASE_A_VALIDATION_1.json"])
        if code: raise RuntimeError("CHUNK3_EXIT_"+str(code))
        chunk=json.loads(CHUNK_RECEIPT.read_text(encoding="utf-8"))
        if chunk.get("status")!="V2_9_3_BATCH3_RECONSTRUCTION_CHUNK_COMPLETE" or chunk.get("execution_integrity_pass") is not True:
            raise RuntimeError("CHUNK3_RECEIPT_BLOCK")
        phase="AGGREGATE"
        code=run(["scripts/v293_batch3_reconstruct_aggregate.py",
                  "--parent-positive-events","evidence/v293_prerequisites/V2.9_HISTORICAL_E_SOURCE_EXPANSION_POSITIVE_EVENTS_1.csv",
                  "--parent-final-receipt","evidence/v293_prerequisites/V2.9_HISTORICAL_E_SOURCE_EXPANSION_FINAL_RECEIPT_1.json"])
        if code: raise RuntimeError("AGGREGATE_EXIT_"+str(code))
        aggregate=json.loads(AGG_RECEIPT.read_text(encoding="utf-8"))
        if aggregate.get("status") not in ("V2_9_3_HYBRID_DISCOVERY_READY","V2_9_3_BATCH3_COMPLETE_TOO_SPARSE") or aggregate.get("next_batch_authorized") is not False:
            raise RuntimeError("AGGREGATE_RECEIPT_BLOCK")
        status="EXECUTION_COMPLETE_SCIENTIFIC_STATUS_IN_AGGREGATE_RECEIPT"
        phase="COMPLETE"
        code=0
    except Exception as exc:
        error=str(exc)
        code=1
    finally:
        if not args.preflight_only:
            EVID.mkdir(parents=True,exist_ok=True)
            record={"schema":"AI_CORE_EVID_V2_9_3_PORTABLE_EXECUTION_TERMINAL_1",
                    "status":status,"phase":phase,"error":error,
                    "chunk_receipt_sha256":sha(CHUNK_RECEIPT) if CHUNK_RECEIPT.exists() else None,
                    "aggregate_receipt_sha256":sha(AGG_RECEIPT) if AGG_RECEIPT.exists() else None,
                    "next_batch_authorized":False,
                    "scientific_conclusion_from_this_receipt":False}
            LOCAL_RECEIPT.write_text(json.dumps(record,indent=2)+chr(10),encoding="utf-8")
            print(json.dumps(record,ensure_ascii=False),flush=True)
    return code

if __name__=="__main__":
    raise SystemExit(main())
