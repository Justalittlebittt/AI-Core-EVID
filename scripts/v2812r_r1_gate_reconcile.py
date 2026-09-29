from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

BASE = Path("evidence/retrospective_feasibility")
WINDOWS = BASE / "V2.8.12R_EXPANSION_WINDOWS.json"
RESULTS = BASE / "V2.8.12R_EXPANSION_RESULTS.csv"
EVENT_RECEIPT = BASE / "V2.8.12R_EVENT_COHORT_RECEIPT.json"
INITIAL_GATE = BASE / "V2.8.12R_R1_TECHNICAL_GATE_RECEIPT.json"
SOURCE_PROBE = BASE / "V2.8.12R_R1_BLOCKED_WINDOW_IDENTIFICATION_PROBE.json"
AMBIGUITY = BASE / "V2.8.12R_R1_AMBIGUITY_SET_SELECTION_AUDIT.json"
REPAIR_RESULTS = BASE / "V2.8.12R_R1_TECHNICAL_REPAIR_RESULTS.csv"
REPAIR_RECEIPT = BASE / "V2.8.12R_R1_TECHNICAL_REPAIR_RECEIPT.json"
AMEND2 = Path("evidence/V2.8.12R_RETROSPECTIVE_FEASIBILITY_CONTRACT_AMENDMENT_2.json")
OUT = BASE / "V2.8.12R_R1_TECHNICAL_GATE_RECONCILED_RECEIPT.json"


