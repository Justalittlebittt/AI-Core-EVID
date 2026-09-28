from __future__ import annotations

import copy
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

CONTRACT = Path("evidence/V2.8.12_PRECOMMITTED_DISCIPLINE_PLAN_CONTRACT.json")
TEMPLATE = Path("evidence/V2.8.12_PRECOMMITTED_DISCIPLINE_PLAN_TEMPLATE.json")
PACKET_VALIDATION = Path("evidence/V2.8.12_HUMAN_REVIEW_PACKET_VALIDATION_RECEIPT.json")
HUMAN_GATE = Path("evidence/V2.8.12_HUMAN_DECISION_GATE_CONTRACT.json")
SHADOW_ACTIVATION = Path("evidence/V2.8.12_SHADOW_ACCUMULATION_ACTIVATION.json")
CANONICAL_SECURITY = re.compile(r"^(SSE|SZSE):\d{6}$")


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def canonical_sha(obj: dict) -> str:
    return hashlib.sha256(
        json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def parse_utc(value: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise RuntimeError("UTC_TIMESTAMP_REQUIRED")
    try:
        dt = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise RuntimeError("UTC_TIMESTAMP_INVALID") from exc
    if dt.tzinfo is None or dt.utcoffset() != timezone.utc.utcoffset(dt):
        raise RuntimeError("UTC_TIMESTAMP_REQUIRED")
    return dt


def contract_guard() -> tuple[dict, dict]:
    c = read_json(CONTRACT)
    p = read_json(PACKET_VALIDATION)
    if c.get("status") != "FROZEN_BEFORE_DISCIPLINE_PLAN_VALIDATION":
        raise RuntimeError("DISCIPLINE_PLAN_CONTRACT_NOT_FROZEN")
    if p.get("status") != "PASS":
        raise RuntimeError("HUMAN_REVIEW_PACKET_INTERFACE_NOT_VALIDATED")
    if read_json(HUMAN_GATE).get("status") != "FROZEN_DOWNSTREAM_HUMAN_DECISION_BOUNDARY":
        raise RuntimeError("HUMAN_DECISION_GATE_NOT_FROZEN")
    return c, p


def expected_plan_id(plan: dict) -> str:
    identity = {
        "canonical_security_id": plan["canonical_security_id"],
        "strategy_or_setup_spec_id": plan["strategy_or_setup_spec_id"],
        "discipline_plan_version": str(plan["discipline_plan_version"]),
        "frozen_at_utc": plan["frozen_at_utc"],
    }
    return canonical_sha(identity)


def finalize_hashes(plan: dict) -> dict:
    out = copy.deepcopy(plan)
    out["discipline_plan_id"] = expected_plan_id(out)
    prehash = copy.deepcopy(out)
    prehash.pop("plan_sha256", None)
    out["plan_sha256"] = canonical_sha(prehash)
    return out


def require_nonempty(obj: dict, key: str, label: str) -> None:
    if key not in obj:
        raise RuntimeError(f"{label}_MISSING:{key}")
    value = obj[key]
    if value is None or value == "" or value == []:
        raise RuntimeError(f"{label}_EMPTY:{key}")


def validate_common_rule(rule: dict, family: str, contract: dict) -> None:
    for key in contract["rule_object_common_schema"]["required_fields"]:
        require_nonempty(rule, key, family.upper())
    if rule["when_unknown_state"] == "PASS":
        raise RuntimeError(f"{family.upper()}_UNKNOWN_DEFAULT_PASS_FORBIDDEN")
    if rule["when_unknown_state"] not in set(contract["rule_object_common_schema"]["allowed_unknown_states"]):
        raise RuntimeError(f"{family.upper()}_UNKNOWN_STATE_INVALID")


def validate_plan(plan: dict, contemplated_action_at_utc: str | None = None) -> str:
    c, _ = contract_guard()
    required_identity = c["plan_identity"]["required_fields"]
    for key in required_identity:
        require_nonempty(plan, key, "PLAN")

    if not CANONICAL_SECURITY.fullmatch(plan["canonical_security_id"]):
        raise RuntimeError("PLAN_CANONICAL_SECURITY_INVALID")
    if plan["frozen_before_current_action"] is not True:
        raise RuntimeError("PLAN_NOT_FROZEN_BEFORE_CURRENT_ACTION")
    if plan.get("order_execution_authorized") is not False:
        raise RuntimeError("PLAN_ORDER_EXECUTION_MUST_BE_FALSE")
    if plan.get("brokerage_execution_authorized") is not False:
        raise RuntimeError("PLAN_BROKERAGE_EXECUTION_MUST_BE_FALSE")

    created = parse_utc(plan["created_at_utc"])
    frozen = parse_utc(plan["frozen_at_utc"])
    if frozen < created:
        raise RuntimeError("PLAN_FROZEN_BEFORE_CREATED")
    if contemplated_action_at_utc is not None and frozen >= parse_utc(contemplated_action_at_utc):
        raise RuntimeError("PLAN_NOT_PRECOMMITTED_BEFORE_ACTION_TIMESTAMP")

    for family in c["required_rule_families"]:
        if family not in plan:
            raise RuntimeError(f"PLAN_RULE_FAMILY_MISSING:{family}")

    thesis = plan["thesis"]
    for key in c["thesis"]["required_fields"]:
        require_nonempty(thesis, key, "THESIS")

    invalidation = plan["thesis_invalidation"]
    conditions = invalidation.get("conditions")
    if not isinstance(conditions, list) or len(conditions) < c["thesis_invalidation"]["minimum_conditions"]:
        raise RuntimeError("INVALIDATION_CONDITION_REQUIRED")
    for condition in conditions:
        for key in c["thesis_invalidation"]["condition_schema"]:
            require_nonempty(condition, key, "INVALIDATION")
        if condition["on_trigger_state"] != c["thesis_invalidation"]["on_trigger_state_required"]:
            raise RuntimeError("INVALIDATION_TRIGGER_STATE_INVALID")
        if condition["unknown_state"] == "PASS":
            raise RuntimeError("INVALIDATION_UNKNOWN_DEFAULT_PASS_FORBIDDEN")

    stop = plan["stop"]
    validate_common_rule(stop, "stop", c)
    if stop["when_satisfied_state"] != c["stop"]["on_trigger_state_required"]:
        raise RuntimeError("STOP_TRIGGER_STATE_INVALID")

    take = plan["take_profit"]
    validate_common_rule(take, "take_profit", c)
    if take["when_satisfied_state"] != c["take_profit"]["on_trigger_state_required"]:
        raise RuntimeError("TAKE_PROFIT_TRIGGER_STATE_INVALID")

    add = plan["add_position"]
    validate_common_rule(add, "add_position", c)
    for key in c["add_position"]["must_define"]:
        require_nonempty(add, key, "ADD_POSITION")
    if add["when_satisfied_state"] != c["add_position"]["required_supported_state"]:
        raise RuntimeError("ADD_POSITION_SUPPORTED_STATE_INVALID")
    if add["when_not_satisfied_state"] != c["add_position"]["default_if_conditions_missing"]:
        raise RuntimeError("ADD_POSITION_FAILURE_STATE_INVALID")
    prohibited_add_basis = {
        "PRICE_FELL_SO_AVERAGE_COST_ONLY",
        "HOPE_FOR_REBOUND",
        "FOMO",
        "UNRECORDED_SUBJECTIVE_OVERRIDE",
    }
    eligibility_tokens = {str(x).strip().upper() for x in add["eligibility_conditions"]}
    if eligibility_tokens and eligibility_tokens.issubset(prohibited_add_basis):
        raise RuntimeError("ADD_POSITION_ONLY_EMOTIONAL_OR_PRICE_DECLINE_BASIS_FORBIDDEN")

    reduce_rule = plan["reduce_exposure"]
    validate_common_rule(reduce_rule, "reduce_exposure", c)
    if reduce_rule["when_satisfied_state"] != c["reduce_exposure"]["on_trigger_state_required"]:
        raise RuntimeError("REDUCE_EXPOSURE_TRIGGER_STATE_INVALID")

    risk = plan["risk_budget"]
    for key in c["risk_budget"]["must_define"]:
        require_nonempty(risk, key, "RISK_BUDGET")
    if risk["breach_state"] != c["risk_budget"]["breach_state_required"]:
        raise RuntimeError("RISK_BUDGET_BREACH_STATE_INVALID")
    if risk.get("position_sizing_output_semantics") != c["risk_budget"]["position_sizing_output_semantics"]:
        raise RuntimeError("RISK_BUDGET_POSITION_SIZING_SEMANTICS_INVALID")

    exposure = plan["position_or_exposure_limit"]
    for key in c["position_or_exposure_limit"]["must_define"]:
        require_nonempty(exposure, key, "EXPOSURE_LIMIT")
    if exposure["breach_state"] != c["position_or_exposure_limit"]["breach_state_required"]:
        raise RuntimeError("EXPOSURE_LIMIT_BREACH_STATE_INVALID")

    unknown = plan["unknown_data_policy"]
    if unknown.get("cannot_default_to_pass") is not True:
        raise RuntimeError("UNKNOWN_POLICY_MUST_BLOCK_PASS_DEFAULT")
    if unknown.get("required_input_unknown_behavior") not in set(c["unknown_data_policy"]["allowed_resolution_states"]):
        raise RuntimeError("UNKNOWN_POLICY_STATE_INVALID")

    amendment = plan["amendment_policy"]
    if amendment.get("append_only_versions") is not True or amendment.get("original_plan_preserved") is not True:
        raise RuntimeError("AMENDMENT_HISTORY_MUST_BE_APPEND_ONLY")
    version = int(str(plan["discipline_plan_version"]))
    permitted = set(c["amendment_policy"]["permitted_bases"])
    forbidden = set(c["amendment_policy"]["forbidden_bases"])
    basis = str(amendment.get("amendment_basis") or "")
    if basis in forbidden:
        raise RuntimeError("AMENDMENT_BASIS_FORBIDDEN")
    if version == 1:
        if plan.get("supersedes_plan_id"):
            raise RuntimeError("VERSION1_CANNOT_SUPERSEDE_PLAN")
    else:
        require_nonempty(plan, "supersedes_plan_id", "PLAN")
        require_nonempty(amendment, "amendment_reason", "AMENDMENT")
        if basis not in permitted:
            raise RuntimeError("AMENDMENT_BASIS_NOT_PERMITTED")
        require_nonempty(amendment, "risk_change_direction", "AMENDMENT")

    if plan["discipline_plan_id"] != expected_plan_id(plan):
        raise RuntimeError("DISCIPLINE_PLAN_ID_MISMATCH")
    prehash = copy.deepcopy(plan)
    claimed = prehash.pop("plan_sha256")
    if canonical_sha(prehash) != claimed:
        raise RuntimeError("DISCIPLINE_PLAN_SHA_MISMATCH")
    return "PASS_PRECOMMITTED_DISCIPLINE_PLAN"


def synthetic_plan() -> dict:
    plan = {
        "discipline_plan_id": "",
        "discipline_plan_version": "1",
        "canonical_security_id": "SZSE:300001",
        "strategy_or_setup_spec_id": "SYNTHETIC_SETUP_SPEC_V1",
        "created_at_utc": "2026-09-28T06:00:00Z",
        "frozen_at_utc": "2026-09-28T06:01:00Z",
        "frozen_before_current_action": True,
        "supersedes_plan_id": "",
        "thesis": {
            "statement": "Synthetic thesis for interface validation only.",
            "evidence_required_to_remain_valid": ["Synthetic causal evidence remains valid"],
            "time_horizon_or_review_condition": "Review on synthetic evidence-state change",
        },
        "thesis_invalidation": {
            "conditions": [{
                "condition_id": "INV-001",
                "condition": "Synthetic material evidence invalidation",
                "evidence_source_or_measure": "synthetic://evidence",
                "on_trigger_state": "THESIS_INVALIDATED_REQUIRES_HUMAN_REVIEW",
                "unknown_state": "UNKNOWN_INSUFFICIENT_EVIDENCE",
            }]
        },
        "stop": {
            "rule_id": "STOP-001",
            "enabled": True,
            "trigger_or_condition": "Synthetic frozen stop condition",
            "evaluation_basis": "synthetic://risk-state",
            "when_satisfied_state": "EXIT_CONDITION_TRIGGERED_REQUIRES_HUMAN_CONFIRMATION",
            "when_not_satisfied_state": "RESEARCH_MONITORING_STATE_UNCHANGED",
            "when_unknown_state": "REQUIRES_HUMAN_REVIEW",
            "rationale": "Synthetic downside discipline",
            "switching_or_tightening_rule": "May tighten only on PRECOMMITTED_SWITCH_RULE_TRIGGERED",
        },
        "take_profit": {
            "rule_id": "TP-001",
            "enabled": True,
            "trigger_or_condition": "Synthetic frozen take-profit condition",
            "evaluation_basis": "synthetic://research-state",
            "when_satisfied_state": "EXIT_CONDITION_TRIGGERED_REQUIRES_HUMAN_CONFIRMATION",
            "when_not_satisfied_state": "RESEARCH_MONITORING_STATE_UNCHANGED",
            "when_unknown_state": "REQUIRES_HUMAN_REVIEW",
            "rationale": "Synthetic profit discipline",
            "switching_rule": "Synthetic precommitted trailing switch",
        },
        "add_position": {
            "rule_id": "ADD-001",
            "enabled": True,
            "trigger_or_condition": "ALL eligibility_conditions must be satisfied",
            "evaluation_basis": "synthetic://evidence-and-risk",
            "when_satisfied_state": "ADD_POSITION_PRECONDITIONS_SATISFIED_REQUIRES_HUMAN_CONFIRMATION",
            "when_not_satisfied_state": "ADD_POSITION_NOT_SUPPORTED_BY_FROZEN_RULES",
            "when_unknown_state": "ACTION_NOT_SUPPORTED_BY_FROZEN_RULES",
            "rationale": "Synthetic add discipline",
            "eligibility_conditions": ["NEW_EVIDENCE_SUPPORTS_THESIS", "RISK_BUDGET_WITHIN_LIMIT"],
            "maximum_add_events": 1,
            "maximum_incremental_exposure": "5pct_synthetic",
            "maximum_total_exposure_after_add": "10pct_synthetic",
            "disallowed_rationales": ["PRICE_FELL_SO_AVERAGE_COST_ONLY", "HOPE_FOR_REBOUND", "FOMO", "UNRECORDED_SUBJECTIVE_OVERRIDE"],
        },
        "reduce_exposure": {
            "rule_id": "REDUCE-001",
            "enabled": True,
            "trigger_or_condition": "Synthetic risk deterioration",
            "evaluation_basis": "synthetic://risk-state",
            "when_satisfied_state": "REDUCE_EXPOSURE_CONDITION_TRIGGERED_REQUIRES_HUMAN_CONFIRMATION",
            "when_not_satisfied_state": "RESEARCH_MONITORING_STATE_UNCHANGED",
            "when_unknown_state": "REQUIRES_HUMAN_REVIEW",
            "rationale": "Synthetic exposure discipline",
        },
        "risk_budget": {
            "risk_budget_measure": "synthetic_max_loss_budget",
            "maximum_risk_budget": "1pct_synthetic",
            "breach_state": "ACTION_NOT_SUPPORTED_BY_FROZEN_RULES",
            "position_sizing_output_semantics": "HYPOTHETICAL_OR_RULE_CONSTRAINED_SIZE_NOT_ORDER_QUANTITY",
        },
        "position_or_exposure_limit": {
            "exposure_measure": "synthetic_single_security_exposure",
            "maximum_exposure": "10pct_synthetic",
            "breach_state": "ACTION_NOT_SUPPORTED_BY_FROZEN_RULES",
        },
        "unknown_data_policy": {
            "required_input_unknown_behavior": "UNKNOWN_INSUFFICIENT_EVIDENCE",
            "cannot_default_to_pass": True,
        },
        "amendment_policy": {
            "append_only_versions": True,
            "original_plan_preserved": True,
            "permitted_bases": read_json(CONTRACT)["amendment_policy"]["permitted_bases"],
            "forbidden_bases": read_json(CONTRACT)["amendment_policy"]["forbidden_bases"],
            "amendment_reason": "",
            "amendment_basis": "",
            "risk_change_direction": "UNCHANGED",
        },
        "order_execution_authorized": False,
        "brokerage_execution_authorized": False,
        "plan_sha256": "",
    }
    return finalize_hashes(plan)


def reh(plan: dict) -> dict:
    return finalize_hashes(plan)


def self_test() -> dict:
    c, _ = contract_guard()
    tests = []

    def check(name: str, ok: bool):
        tests.append({"name": name, "pass": bool(ok)})

    action_at = "2026-09-28T06:30:00Z"
    base = synthetic_plan()
    check("D01_complete_plan_passes", validate_plan(base, action_at) == "PASS_PRECOMMITTED_DISCIPLINE_PLAN")

    for name, family in [
        ("D02_missing_stop_fails", "stop"),
        ("D03_missing_take_profit_fails", "take_profit"),
        ("D04_missing_invalidation_fails", "thesis_invalidation"),
        ("D05_missing_add_position_fails", "add_position"),
        ("D06_missing_risk_budget_fails", "risk_budget"),
        ("D07_missing_exposure_limit_fails", "position_or_exposure_limit"),
    ]:
        failed = False
        try:
            x = copy.deepcopy(base); del x[family]; x = reh(x); validate_plan(x, action_at)
        except Exception:
            failed = True
        check(name, failed)

    late = False
    try:
        x = copy.deepcopy(base); x["frozen_at_utc"] = "2026-09-28T06:31:00Z"; x = reh(x); validate_plan(x, action_at)
    except RuntimeError:
        late = True
    check("D08_plan_frozen_after_action_fails", late)

    unknown_pass = False
    try:
        x = copy.deepcopy(base); x["unknown_data_policy"]["cannot_default_to_pass"] = False; x = reh(x); validate_plan(x, action_at)
    except RuntimeError:
        unknown_pass = True
    check("D09_unknown_cannot_default_to_pass", unknown_pass)

    averaging_down = False
    try:
        x = copy.deepcopy(base); x["add_position"]["eligibility_conditions"] = ["PRICE_FELL_SO_AVERAGE_COST_ONLY"]; x = reh(x); validate_plan(x, action_at)
    except RuntimeError:
        averaging_down = True
    check("D10_price_decline_only_cannot_support_add", averaging_down)

    hope_amendment = False
    try:
        x = copy.deepcopy(base)
        old_id = x["discipline_plan_id"]
        x["discipline_plan_version"] = "2"; x["supersedes_plan_id"] = old_id
        x["frozen_at_utc"] = "2026-09-28T06:10:00Z"
        x["amendment_policy"]["amendment_reason"] = "Avoid realizing synthetic loss"
        x["amendment_policy"]["amendment_basis"] = "HOPE_FOR_REBOUND_AFTER_LOSS"
        x["amendment_policy"]["risk_change_direction"] = "LOOSEN"
        x = reh(x); validate_plan(x, action_at)
    except RuntimeError:
        hope_amendment = True
    check("D11_hope_based_stop_loosening_amendment_fails", hope_amendment)

    x = copy.deepcopy(base)
    old_id = x["discipline_plan_id"]
    x["discipline_plan_version"] = "2"; x["supersedes_plan_id"] = old_id
    x["frozen_at_utc"] = "2026-09-28T06:10:00Z"
    x["stop"]["trigger_or_condition"] = "Synthetic tighter stop under preregistered switch"
    x["amendment_policy"]["amendment_reason"] = "Synthetic precommitted tightening switch triggered"
    x["amendment_policy"]["amendment_basis"] = "PRECOMMITTED_SWITCH_RULE_TRIGGERED"
    x["amendment_policy"]["risk_change_direction"] = "TIGHTEN"
    x = reh(x)
    check("D12_precommitted_tightening_new_version_passes", validate_plan(x, action_at) == "PASS_PRECOMMITTED_DISCIPLINE_PLAN" and x["supersedes_plan_id"] == old_id)
    check("D13_old_plan_hash_preserved_by_new_version", base["plan_sha256"] != x["plan_sha256"] and base["discipline_plan_id"] == old_id)

    order_block = False
    try:
        y = copy.deepcopy(base); y["order_execution_authorized"] = True; y = reh(y); validate_plan(y, action_at)
    except RuntimeError:
        order_block = True
    check("D14_order_execution_authority_rejected", order_block)

    broker_block = False
    try:
        y = copy.deepcopy(base); y["brokerage_execution_authorized"] = True; y = reh(y); validate_plan(y, action_at)
    except RuntimeError:
        broker_block = True
    check("D15_brokerage_execution_authority_rejected", broker_block)

    tmpl = read_json(TEMPLATE)
    check("D16_template_is_not_real_security_plan", tmpl["template_only"] is True and tmpl["not_a_real_security_plan"] is True)
    check("D17_packet_activation_still_separate", c["packet_activation_gate"]["real_packet_generation_authorized_now"] is False and c["packet_activation_gate"]["activation_requires_separate_receipt"] is True)
    check("D18_shadow_accumulation_remains_active", read_json(SHADOW_ACTIVATION)["status"] == "ACTIVE_PROSPECTIVE_SHADOW_ACCUMULATION")

    source = Path(__file__).read_text(encoding="utf-8").split("def self_test():")[0].lower()
    check("D19_no_broker_order_execution_code", all(t not in source for t in ["submit_order(", "place_order(", "broker_client", "brokerage_api"]))

    result = {
        "schema": "AI_CORE_EVID_V2_8_12_PRECOMMITTED_DISCIPLINE_PLAN_SELFTEST_V1",
        "tests": tests,
        "passed": sum(t["pass"] for t in tests),
        "total": len(tests),
        "all_pass": all(t["pass"] for t in tests),
        "real_discipline_plan_created": False,
        "real_candidate_packet_generated": False,
        "price_or_return_data_consumed": False,
        "brokerage_or_order_action_executed": False,
        "shadow_accumulation_modified": False,
        "fold3_4_accessed": False,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["all_pass"]:
        raise SystemExit(2)
    return result


if __name__ == "__main__":
    self_test()
