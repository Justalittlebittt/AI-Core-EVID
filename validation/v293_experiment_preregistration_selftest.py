import copy
import json
from pathlib import Path

from scripts.v29_strategy_validity_validator import contract, validate_prereg


TEMPLATE = Path("evidence/V2.9_EXPERIMENT_PREREGISTRATION_TEMPLATE.json")


def fill(value):
    if isinstance(value, dict):
        return {k: fill(v) for k, v in value.items()}
    if isinstance(value, list):
        return [fill(v) for v in value]
    if value == "REQUIRED_BEFORE_FREEZE":
        return "synthetic-predeclared-value"
    return value


def main() -> None:
    c = contract()
    template = json.loads(TEMPLATE.read_text(encoding="utf-8"))

    unresolved = copy.deepcopy(template)
    unresolved["status"] = "FROZEN_BEFORE_OUTCOME_EVALUATION"
    try:
        validate_prereg(unresolved, c)
        raise AssertionError("unresolved placeholders must fail")
    except RuntimeError as exc:
        assert "UNRESOLVED_PREREG_PLACEHOLDER" in str(exc)

    frozen = fill(copy.deepcopy(template))
    frozen["status"] = "FROZEN_BEFORE_OUTCOME_EVALUATION"
    frozen["matched_random_baseline_plan"]["replicate_count"] = 5000
    frozen["matched_random_baseline_plan"]["seed"] = 2901
    frozen["matched_random_baseline_plan"]["post_outcome_change_forbidden"] = True
    frozen["coverage_plan"]["no_universal_selection_rate_floor"] = True
    frozen["coverage_plan"]["post_outcome_relaxation_forbidden"] = True
    frozen["oos_plan"]["membership_frozen_before_outcomes"] = True
    frozen["oos_plan"]["reuse_after_failure_for_rule_tuning"] = False
    frozen["interpretation_policy"]["ordinary_validity_weakness_is_hard_block"] = False
    frozen["interpretation_policy"]["all_soft_dimensions_must_pass"] = False
    frozen["interpretation_policy"]["coverage_collapse_cannot_strengthen_claim"] = True
    frozen["interpretation_policy"]["post_outcome_threshold_tuning"] = "FORBIDDEN"

    receipt = validate_prereg(frozen, c)
    assert receipt["status"] == "PASS_PREREGISTRATION_INTERFACE"
    assert receipt["dimension_count"] == 10
    assert receipt["matched_random_scope"] == "CONDITIONAL_SELECTION_ONLY"
    assert receipt["coverage_metric_count"] == 6
    assert receipt["portfolio_path_plan_bound"] is True
    assert receipt["oos_plan_bound"] is True
    assert len(receipt["preregistration_sha256"]) == 64

    bad_oos = copy.deepcopy(frozen)
    bad_oos["oos_plan"]["reuse_after_failure_for_rule_tuning"] = True
    try:
        validate_prereg(bad_oos, c)
        raise AssertionError("OOS reuse for tuning must fail")
    except RuntimeError as exc:
        assert "OOS_REUSE_FOR_TUNING_FORBIDDEN" in str(exc)

    bad_and_gate = copy.deepcopy(frozen)
    bad_and_gate["interpretation_policy"]["all_soft_dimensions_must_pass"] = True
    try:
        validate_prereg(bad_and_gate, c)
        raise AssertionError("soft-dimension AND gate must fail")
    except RuntimeError as exc:
        assert "SOFT_DIMENSION_AND_GATE_FORBIDDEN" in str(exc)

    print("V2.9 experiment preregistration synthetic selftest: PASS")


if __name__ == "__main__":
    main()
