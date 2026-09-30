from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from scripts.v294_evidence_strength_synthesizer import (
    REQUIRED_ANCHORS,
    VALID_FAILURE_EFFECTS,
    VALID_ROLES,
    synthesize_strength,
)

CONTRACT = Path("evidence/V2.9_STRATEGY_VALIDITY_BASELINE_CONTRACT.json")
PLACEHOLDER = "REQUIRED_BEFORE_FREEZE"


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def stable_sha(obj) -> str:
    return hashlib.sha256(json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def require_keys(obj: dict, keys: list[str], where: str) -> None:
    missing = [k for k in keys if k not in obj]
    if missing:
        raise RuntimeError(f"MISSING_REQUIRED_FIELDS:{where}:{','.join(missing)}")


def _contains_placeholder(obj) -> bool:
    if isinstance(obj, dict):
        return any(_contains_placeholder(v) for v in obj.values())
    if isinstance(obj, list):
        return any(_contains_placeholder(v) for v in obj)
    return obj == PLACEHOLDER


def contract() -> dict:
    c = read_json(CONTRACT)
    if c.get("schema") != "AI_CORE_EVID_V2_9_STRATEGY_VALIDITY_BASELINE_CONTRACT_V2":
        raise RuntimeError("VALIDITY_BASELINE_CONTRACT_SCHEMA_MISMATCH")
    if c.get("status") != "FROZEN_BEFORE_REAL_STRATEGY_SCORING":
        raise RuntimeError("VALIDITY_BASELINE_CONTRACT_NOT_FROZEN")
    return c


def validate_prereg(prereg: dict, c: dict) -> dict:
    if prereg.get("status") != "FROZEN_BEFORE_OUTCOME_EVALUATION":
        raise RuntimeError("PREREG_NOT_FROZEN_BEFORE_OUTCOME")
    if _contains_placeholder(prereg):
        raise RuntimeError("PREREG_CONTAINS_UNRESOLVED_PLACEHOLDER")

    require_keys(
        prereg,
        [
            "identity", "comparison", "matched_random_baseline_plan", "coverage_plan",
            "portfolio_path_plan", "oos_plan", "interpretation_policy", "synthesis_policy",
            "dimensions"
        ],
        "prereg",
    )
    require_keys(prereg["identity"], c["experiment_preregistration"]["required_identity_fields"], "identity")
    require_keys(prereg["comparison"], c["experiment_preregistration"]["required_comparison_fields"], "comparison")

    required_dims = c["experiment_preregistration"]["required_dimension_plan"]
    dim_required = c["experiment_preregistration"]["per_dimension_required_fields"]
    dims = prereg["dimensions"]
    if not isinstance(dims, list):
        raise RuntimeError("PREREG_DIMENSIONS_NOT_LIST")
    seen = []
    anchors = set()
    for d in dims:
        require_keys(d, dim_required, f"dimension:{d.get('dimension','?')}")
        name = d["dimension"]
        seen.append(name)
        if d["role"] not in VALID_ROLES:
            raise RuntimeError(f"INVALID_DIMENSION_ROLE:{name}:{d['role']}")
        if d["failure_effect"] not in VALID_FAILURE_EFFECTS:
            raise RuntimeError(f"INVALID_FAILURE_EFFECT:{name}:{d['failure_effect']}")
        if d["role"] == "ANCHOR":
            anchors.add(name)
    if len(seen) != len(set(seen)):
        raise RuntimeError("DUPLICATE_PREREG_DIMENSION")
    if set(seen) != set(required_dims):
        raise RuntimeError(f"PREREG_DIMENSION_SET_DRIFT:expected={sorted(required_dims)}:actual={sorted(seen)}")
    if not REQUIRED_ANCHORS.issubset(anchors):
        raise RuntimeError(f"REQUIRED_ANCHORS_MISSING:{','.join(sorted(REQUIRED_ANCHORS - anchors))}")

    comparison = prereg["comparison"]
    for k in ["simple_baseline", "market_or_domain_baseline", "primary_metric", "primary_horizon", "transaction_cost_model", "execution_constraints"]:
        if comparison.get(k) in (None, "", [], {}):
            raise RuntimeError(f"EMPTY_PREREG_COMPARISON_FIELD:{k}")

    mr = prereg["matched_random_baseline_plan"]
    require_keys(mr, ["scope", "opportunity_set_definition", "sampling_rule", "replicate_count", "seed", "primary_comparisons", "post_outcome_change_forbidden"], "matched_random_baseline_plan")
    if mr["scope"] != "CONDITIONAL_SELECTION_ONLY":
        raise RuntimeError("MATCHED_RANDOM_SCOPE_DRIFT")
    if type(mr["replicate_count"]) is not int or mr["replicate_count"] <= 0:
        raise RuntimeError("INVALID_MATCHED_RANDOM_REPLICATE_COUNT")
    if type(mr["seed"]) is not int:
        raise RuntimeError("INVALID_MATCHED_RANDOM_SEED")
    if mr["post_outcome_change_forbidden"] is not True:
        raise RuntimeError("MATCHED_RANDOM_POST_OUTCOME_CHANGE_NOT_FORBIDDEN")

    coverage = prereg["coverage_plan"]
    require_keys(coverage, ["time_unit", "required_metrics", "minimum_information_floor", "near_zero_action_review_rule", "no_universal_selection_rate_floor", "post_outcome_relaxation_forbidden"], "coverage_plan")
    required_coverage_metrics = {
        "evaluated_candidate_count", "eligible_candidate_count", "selection_rate",
        "opportunity_rate_per_predeclared_time_unit", "risk_increasing_action_count",
        "risk_increasing_action_rate"
    }
    if not required_coverage_metrics.issubset(set(coverage["required_metrics"])):
        raise RuntimeError("COVERAGE_METRICS_INCOMPLETE")
    if coverage["post_outcome_relaxation_forbidden"] is not True:
        raise RuntimeError("COVERAGE_POST_OUTCOME_RELAXATION_NOT_FORBIDDEN")

    portfolio = prereg["portfolio_path_plan"]
    require_keys(portfolio, ["position_weight_rule", "holding_period_rule", "overlapping_signal_rule", "transaction_cost_application", "untradable_entry_rule", "untradable_exit_rule", "benchmark_return_rule", "annualization_periods_per_year"], "portfolio_path_plan")

    oos = prereg["oos_plan"]
    require_keys(oos, ["development_scope", "untouched_oos_scope", "membership_frozen_before_outcomes", "reuse_after_failure_for_rule_tuning"], "oos_plan")
    if oos["membership_frozen_before_outcomes"] is not True:
        raise RuntimeError("OOS_MEMBERSHIP_NOT_FROZEN")
    if oos["reuse_after_failure_for_rule_tuning"] is not False:
        raise RuntimeError("OOS_REUSE_FOR_TUNING_NOT_FORBIDDEN")

    synthesis = prereg["synthesis_policy"]
    require_keys(synthesis, ["allowed_dimension_roles", "allowed_failure_effects", "required_anchor_dimensions", "rule", "post_outcome_role_or_failure_effect_change_forbidden"], "synthesis_policy")
    if set(synthesis["allowed_dimension_roles"]) != VALID_ROLES:
        raise RuntimeError("SYNTHESIS_ROLE_ENUM_DRIFT")
    if set(synthesis["allowed_failure_effects"]) != VALID_FAILURE_EFFECTS:
        raise RuntimeError("SYNTHESIS_FAILURE_EFFECT_ENUM_DRIFT")
    if set(synthesis["required_anchor_dimensions"]) != REQUIRED_ANCHORS:
        raise RuntimeError("SYNTHESIS_REQUIRED_ANCHORS_DRIFT")
    if synthesis["post_outcome_role_or_failure_effect_change_forbidden"] is not True:
        raise RuntimeError("POST_OUTCOME_SYNTHESIS_CHANGE_NOT_FORBIDDEN")

    return {
        "status": "PASS_PREREGISTRATION_INTERFACE",
        "experiment_id": prereg["identity"]["experiment_id"],
        "dimension_count": len(dims),
        "anchor_dimensions": sorted(anchors),
        "preregistration_sha256": stable_sha(prereg),
    }


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
        if "role" in rd and rd["role"] != pd["role"]:
            raise RuntimeError(f"POST_OUTCOME_ROLE_CHANGED:{name}")
        if "failure_effect" in rd and rd["failure_effect"] != pd["failure_effect"]:
            raise RuntimeError(f"POST_OUTCOME_FAILURE_EFFECT_CHANGED:{name}")

    strength, reasons = synthesize_strength(prereg, result)
    claimed = result.get("evidence_strength")
    if claimed is not None and claimed != strength:
        raise RuntimeError(f"EVIDENCE_STRENGTH_MISMATCH:claimed={claimed}:derived={strength}")

    return {
        "schema": "AI_CORE_EVID_V2_9_STRATEGY_VALIDITY_VALIDATION_RECEIPT_V2",
        "status": "PASS_VALIDITY_RESULT_INTERFACE",
        "experiment_id": result["experiment_id"],
        "preregistration_sha256": expected_prereg_sha,
        "result_sha256": stable_sha(result),
        "derived_evidence_strength": strength,
        "strength_reasons": reasons,
        "dimension_statuses": {k: v["status"] for k, v in sorted(result_by_dim.items())},
        "post_outcome_dimension_deletion_detected": False,
        "post_outcome_preregistration_rule_change_detected": False,
        "post_outcome_synthesis_role_change_detected": False,
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
