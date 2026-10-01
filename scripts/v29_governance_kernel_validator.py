from __future__ import annotations

import json
from pathlib import Path

KERNEL = Path("evidence/V2.9_GOVERNANCE_KERNEL.json")
FOUNDATION = Path("evidence/V2.9_VALIDITY_AND_DISCIPLINE_FOUNDATION.json")
EXIT_AUDIT_CONTRACT = Path("evidence/V2.9_INTEGRITY_EXIT_AUDIT_CONTRACT.json")
EXIT_AUDIT_RECEIPT = Path("evidence/V2.9_INTEGRITY_EXIT_AUDIT_RECEIPT.json")
VALIDITY_CONTRACT = Path("evidence/V2.9_STRATEGY_VALIDITY_BASELINE_CONTRACT.json")
DISCIPLINE_CONTRACT = Path("evidence/V2.9_DISCIPLINE_ENGINE_V1_CONTRACT.json")
DECISION_PACKET_CONTRACT = Path("evidence/V2.9_DECISION_PACKET_CONTRACT.json")
DISCIPLINE_REPAIR_1 = Path("evidence/V2.9_DISCIPLINE_POST_BASELINE_REPAIR_1.json")
DISCIPLINE_ENGINE = Path("scripts/v29_discipline_engine.py")
DECISION_PACKET_ADAPTER = Path("scripts/v29_decision_packet_adapter.py")

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
REQUIRED_PRIORITY = [
    "EXIT_REQUIRED","ACTION_BLOCKED_BY_RISK","ACTION_BLOCKED_BY_EVIDENCE",
    "NO_ACTION_INSUFFICIENT_EVIDENCE","ACTION_ELIGIBLE",
]
REQUIRED_EXIT_LABELS = {"CONSTITUTION_KEEP","ACTIVE_COMPATIBILITY_KEEP","DIAGNOSTIC_ONLY","REDUNDANT_RETIRE_FROM_ACTIVE_PATH","UNRESOLVED_BLOCKER"}
REQUIRED_GOVERNANCE_OBJECTS = {"workflow","gate","amendment","receipt","validation_layer","probe"}
REQUIRED_ADMISSION_PREVENTS = {"leakage","silent mutation","invalid inference","risk-discipline failure"}
REQUIRED_REPAIR_RISK_FIELDS = {
    "exit_rule_revision_type",
    "exit_rule_triggered",
    "exit_rule_relaxation_condition_satisfied_before_trigger",
}


def read(path: Path) -> dict:
    if not path.exists():
        raise RuntimeError(f"MISSING_REQUIRED_FILE:{path}")
    return json.loads(path.read_text(encoding="utf-8"))


def exact_set(actual, expected: set[str], code: str) -> None:
    got = set(actual or [])
    if got != expected:
        raise RuntimeError(f"{code}:{sorted(got)}")


