from __future__ import annotations

import json
from pathlib import Path

KERNEL = Path("evidence/V2.9_GOVERNANCE_KERNEL.json")
FOUNDATION = Path("evidence/V2.9_VALIDITY_AND_DISCIPLINE_FOUNDATION.json")
EXIT_AUDIT = Path("evidence/V2.9_INTEGRITY_EXIT_AUDIT_CONTRACT.json")

REQUIRED_INVARIANTS = {"NO_LEAKAGE","NO_SILENT_SAMPLE_MUTATION","NO_UNDOCUMENTED_OVERRIDE","NO_UNSUPPORTED_CERTAINTY","NO_GOAL_DRIFT"}
REQUIRED_ARCHITECTURE = {"GOVERNANCE_KERNEL","EVIDENCE_ENGINE","VALIDITY_ENGINE","DISCIPLINE_ENGINE"}
REQUIRED_PROBLEM_CLASSES = {"SYSTEM_CRITICAL","RESEARCH_UNCERTAINTY","EXTERNAL_OPERATIONAL"}
REQUIRED_HARD_GATE_FAMILIES = {
    "FUTURE_OR_LABEL_LEAKAGE","SILENT_SAMPLE_MUTATION_OR_SELECTION_BIAS",
    "TEMPORAL_OR_VINTAGE_INDETERMINACY_MATERIAL_TO_INFERENCE","OOS_PROSPECTIVE_OR_LIVE_CONTAMINATION",
    "UNAUTHORIZED_MODEL_CLASSIFIER_THRESHOLD_OR_LABEL_CHANGE","MATERIAL_EVIDENCE_IDENTITY_FAILURE",
    "RISK_OR_DISCIPLINE_RULE_FAILURE",
}
REQUIRED_VALIDITY_DIMENSIONS = {
    "effect_size","baseline_comparison","out_of_sample","regime_stability","cross_sectional_stability",
    "transaction_cost_and_execution_constraints","drawdown_and_loss_sequences",
    "probability_calibration_where_applicable","reasonable_parameter_sensitivity","failure_region_identification",
}
REQUIRED_STRENGTH_LEVELS = {"STRONG","MODERATE","WEAK","INSUFFICIENT"}
REQUIRED_ACTION_TYPES = {"BUY","ADD","HOLD","REDUCE","EXIT"}
REQUIRED_ELIGIBILITY_OUTPUTS = {
    "EXIT_REQUIRED","ACTION_BLOCKED_BY_RISK","ACTION_BLOCKED_BY_EVIDENCE",
    "NO_ACTION_INSUFFICIENT_EVIDENCE","ACTION_ELIGIBLE",
}
REQUIRED_EXIT_LABELS = {"CONSTITUTION_KEEP","ACTIVE_COMPATIBILITY_KEEP","DIAGNOSTIC_ONLY","REDUNDANT_RETIRE_FROM_ACTIVE_PATH","UNRESOLVED_BLOCKER"}
REQUIRED_GOVERNANCE_OBJECTS = {"workflow","gate","amendment","receipt","validation_layer","probe"}
REQUIRED_ADMISSION_PREVENTS = {"leakage","silent mutation","invalid inference","risk-discipline failure"}


def read(path: Path) -> dict:
    if not path.exists():
        raise RuntimeError(f"MISSING_REQUIRED_FILE:{path}")
    return json.loads(path.read_text(encoding="utf-8"))


def exact_set(actual, expected: set[str], code: str) -> None:
    got = set(actual or [])
    if got != expected:
        raise RuntimeError(f"{code}:{sorted(got)}")


