"""Write non-scientific failure terminal evidence for a V2.9.3 workflow failure.

This does not change historical chunk receipts, scientific outcomes, or information floors.
"""
import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

EVIDENCE = Path("evidence")
PREFIX = "V2.9.3_BATCH3_RECONSTRUCTION"
CHUNK = EVIDENCE / (PREFIX + "_CHUNK_03_RECEIPT_1.json")
PROGRESS = EVIDENCE / (PREFIX + "_CHUNK_03_PROGRESS_1.json")
RESULTS = EVIDENCE / (PREFIX + "_CHUNK_03_RESULTS_1.csv")
AGGREGATE = EVIDENCE / "V2.9.3_RECONSTRUCTED_BATCH3_RECEIPT_1.json"
OUTPUT = EVIDENCE / "V2.9.3_BATCH3_EXECUTION_FAILURE_TERMINAL_1.json"

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--job-status", required=True, choices=("failure", "cancelled", "success"))
    parser.add_argument("--run-id", default="")
    parser.add_argument("--run-attempt", default="")
    args = parser.parse_args()
    if args.job_status == "success":
        return
    chunk_receipt = json.loads(CHUNK.read_text(encoding="utf-8")) if CHUNK.exists() else None
    aggregate_receipt = json.loads(AGGREGATE.read_text(encoding="utf-8")) if AGGREGATE.exists() else None
    record = {
        "schema": "AI_CORE_EVID_V2_9_3_BATCH3_EXECUTION_FAILURE_TERMINAL_1",
        "version": "V2.9.3",
        "status": "EXECUTION_FAILED_NO_SCIENTIFIC_CONCLUSION",
        "job_status": args.job_status,
        "run_id": args.run_id,
        "run_attempt": args.run_attempt,
        "recorded_utc": datetime.now(timezone.utc).isoformat(),
        "scientific_batch_index": 3,
        "batch_ranks": [129, 192],
        "reconstructed_chunk_ranks": list(range(145, 153)),
        "chunk_receipt_status": chunk_receipt.get("status") if chunk_receipt else "ABSENT",
        "aggregate_receipt_status": aggregate_receipt.get("status") if aggregate_receipt else "ABSENT",
        "observed_files_sha256": {str(p): digest(p) for p in (CHUNK, PROGRESS, RESULTS, AGGREGATE)},
        "next_scientific_batch_authorized": False,
        "scientific_terminal_status_emitted": False,
        "no_scientific_conclusion": True,
        "failure_source": "GITHUB_ACTIONS_JOB_TERMINAL_STATE",
        "limitations": "Not evidence of an atomic commit or survival of runner loss before this handler executes."
    }
    OUTPUT.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(record, ensure_ascii=False))

if __name__ == "__main__":
    main()