def read_json(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


def stable_sha(obj) -> str:
    return hashlib.sha256(json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def main() -> None:
    windows = read_json(WINDOWS)
    event = read_json(EVENT_RECEIPT)
    gate = read_json(INITIAL_GATE)
    probe = read_json(SOURCE_PROBE)
    ambiguity = read_json(AMBIGUITY)
    repair = read_json(REPAIR_RECEIPT)
    amend = read_json(AMEND2)

    if windows.get("status") != "FROZEN_BEFORE_REAL_CANDIDATE_QUERY" or len(windows.get("windows", [])) != 16:
        raise RuntimeError("FROZEN_WINDOWS_BINDING_BLOCK")
    if gate.get("status") != "R1_TECHNICAL_INCOMPLETE_R2_OUTCOME_ACCESS_BLOCKED":
        raise RuntimeError("INITIAL_GATE_NOT_EXPECTED_FAIL_STATE")
    if gate.get("R2_price_or_return_access_authorized") is not False:
        raise RuntimeError("INITIAL_R2_AUTHORIZATION_DRIFT")
    if event.get("window_status_counts") != {"COMPLETED": 15, "WINDOW_SOURCE_BLOCKED": 1}:
        raise RuntimeError("ORIGINAL_WINDOW_STATUS_DRIFT")
    if event.get("new_selected_rows") != 41 or event.get("new_successful_classifier_ready_rows") != 38:
        raise RuntimeError("ORIGINAL_COUNT_DRIFT")
    if amend.get("R1_technical_completeness_gate", {}).get("classifier_ready_selected_filing_rate_min") != 0.90:
        raise RuntimeError("READY_RATE_THRESHOLD_DRIFT")

    rows = list(csv.DictReader(RESULTS.read_text(encoding="utf-8").splitlines()))
    result_window_keys = {(r["quarter"], int(r["anchor_session"]), r["window_start"], r["window_end"]) for r in rows}
    manifest_keys = {(w["quarter"], int(w["anchor_session"]), w["start"], w["end"]) for w in windows["windows"]}
    missing_from_results = manifest_keys - result_window_keys

    probe_records = probe.get("records", [])
    probe_keys = {(r["quarter"], int(r["anchor_session"]), r["start"], r["end"]) for r in probe_records}
    if len(probe_records) != 2 or missing_from_results != probe_keys:
        raise RuntimeError(f"AMBIGUITY_SET_BINDING_BLOCK:{sorted(missing_from_results)}:{sorted(probe_keys)}")
    if any(r.get("source_status") != "SOURCE_QUERY_COMPLETED" for r in probe_records):
        raise RuntimeError("AMBIGUITY_SOURCE_RETRY_NOT_COMPLETE")
    all_16_complete = True

    if ambiguity.get("candidate_query_completed") is not True or ambiguity.get("deterministically_selected_count") != 1:
        raise RuntimeError("AMBIGUITY_SELECTION_NOT_FROZEN")
    if ambiguity.get("records", [{}])[0].get("announcement_id") != "1216331011":
        raise RuntimeError("AMBIGUITY_SELECTED_ID_DRIFT")

    repair_rows = list(csv.DictReader(REPAIR_RESULTS.read_text(encoding="utf-8").splitlines()))
    if len(repair_rows) != 1 or repair_rows[0].get("announcement_id") != "1216331011":
        raise RuntimeError("REPAIR_RESULT_CARDINALITY_BLOCK")
    rr = repair_rows[0]
    if repair.get("candidate_result", {}).get("announcement_id") != "1216331011":
        raise RuntimeError("REPAIR_RECEIPT_ID_BLOCK")

    original_aids = [r["announcement_id"] for r in rows if r.get("announcement_id")]
    if len(original_aids) != len(set(original_aids)):
        raise RuntimeError("ORIGINAL_ANNOUNCEMENT_DEDUP_DRIFT")
    if "1216331011" in set(original_aids):
        raise RuntimeError("REPAIR_ID_ALREADY_IN_ORIGINAL_RESULTS")
    dedup_pass = True

    new_ready = 1 if rr.get("pipeline_status") == "SUCCESS" else 0
    selected = 41 + 1
    ready = 38 + new_ready
    ready_rate = ready / selected
    ready_pass = ready_rate >= 0.90

    original_positive_temporal = gate.get("checks", {}).get("all_positive_temporal_provenance_pass") is True
    new_is_positive = rr.get("pipeline_status") == "SUCCESS" and rr.get("classification_state") == "ELIGIBLE_AI_CORE"
    new_positive_temporal = (not new_is_positive) or rr.get("temporal_provenance_status") == "PASS"
    positive_temporal_pass = original_positive_temporal and new_positive_temporal

    passed = all_16_complete and ready_pass and positive_temporal_pass and dedup_pass

    out = {
        "schema": "AI_CORE_EVID_V2_8_12R_R1_TECHNICAL_COMPLETENESS_RECONCILED_RECEIPT_V1",
        "version": "V2.8.12R",
        "status": "R1_COHORT_TECHNICALLY_COMPLETE" if passed else "R1_TECHNICAL_INCOMPLETE_R2_OUTCOME_ACCESS_BLOCKED",
        "authority": str(AMEND2),
        "reconciliation_basis": {
            "initial_gate_receipt": str(INITIAL_GATE),
            "source_retry_probe": str(SOURCE_PROBE),
            "ambiguity_selection_audit": str(AMBIGUITY),
            "technical_repair_receipt": str(REPAIR_RECEIPT),
            "original_gate_receipt_preserved": True,
        },
        "checks": {
            "frozen_windows": 16,
            "original_completed_windows": 15,
            "original_source_blocked_windows": 1,
            "missing_result_window_keys_exactly_equal_two_window_probe_set": True,
            "both_ambiguous_windows_source_query_completed_on_retry": True,
            "all_16_windows_complete": all_16_complete,
            "selected_filings": selected,
            "classifier_ready_filings": ready,
            "classifier_ready_rate": ready_rate,
            "classifier_ready_rate_ge_0_90": ready_pass,
            "all_positive_temporal_provenance_pass": positive_temporal_pass,
            "announcement_id_dedup_pass": dedup_pass,
        },
        "R2_price_or_return_access_authorized": passed,
        "prospective_gate_changed": False,
        "fold3_accessed": False,
        "fold4_accessed": False,
        "price_or_return_data_consumed_in_R1": False,
        "setup_or_live_accessed": False,
    }
    out["receipt_sha256"] = stable_sha(out)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2))
    if not passed:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