def main() -> None:
    k = read(KERNEL); f = read(FOUNDATION); e = read(EXIT_AUDIT)
    if k.get("schema") != "AI_CORE_EVID_V2_9_GOVERNANCE_KERNEL_V1": raise RuntimeError("KERNEL_SCHEMA_BLOCK")
    if k.get("status") != "FROZEN_ARCHITECTURE_BASELINE": raise RuntimeError("KERNEL_STATUS_BLOCK")
    exact_set(k.get("constitutional_invariants", {}).keys(), REQUIRED_INVARIANTS, "KERNEL_INVARIANT_DRIFT")
    exact_set(k.get("architecture", {}).keys(), REQUIRED_ARCHITECTURE, "KERNEL_ARCHITECTURE_DRIFT")
    exact_set(k.get("problem_ownership", {}).keys(), REQUIRED_PROBLEM_CLASSES, "PROBLEM_OWNERSHIP_DRIFT")
    exact_set(k.get("allowed_hard_gate_families"), REQUIRED_HARD_GATE_FAMILIES, "HARD_GATE_FAMILY_DRIFT")

    ownership = k["problem_ownership"]
    if ownership["SYSTEM_CRITICAL"].get("default_action") != "BLOCK": raise RuntimeError("SYSTEM_CRITICAL_DEFAULT_ACTION_BLOCK")
    if ownership["RESEARCH_UNCERTAINTY"].get("default_action") != "DO_NOT_ENGINEER_A_FIX": raise RuntimeError("RESEARCH_UNCERTAINTY_DEFAULT_ACTION_BLOCK")
    exact_set(ownership["RESEARCH_UNCERTAINTY"].get("allowed_outputs"), REQUIRED_STRENGTH_LEVELS, "RESEARCH_UNCERTAINTY_OUTPUT_DRIFT")
    if ownership["EXTERNAL_OPERATIONAL"].get("default_action") != "RETRY_CACHE_DEGRADE_RECORD": raise RuntimeError("EXTERNAL_OPERATIONAL_DEFAULT_ACTION_BLOCK")
    escalation = ownership["EXTERNAL_OPERATIONAL"].get("escalation_rule", "")
    if "sample identity" not in escalation or "temporal validity" not in escalation or "discipline outcome" not in escalation:
        raise RuntimeError("EXTERNAL_OPERATIONAL_ESCALATION_RULE_BLOCK")

    compat = k.get("backward_compatibility", {})
    for key, expected in {
        "V2_8_12R_evidence_is_immutable": True,
        "V2_8_12R_existing_gates_remain_binding_until_explicitly_closed": True,
        "no_existing_threshold_or_pass_condition_is_changed_by_this_kernel": True,
        "new_kernel_applies_prospectively_to_new_governance_design": True,
    }.items():
        if compat.get(key) is not expected: raise RuntimeError(f"BACKWARD_COMPATIBILITY_BLOCK:{key}")

    gate_test = k.get("gate_admission_test", {})
    if len(gate_test.get("questions", [])) != 4: raise RuntimeError("GATE_ADMISSION_QUESTION_COUNT_BLOCK")
    if "If all answers are NO" not in gate_test.get("rule", ""): raise RuntimeError("GATE_ADMISSION_RULE_BLOCK")

    obj_rule = k.get("governance_object_admission_rule", {})
    exact_set(obj_rule.get("applies_to"), REQUIRED_GOVERNANCE_OBJECTS, "GOVERNANCE_OBJECT_SCOPE_DRIFT")
    exact_set(obj_rule.get("admit_only_if_prevents"), REQUIRED_ADMISSION_PREVENTS, "GOVERNANCE_ADMISSION_PREVENTS_DRIFT")
    if not obj_rule.get("required_question"): raise RuntimeError("GOVERNANCE_REQUIRED_QUESTION_BLOCK")

    semantics = k.get("decision_semantics", {})
    exact_set(semantics.get("action_type_values"), REQUIRED_ACTION_TYPES, "ACTION_TYPE_SEMANTICS_DRIFT")
    exact_set(semantics.get("eligibility_output_values"), REQUIRED_ELIGIBILITY_OUTPUTS, "ELIGIBILITY_OUTPUT_SEMANTICS_DRIFT")
    if "separate fields" not in semantics.get("semantic_rule", ""): raise RuntimeError("ACTION_ELIGIBILITY_SEPARATION_BLOCK")

    if f.get("schema") != "AI_CORE_EVID_V2_9_VALIDITY_AND_DISCIPLINE_FOUNDATION_V1": raise RuntimeError("FOUNDATION_SCHEMA_BLOCK")
    if f.get("governance_kernel") != str(KERNEL): raise RuntimeError("FOUNDATION_KERNEL_BINDING_BLOCK")
    if f.get("status") != "FOUNDATION_FROZEN_BEFORE_IMPLEMENTATION": raise RuntimeError("FOUNDATION_STATUS_BLOCK")
    validity = f.get("validity_engine", {})
    exact_set(validity.get("required_dimensions"), REQUIRED_VALIDITY_DIMENSIONS, "VALIDITY_DIMENSION_DRIFT")
    exact_set(validity.get("evidence_strength_levels"), REQUIRED_STRENGTH_LEVELS, "VALIDITY_STRENGTH_DRIFT")
    if len(validity.get("anti_p_hacking_rules", [])) < 4: raise RuntimeError("ANTI_P_HACKING_RULES_BLOCK")
    if "single PASS" not in validity.get("pass_fail_policy", ""): raise RuntimeError("VALIDITY_PASS_FAIL_POLICY_BLOCK")

    discipline = f.get("discipline_engine", {})
    exact_set(discipline.get("behavioral_guards", {}).keys(), {"anti_fomo","anti_averaging_down","stop_loss_lock","take_profit_lock","override_logging"}, "DISCIPLINE_GUARD_DRIFT")
    if "action eligibility" not in discipline.get("principle", ""): raise RuntimeError("DISCIPLINE_PRINCIPLE_BLOCK")

    if e.get("schema") != "AI_CORE_EVID_V2_9_INTEGRITY_EXIT_AUDIT_CONTRACT_V1": raise RuntimeError("EXIT_AUDIT_SCHEMA_BLOCK")
    if e.get("governance_kernel") != str(KERNEL): raise RuntimeError("EXIT_AUDIT_KERNEL_BINDING_BLOCK")
    if e.get("status") != "FROZEN_BEFORE_AUDIT": raise RuntimeError("EXIT_AUDIT_STATUS_BLOCK")
    exact_set(e.get("classification_labels"), REQUIRED_EXIT_LABELS, "EXIT_AUDIT_LABEL_DRIFT")
    retirement = e.get("retirement_safety", {})
    if retirement.get("destructive_deletion_of_historical_evidence") is not False: raise RuntimeError("HISTORICAL_EVIDENCE_DELETION_BLOCK")
    if retirement.get("silent_relabeling_of_old_pass_fail_states") is not False: raise RuntimeError("OLD_STATE_RELABEL_BLOCK")
    if retirement.get("removal_of_controls_required_by_open_frozen_contracts") is not False: raise RuntimeError("OPEN_CONTRACT_CONTROL_REMOVAL_BLOCK")

    result = {
        "schema": "AI_CORE_EVID_V2_9_GOVERNANCE_KERNEL_VALIDATION_V3",
        "status": "PASS",
        "checks": {
            "constitutional_invariants_exact": True,
            "four_module_architecture_exact": True,
            "problem_ownership_exact": True,
            "hard_gate_families_exact": True,
            "governance_admission_rule_exact": True,
            "action_and_eligibility_semantics_exact": True,
            "V2_8_12R_backward_compatibility_preserved": True,
            "validity_dimensions_and_strength_exact": True,
            "anti_p_hacking_protection_present": True,
            "discipline_guards_exact": True,
            "integrity_exit_labels_and_retirement_safety_exact": True
        },
        "note": "Checks V2.9 governance semantics and compatibility structure only; does not evaluate profitability or authorize execution."
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__": main()
