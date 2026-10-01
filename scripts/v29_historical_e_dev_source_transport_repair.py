from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import v29_historical_e_dev_source_runner as runner

RUNNER_PATH = Path("scripts/v29_historical_e_dev_source_runner.py")
COLLECTOR_PATH = Path("scripts/v284_candidate_collector.py")
AUDIT_PATH = Path("evidence/V2.9_HISTORICAL_E_DEV_SOURCE_TRANSPORT_REPAIR_1.json")

EXPECTED_RUNNER_BLOB = "9fc6d07c92571db45845271175fced261f0226ab"
EXPECTED_COLLECTOR_BLOB = "9fd2885518aaa5eefc382c068019a0c86ac5f3ce"
FAILED_OUTPUT_COMMIT = "4594b775c6aa0b7aa53fc82a050dfc410b6a3939"
FAILED_RECEIPT_SHA256 = "01e4a53a0c7b5ca0d6ad19c5f8f2ffbab0cf77622ee56379049b67849ce2d379"
TECH_BLOCK = "V2_9_HISTORICAL_E_DEV_SOURCE_TECHNICALLY_BLOCKED"
TERMINAL = {
    "V2_9_HISTORICAL_E_DEV_SOURCE_READY",
    "V2_9_HISTORICAL_E_DEV_SOURCE_TOO_SPARSE",
}


def git_blob_sha(path: Path) -> str:
    data = path.read_bytes()
    header = f"blob {len(data)}\0".encode("utf-8")
    return hashlib.sha1(header + data).hexdigest()


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def verify_frozen_blobs() -> None:
    if git_blob_sha(RUNNER_PATH) != EXPECTED_RUNNER_BLOB:
        raise RuntimeError("RUNNER_BLOB_DRIFT")
    if git_blob_sha(COLLECTOR_PATH) != EXPECTED_COLLECTOR_BLOB:
        raise RuntimeError("COLLECTOR_BLOB_DRIFT")


def load_audit() -> dict:
    obj = read_json(AUDIT_PATH)
    if obj.get("schema") != "AI_CORE_EVID_V2_9_HISTORICAL_E_DEV_SOURCE_TRANSPORT_REPAIR_1":
        raise RuntimeError("TRANSPORT_REPAIR_AUDIT_SCHEMA_BLOCK")
    if obj.get("status") != "FROZEN_TECHNICAL_RETRY_AUTHORIZATION":
        raise RuntimeError("TRANSPORT_REPAIR_AUDIT_STATUS_BLOCK")
    failure = obj.get("failed_attempt", {})
    if failure.get("output_commit") != FAILED_OUTPUT_COMMIT:
        raise RuntimeError("FAILED_OUTPUT_COMMIT_BINDING_BLOCK")
    if failure.get("final_receipt_sha256") != FAILED_RECEIPT_SHA256:
        raise RuntimeError("FAILED_RECEIPT_BINDING_BLOCK")
    auth = obj.get("authorization", {})
    if auth.get("one_in_place_source_only_technical_retry") is not True:
        raise RuntimeError("TECHNICAL_RETRY_NOT_AUTHORIZED")
    forbidden = (
        "price_or_return_access",
        "candidate_outcome_research",
        "fold3_access",
        "fold4_access",
        "window_mutation",
        "classifier_mutation",
        "triage_mutation",
        "registry_mutation",
        "selection_cap_mutation",
        "information_gate_mutation",
        "v2_8_12r_reopen",
    )
    if any(auth.get(key) is not False for key in forbidden):
        raise RuntimeError("TRANSPORT_REPAIR_SCOPE_BLOCK")
    return obj


def isolated_collect(start, end, out_dir: Path) -> None:
    subprocess.run(
        [
            sys.executable,
            str(COLLECTOR_PATH),
            "collect",
            "--start",
            start.isoformat(),
            "--end",
            end.isoformat(),
            "--out",
            str(out_dir),
        ],
        check=True,
    )


def prepare_retry() -> str:
    verify_frozen_blobs()
    audit = load_audit()
    if not runner.OUT_FINAL.exists():
        return "NO_PRIOR_FINAL"

    final = read_json(runner.OUT_FINAL)
    status = final.get("status")
    if status in TERMINAL:
        return "TERMINAL_ALREADY_FROZEN"
    if status != TECH_BLOCK:
        raise RuntimeError(f"UNRECOGNIZED_PRIOR_FINAL_STATUS:{status}")
    if final.get("receipt_sha256") != FAILED_RECEIPT_SHA256:
        raise RuntimeError("PRIOR_TECHNICAL_FAILURE_RECEIPT_DRIFT")

    if audit["failed_attempt"].get("root_cause") != "NESTED_PLAYWRIGHT_SYNC_CONTEXT":
        raise RuntimeError("ROOT_CAUSE_BINDING_BLOCK")

    for path in (runner.OUT_WINDOWS, runner.OUT_RESULTS, runner.OUT_POSITIVE, runner.OUT_FINAL):
        if path.exists():
            path.unlink()
    return "TECHNICAL_RETRY_PREPARED"


def self_test() -> None:
    verify_frozen_blobs()
    audit = load_audit()
    tests = [
        {"name": "TR01_runner_blob_frozen", "pass": git_blob_sha(RUNNER_PATH) == EXPECTED_RUNNER_BLOB},
        {"name": "TR02_collector_blob_frozen", "pass": git_blob_sha(COLLECTOR_PATH) == EXPECTED_COLLECTOR_BLOB},
        {"name": "TR03_failed_commit_pinned", "pass": audit["failed_attempt"]["output_commit"] == FAILED_OUTPUT_COMMIT},
        {"name": "TR04_failed_receipt_pinned", "pass": audit["failed_attempt"]["final_receipt_sha256"] == FAILED_RECEIPT_SHA256},
        {"name": "TR05_retry_source_only", "pass": audit["authorization"]["one_in_place_source_only_technical_retry"] is True},
        {"name": "TR06_no_price_or_return", "pass": audit["authorization"]["price_or_return_access"] is False},
        {"name": "TR07_no_fold34", "pass": audit["authorization"]["fold3_access"] is False and audit["authorization"]["fold4_access"] is False},
        {"name": "TR08_no_semantic_mutation", "pass": all(
            audit["authorization"][k] is False
            for k in (
                "window_mutation",
                "classifier_mutation",
                "triage_mutation",
                "registry_mutation",
                "selection_cap_mutation",
                "information_gate_mutation",
                "v2_8_12r_reopen",
            )
        )},
    ]
    out = {
        "schema": "AI_CORE_EVID_V2_9_HISTORICAL_E_DEV_SOURCE_TRANSPORT_REPAIR_SELFTEST_1",
        "passed": sum(x["pass"] for x in tests),
        "total": len(tests),
        "all_pass": all(x["pass"] for x in tests),
        "tests": tests,
        "real_source_queries_executed": False,
        "price_or_return_data_consumed": False,
        "fold3_accessed": False,
        "fold4_accessed": False,
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    if not out["all_pass"]:
        raise SystemExit(2)


def run() -> None:
    mode = prepare_retry()
    if mode == "TERMINAL_ALREADY_FROZEN":
        print(json.dumps({"status": mode}, ensure_ascii=False))
        return
    import v284_candidate_collector as collector
    collector.collect = isolated_collect
    print(json.dumps({"transport_repair_mode": mode}, ensure_ascii=False))
    runner.run()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["self-test", "run"])
    args = parser.parse_args()
    self_test() if args.command == "self-test" else run()
