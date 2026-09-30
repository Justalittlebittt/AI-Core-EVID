from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

CONTRACT = Path("evidence/V2.9_STRATEGY_VALIDITY_BASELINE_CONTRACT.json")


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def stable_sha(obj) -> str:
    return hashlib.sha256(json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def require_keys(obj: dict, keys: list[str], where: str) -> None:
    missing = [k for k in keys if k not in obj]
    if missing:
        raise RuntimeError(f"MISSING_REQUIRED_FIELDS:{where}:{','.join(missing)}")


def contract() -> dict:
    c = read_json(CONTRACT)
    if c.get("status") != "FROZEN_BEFORE_STRATEGY_LEVEL_IMPLEMENTATION":
        raise RuntimeError("VALIDITY_BASELINE_CONTRACT_NOT_FROZEN")
    return c


def validate_prereg(prereg: dict, c: dict) -> dict:
    if prereg.get("status") != "FROZEN_BEFORE_OUTCOME_EVALUATION":
        raise RuntimeError("PREREG_NOT_FROZEN_BEFORE_OUTCOME")
    require_keys(prereg, ["identity", "comparison", "dimensions"], "prereg")
    require_keys(prereg["identity"], c["experiment_preregistration"]["required_identity_fields"], "identity")
    require_keys(prereg["comparison"], c["experiment_preregistration"]["required_comparison_fields"], "comparison")

    required_dims = c["experiment_preregistration"]["required_dimension_plan"]
    dim_required = c["experiment_preregistration"]["per_dimension_required_fields"]
    dims = prereg["dimensions"]
    if not isinstance(dims, list):
        raise RuntimeError("PREREG_DIMENSIONS_NOT_LIST")
    seen = []
    for d in dims:
        require_keys(d, dim_required, f"dimension:{d.get('dimension','?')}")
        seen.append(d["dimension"])
    if len(seen) != len(set(seen)):
        raise RuntimeError("DUPLICATE_PREREG_DIMENSION")
    if set(seen) != set(required_dims):
        raise RuntimeError(f"PREREG_DIMENSION_SET_DRIFT:expected={sorted(required_dims)}:actual={sorted(seen)}")

    comparison = prereg["comparison"]
    for k in ["simple_baseline", "market_or_domain_baseline", "primary_metric", "primary_horizon", "transaction_cost_model", "execution_constraints"]:
        if comparison.get(k) in (None, "", [], {}):
            raise RuntimeError(f"EMPTY_PREREG_COMPARISON_FIELD:{k}")

    return {
        "status": "PASS_PREREGISTRATION_INTERFACE",
        "experiment_id": prereg["identity"]["experiment_id"],
        "dimension_count": len(dims),
        "preregistration_sha256": stable_sha(prereg),
    }


def derive_strength(prereg: dict, result: dict, c: dict) -> tuple[str, list[str]]:
    reasons: list[str] = []
    if result.get("integrity_prerequisite_status") != "PASS":
        reasons.append("integrity_prerequisite_not_pass")
        return "INSUFFICIENT", reasons
    if result.get("minimum_sample_or_resolved_data_floor_pass") is not True:
        reasons.append("minimum_sample_or_resolved_data_floor_failed")
        return "INSUFFICIENT", reasons
    if result.get("untouched_oos_completed") is not True:
        reasons.append("untouched_oos_missing")
        return "INSUFFICIENT", reasons
    if result.get("primary_baseline_comparison_completed") is not True:
        reasons.append("primary_baseline_comparison_missing")
        return "INSUFFICIENT", reasons

    statuses = [d["status"] for d in result["dimensions"] if d["status"] != "NOT_APPLICABLE_PREDECLARED"]
    if any(s == "INSUFFICIENT_DATA" for s in statuses):
        reasons.append("applicable_dimension_has_insufficient_data")
        return "INSUFFICIENT", reasons
    if any(s == "FAILED" for s in statuses):
        reasons.append("one_or_more_predeclared_dimensions_failed")
        return "WEAK", reasons
    if any(s == "MIXED_OR_UNSTABLE" for s in statuses):
        reasons.append("one_or_more_dimensions_mixed_or_unstable")
        return "MODERATE", reasons
    if statuses and all(s == "SUPPORTED" for s in statuses):
        reasons.append("all_applicable_preregistered_dimensions_supported")
        return "STRONG", reasons
    reasons.append("no_sufficient_applicable_dimension_result")
    return "INSUFFICIENT", reasons


def validate_result(prereg: dict, result: dict, c: dict) -> dict:
    require_keys(result, [
        "experiment_id", "strategy_version", "signal_version", "preregistration_sha256",
        "integrity_prerequisite_status", "minimum_sample_or_resolved_data_floor_pass",
        "untouched_oos_completed", "primary_baseline_comparison_completed", "dimensions"
    ], "result")
    pid = prereg["identity"]
    if result["experiment_id"] != pid["experiment_id"]:
        raise RuntimeError("EXPERIMENT_ID_MISMATCH")
    if result["strategy_version"] != pid["strategy_version"]:
        raise RuntimeError("STRATEGY_VERSION_MISMATCH")
    if result["signal_version"] != pid["signal_version"]:
        raise RuntimeError("SIGNAL_VERSION_MISMATCH")
    expected_prereg_sha = stable_sha(prereg)
    if result["preregistration_sha256"] != expected_prereg_sha:
        raise RuntimeError("PREREGISTRATION_HASH_MISMATCH")

    allowed_status = set(c["result_interface"]["dimension_status_values"])
    required_result_fields = c["result_interface"]["required_result_fields_per_dimension"]
    prereg_by_dim = {d["dimension"]: d for d in prereg["dimensions"]}
    result_dims = result["dimensions"]
    result_by_dim = {}
    for d in result_dims:
        require_keys(d, required_result_fields, f"result_dimension:{d.get('dimension','?')}")
        if d["status"] not in allowed_status:
            raise RuntimeError(f"INVALID_DIMENSION_STATUS:{d['dimension']}:{d['status']}")
        if d["dimension"] in result_by_dim:
            raise RuntimeError(f"DUPLICATE_RESULT_DIMENSION:{d['dimension']}")
        result_by_dim[d["dimension"]] = d
    if set(result_by_dim) != set(prereg_by_dim):
        raise RuntimeError("POST_OUTCOME_DIMENSION_SET_CHANGED")

    for name, rd in result_by_dim.items():
        pd = prereg_by_dim[name]
        if rd["predeclared_rule_applied"] != pd["predeclared_interpretation_rule"]:
            raise RuntimeError(f"PREDECLARED_RULE_CHANGED:{name}")
        if rd["status"] == "NOT_APPLICABLE_PREDECLARED" and pd["status_if_data_unavailable"] != "NOT_APPLICABLE_PREDECLARED":
            raise RuntimeError(f"POST_HOC_NOT_APPLICABLE:{name}")

    strength, reasons = derive_strength(prereg, result, c)
    claimed = result.get("evidence_strength")
    if claimed is not None and claimed != strength:
        raise RuntimeError(f"EVIDENCE_STRENGTH_MISMATCH:claimed={claimed}:derived={strength}")

    return {
        "schema": "AI_CORE_EVID_V2_9_STRATEGY_VALIDITY_VALIDATION_RECEIPT_V1",
        "status": "PASS_VALIDITY_RESULT_INTERFACE",
        "experiment_id": result["experiment_id"],
        "preregistration_sha256": expected_prereg_sha,
        "result_sha256": stable_sha(result),
        "derived_evidence_strength": strength,
        "strength_reasons": reasons,
        "dimension_statuses": {k: v["status"] for k, v in sorted(result_by_dim.items())},
        "post_outcome_dimension_deletion_detected": False,
        "post_outcome_preregistration_rule_change_detected": False,
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--prereg", required=True)
    p.add_argument("--result")
    p.add_argument("--out")
    args = p.parse_args()

    c = contract()
    prereg = read_json(Path(args.prereg))
    pre = validate_prereg(prereg, c)
    if args.result:
        result = read_json(Path(args.result))
        receipt = validate_result(prereg, result, c)
    else:
        receipt = pre
    text = json.dumps(receipt, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    print(text, end="")


if __name__ == "__main__":
    main()