def main() -> None:
    k = read(KERNEL); f = read(FOUNDATION); ec = read(EXIT_AUDIT_CONTRACT); er = read(EXIT_AUDIT_RECEIPT)
    vc = read(VALIDITY_CONTRACT); dc = read(DISCIPLINE_CONTRACT); pc = read(DECISION_PACKET_CONTRACT)
    repair = read(DISCIPLINE_REPAIR_1)

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

    compat = k.get("backward_compatibility", {})
    for key, expected in {
        "V2_8_12R_evidence_is_immutable": True,
        "V2_8_12R_existing_gates_remain_binding_until_explicitly_closed": True,
        "no_existing_threshold_or_pass_condition_is_changed_by_this_kernel": True,
        "new_kernel_applies_prospectively_to_new_governance_design": True,
    }.items():
        if compat.get(key) is not expected: raise RuntimeError(f"BACKWARD_COMPATIBILITY_BLOCK:{key}")

    obj_rule = k.get("governance_object_admission_rule", {})
    exact_set(obj_rule.get("applies_to"), REQUIRED_GOVERNANCE_OBJECTS, "GOVERNANCE_OBJECT_SCOPE_DRIFT")
    exact_set(obj_rule.get("admit_only_if_prevents"), REQUIRED_ADMISSION_PREVENTS, "GOVERNANCE_ADMISSION_PREVENTS_DRIFT")

    semantics = k.get("decision_semantics", {})
    exact_set(semantics.get("action_type_values"), REQUIRED_ACTION_TYPES, "ACTION_TYPE_SEMANTICS_DRIFT")
    exact_set(semantics.get("eligibility_output_values"), REQUIRED_ELIGIBILITY_OUTPUTS, "ELIGIBILITY_OUTPUT_SEMANTICS_DRIFT")

    if f.get("schema") != "AI_CORE_EVID_V2_9_VALIDITY_AND_DISCIPLINE_FOUNDATION_V1": raise RuntimeError("FOUNDATION_SCHEMA_BLOCK")
    if f.get("governance_kernel") != str(KERNEL): raise RuntimeError("FOUNDATION_KERNEL_BINDING_BLOCK")
    validity = f.get("validity_engine", {})
    exact_set(validity.get("required_dimensions"), REQUIRED_VALIDITY_DIMENSIONS, "VALIDITY_DIMENSION_DRIFT")
    exact_set(validity.get("evidence_strength_levels"), REQUIRED_STRENGTH_LEVELS, "VALIDITY_STRENGTH_DRIFT")
    if len(validity.get("anti_p_hacking_rules", [])) < 4: raise RuntimeError("ANTI_P_HACKING_RULES_BLOCK")
    discipline = f.get("discipline_engine", {})
    if discipline.get("action_output_priority") != REQUIRED_PRIORITY: raise RuntimeError("FOUNDATION_DISCIPLINE_PRIORITY_DRIFT")
    exact_set(discipline.get("behavioral_guards", {}).keys(), {"anti_fomo","anti_averaging_down","stop_loss_lock","take_profit_lock","override_logging"}, "DISCIPLINE_GUARD_DRIFT")

    if vc.get("governance_kernel") != str(KERNEL) or vc.get("foundation") != str(FOUNDATION): raise RuntimeError("VALIDITY_CONTRACT_BINDING_BLOCK")
    exact_set(vc.get("experiment_preregistration", {}).get("required_dimension_plan"), REQUIRED_VALIDITY_DIMENSIONS, "VALIDITY_CONTRACT_DIMENSION_DRIFT")
    exact_set(vc.get("result_interface", {}).get("evidence_strength_levels"), REQUIRED_STRENGTH_LEVELS, "VALIDITY_CONTRACT_STRENGTH_DRIFT")
    if vc.get("experiment_preregistration", {}).get("post_outcome_dimension_deletion_allowed") is not False: raise RuntimeError("POST_OUTCOME_DIMENSION_DELETION_BLOCK")
    if vc.get("experiment_preregistration", {}).get("post_outcome_baseline_replacement_allowed") is not False: raise RuntimeError("POST_OUTCOME_BASELINE_REPLACEMENT_BLOCK")
    if vc.get("result_interface", {}).get("automatic_upgrade_from_point_estimate_only") is not False: raise RuntimeError("POINT_ESTIMATE_AUTO_UPGRADE_BLOCK")

    if dc.get("governance_kernel") != str(KERNEL): raise RuntimeError("DISCIPLINE_KERNEL_BINDING_BLOCK")
    if dc.get("validity_foundation") != str(FOUNDATION): raise RuntimeError("DISCIPLINE_FOUNDATION_BINDING_BLOCK")
    exact_set(dc.get("input_contract", {}).get("action_types"), REQUIRED_ACTION_TYPES, "DISCIPLINE_ACTION_TYPE_DRIFT")
    exact_set(dc.get("input_contract", {}).get("evidence_strength_levels"), REQUIRED_STRENGTH_LEVELS, "DISCIPLINE_EVIDENCE_STRENGTH_DRIFT")
    exact_set(dc.get("output_contract", {}).get("decision_values"), REQUIRED_ELIGIBILITY_OUTPUTS, "DISCIPLINE_OUTPUT_DRIFT")
    if dc.get("priority_order") != REQUIRED_PRIORITY: raise RuntimeError("DISCIPLINE_PRIORITY_DRIFT")
    strict_types = dc.get("input_contract", {}).get("strict_types", {})
    if "native booleans" not in strict_types.get("boolean_rule", ""): raise RuntimeError("DISCIPLINE_BOOLEAN_TYPE_BLOCK")
    if "finite numeric values" not in strict_types.get("numeric_rule", ""): raise RuntimeError("DISCIPLINE_NUMERIC_TYPE_BLOCK")
    if "fail closed" not in strict_types.get("numeric_rule", ""): raise RuntimeError("DISCIPLINE_NUMERIC_FAIL_CLOSED_BLOCK")

    if pc.get("governance_kernel") != str(KERNEL): raise RuntimeError("PACKET_KERNEL_BINDING_BLOCK")
    if pc.get("validity_contract") != str(VALIDITY_CONTRACT): raise RuntimeError("PACKET_VALIDITY_BINDING_BLOCK")
    if pc.get("discipline_contract") != str(DISCIPLINE_CONTRACT): raise RuntimeError("PACKET_DISCIPLINE_BINDING_BLOCK")
    if "native booleans" not in pc.get("packet", {}).get("strict_boolean_rule", ""): raise RuntimeError("PACKET_BOOLEAN_TYPE_BLOCK")
    if "NaN and infinity are invalid" not in pc.get("packet", {}).get("strict_numeric_rule", ""): raise RuntimeError("PACKET_NUMERIC_TYPE_BLOCK")
    if "may only be downgraded to INSUFFICIENT" not in pc.get("binding_rules", {}).get("evidence_strength_passthrough", ""): raise RuntimeError("PACKET_EVIDENCE_DOWNGRADE_ONLY_BLOCK")
    if "Missing required fields are an error" not in pc.get("binding_rules", {}).get("no_risk_field_inference", ""): raise RuntimeError("PACKET_MISSING_RISK_FAIL_CLOSED_BLOCK")

    packet_fields = set()
    psec = pc.get("packet", {})
    for key in ("validity_required_fields","action_context_required_fields","risk_context_required_fields","behavior_context_required_fields","override_context_required_fields"):
        packet_fields.update(psec.get(key, []))
    discipline_fields = set(dc.get("input_contract", {}).get("required_fields", []))
    if not discipline_fields.issubset(packet_fields):
        raise RuntimeError(f"PACKET_DOES_NOT_COVER_DISCIPLINE_INPUT:{sorted(discipline_fields - packet_fields)}")

    # Post-baseline repair is additive and immutable-history preserving. The active validator must
    # not report PASS from the frozen V1 contracts alone after active code has stricter semantics.
    if repair.get("schema") != "AI_CORE_EVID_V2_9_DISCIPLINE_POST_BASELINE_REPAIR_1":
        raise RuntimeError("DISCIPLINE_REPAIR_SCHEMA_BLOCK")
    if repair.get("status") != "IMPLEMENTATION_AND_REGRESSION_TESTS_UPDATED_NOT_CENTRALLY_EXECUTED":
        raise RuntimeError("DISCIPLINE_REPAIR_STATUS_BLOCK")
    exact_set(
        repair.get("new_required_active_fields", {}).get("risk_context"),
        REQUIRED_REPAIR_RISK_FIELDS,
        "DISCIPLINE_REPAIR_RISK_FIELD_DRIFT",
    )
    exact_set(
        repair.get("new_required_active_fields", {}).get("exit_rule_revision_type_enum"),
        {"NONE", "TIGHTEN", "RELAX"},
        "DISCIPLINE_REPAIR_REVISION_ENUM_DRIFT",
    )
    validation_state = repair.get("validation_state", {})
    if validation_state.get("implementation_updated") is not True: raise RuntimeError("DISCIPLINE_REPAIR_IMPLEMENTATION_BLOCK")
    if validation_state.get("regression_tests_updated") is not True: raise RuntimeError("DISCIPLINE_REPAIR_REGRESSION_TEST_BLOCK")
    if validation_state.get("central_runtime_execution_observed") is not False: raise RuntimeError("DISCIPLINE_REPAIR_RUNTIME_CLAIM_DRIFT")

    if not DISCIPLINE_ENGINE.exists() or not DECISION_PACKET_ADAPTER.exists():
        raise RuntimeError("DISCIPLINE_REPAIR_ACTIVE_CODE_MISSING")
    engine_text = DISCIPLINE_ENGINE.read_text(encoding="utf-8")
    adapter_text = DECISION_PACKET_ADAPTER.read_text(encoding="utf-8")
    for field in REQUIRED_REPAIR_RISK_FIELDS:
        if field not in engine_text: raise RuntimeError(f"DISCIPLINE_REPAIR_ENGINE_FIELD_MISSING:{field}")
        if field not in adapter_text: raise RuntimeError(f"DISCIPLINE_REPAIR_ADAPTER_FIELD_MISSING:{field}")
    if "if current_exposure_exists and stop_loss_breached:" not in engine_text:
        raise RuntimeError("DISCIPLINE_REPAIR_UNCONDITIONAL_STOP_LOCK_MISSING")
    if "if current_exposure_exists and exit_rule_triggered:" not in engine_text:
        raise RuntimeError("DISCIPLINE_REPAIR_EXIT_TRIGGER_LOCK_MISSING")
    if 'exit_rule_revision_type == "RELAX"' not in engine_text:
        raise RuntimeError("DISCIPLINE_REPAIR_RELAXATION_LOCK_MISSING")

    if ec.get("schema") != "AI_CORE_EVID_V2_9_INTEGRITY_EXIT_AUDIT_CONTRACT_V1": raise RuntimeError("EXIT_AUDIT_SCHEMA_BLOCK")
    exact_set(ec.get("classification_labels"), REQUIRED_EXIT_LABELS, "EXIT_AUDIT_LABEL_DRIFT")
    if er.get("status") != "PASS_NO_UNRESOLVED_BLOCKER": raise RuntimeError("EXIT_AUDIT_RECEIPT_STATUS_BLOCK")
    if er.get("summary", {}).get("UNRESOLVED_BLOCKER") != 0: raise RuntimeError("EXIT_AUDIT_UNRESOLVED_BLOCKER")
    if er.get("summary", {}).get("V2_8_12R_open_compatibility_dependencies") != 0: raise RuntimeError("LEGACY_COMPATIBILITY_DEPENDENCY_REOPENED")
    if er.get("exit_condition_pass") is not True: raise RuntimeError("EXIT_AUDIT_EXIT_CONDITION_BLOCK")

    result = {
        "schema": "AI_CORE_EVID_V2_9_END_TO_END_GOVERNANCE_ACCEPTANCE_V1",
        "status": "PASS",
        "checks": {
            "governance_kernel_invariants_exact": True,
            "problem_ownership_and_hard_gate_scope_exact": True,
            "V2_8_12R_backward_compatibility_preserved": True,
            "validity_dimensions_and_strength_consistent": True,
            "anti_p_hacking_contract_consistent": True,
            "discipline_action_output_and_priority_consistent": True,
            "strict_boolean_and_numeric_semantics_present": True,
            "decision_packet_covers_frozen_v1_discipline_inputs": True,
            "decision_packet_downgrade_only_semantics_present": True,
            "post_baseline_discipline_repair_bound_to_active_code": True,
            "post_baseline_stop_and_exit_rule_locks_statically_present": True,
            "integrity_exit_audit_closed_without_blocker": True,
            "legacy_active_dependency_count_zero": True
        },
        "note": "Cross-layer contract/static acceptance including post-baseline discipline repair 1. Runtime self-tests are not claimed as centrally executed. Profitability is not evaluated and no brokerage or live execution is authorized."
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__": main()
