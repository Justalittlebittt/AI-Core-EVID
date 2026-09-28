from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

CONTRACT = Path("evidence/V2.8.12_HUMAN_REVIEW_PACKET_CONTRACT.json")
HUMAN_GATE = Path("evidence/V2.8.12_HUMAN_DECISION_GATE_CONTRACT.json")
SEMANTIC_SUPERSESSION = Path("evidence/V2.8.12_DOWNSTREAM_DECISION_SEMANTICS_SUPERSESSION.json")
SHADOW_ACTIVATION = Path("evidence/V2.8.12_SHADOW_ACCUMULATION_ACTIVATION.json")


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def canonical_sha(obj: dict) -> str:
    return hashlib.sha256(
        json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def contract_guard() -> tuple[dict, dict, dict]:
    c = read_json(CONTRACT)
    h = read_json(HUMAN_GATE)
    s = read_json(SEMANTIC_SUPERSESSION)
    if c.get("status") != "FROZEN_BEFORE_PACKET_INTERFACE_VALIDATION":
        raise RuntimeError("HUMAN_REVIEW_PACKET_CONTRACT_NOT_FROZEN")
    if h.get("status") != "FROZEN_DOWNSTREAM_HUMAN_DECISION_BOUNDARY":
        raise RuntimeError("HUMAN_DECISION_GATE_NOT_FROZEN")
    if s.get("status") != "ACTIVE_PROSPECTIVE_SEMANTIC_SUPERSESSION":
        raise RuntimeError("SEMANTIC_SUPERSESSION_NOT_ACTIVE")
    return c, h, s


def recursive_tokens(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield str(k)
            yield from recursive_tokens(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from recursive_tokens(v)
    elif isinstance(obj, str):
        yield obj


def build_packet(payload: dict) -> dict:
    c, _, _ = contract_guard()
    packet = copy.deepcopy(payload)
    packet.setdefault("capital_action_related", True)
    packet.setdefault("requires_human_decision", True)
    packet.setdefault("order_execution_authorized", False)
    packet.setdefault("human_decision", {"status": "UNSET", "override_reason": ""})

    identity_material = {
        "canonical_security_id": packet.get("canonical_security_id"),
        "research_as_of_date": packet.get("research_as_of_date"),
        "research_state": packet.get("research_state"),
        "frozen_discipline_plan": packet.get("frozen_discipline_plan"),
    }
    packet["packet_id"] = canonical_sha(identity_material)
    prehash = copy.deepcopy(packet)
    prehash.pop("packet_sha256", None)
    packet["packet_sha256"] = canonical_sha(prehash)
    validate_packet(packet, generation_phase=True)
    return packet


def validate_packet(packet: dict, generation_phase: bool = True) -> str:
    c, h, _ = contract_guard()

    for key in c["packet_schema"]["required_top_level_fields"]:
        if key not in packet:
            raise RuntimeError(f"PACKET_REQUIRED_FIELD_MISSING:{key}")

    if packet.get("capital_action_related") is not True:
        raise RuntimeError("PACKET_CAPITAL_ACTION_FLAG_MUST_BE_TRUE")
    if packet.get("requires_human_decision") is not True:
        raise RuntimeError("PACKET_HUMAN_DECISION_REQUIRED")
    if packet.get("order_execution_authorized") is not False:
        raise RuntimeError("PACKET_ORDER_EXECUTION_MUST_BE_FALSE")

    prohibited = set(h["prohibited_executable_statuses"])
    if str(packet.get("research_state")) in prohibited:
        raise RuntimeError("PACKET_PROHIBITED_EXECUTABLE_STATE")

    for token in recursive_tokens(packet):
        if token in prohibited:
            raise RuntimeError(f"PACKET_PROHIBITED_EXECUTABLE_TOKEN:{token}")

    provenance = packet["research_provenance"]
    for key in c["research_provenance"]["required"]:
        if not str(provenance.get(key) or "").strip():
            raise RuntimeError(f"PACKET_PROVENANCE_MISSING:{key}")

    snapshot = packet["research_snapshot"]
    for key in c["research_snapshot"]["required"]:
        if key not in snapshot:
            raise RuntimeError(f"PACKET_RESEARCH_SNAPSHOT_MISSING:{key}")

    plan = packet["frozen_discipline_plan"]
    for key in c["frozen_discipline_plan"]["required"]:
        if key not in plan:
            raise RuntimeError(f"PACKET_DISCIPLINE_PLAN_MISSING:{key}")
    if plan.get("rule_snapshot_frozen_before_current_action") is not True:
        raise RuntimeError("PACKET_DISCIPLINE_PLAN_NOT_PRECOMMITTED")

    rc = packet["rule_conformance"]
    allowed_check_values = set(c["rule_conformance"]["allowed_values"])
    for key in c["rule_conformance"]["required_checks"]:
        if key not in rc:
            raise RuntimeError(f"PACKET_RULE_CHECK_MISSING:{key}")
        if rc[key] not in allowed_check_values:
            raise RuntimeError(f"PACKET_RULE_CHECK_INVALID:{key}:{rc[key]}")

    if packet["research_state"] not in set(c["rule_conformance"]["overall_rule_state"]):
        raise RuntimeError("PACKET_RESEARCH_STATE_NOT_CANONICAL")

    # Unknown evidence must remain explicit and cannot be presented as an all-clear packet.
    if any(v == "UNKNOWN_INSUFFICIENT_EVIDENCE" for v in rc.values()):
        if packet["research_state"] in {
            "RESEARCH_CONDITIONS_SATISFIED",
            "ADD_POSITION_PRECONDITIONS_SATISFIED_REQUIRES_HUMAN_CONFIRMATION",
        }:
            raise RuntimeError("PACKET_UNKNOWN_COERCED_TO_POSITIVE_STATE")

    # Any failed add-position prerequisite cannot coexist with an add-supported state.
    if rc.get("add_position_preconditions_satisfied") == "FAIL" and packet["research_state"] == "ADD_POSITION_PRECONDITIONS_SATISFIED_REQUIRES_HUMAN_CONFIRMATION":
        raise RuntimeError("PACKET_ADD_POSITION_STATE_CONTRADICTS_RULE_CHECK")

    # A triggered thesis invalidation or exit state may be surfaced, but never executed.
    if packet["research_state"] in {
        "THESIS_INVALIDATED_REQUIRES_HUMAN_REVIEW",
        "EXIT_CONDITION_TRIGGERED_REQUIRES_HUMAN_CONFIRMATION",
        "REDUCE_EXPOSURE_CONDITION_TRIGGERED_REQUIRES_HUMAN_CONFIRMATION",
    } and packet["order_execution_authorized"] is not False:
        raise RuntimeError("PACKET_TRIGGERED_STATE_CANNOT_AUTHORIZE_ORDER")

    flags = packet["behavioral_discipline_flags"]
    if not isinstance(flags, list) or not flags:
        raise RuntimeError("PACKET_BEHAVIORAL_FLAGS_REQUIRED")
    allowed_flags = set(c["behavioral_discipline_flags"]["standard_flags"])
    if any(f not in allowed_flags for f in flags):
        raise RuntimeError("PACKET_BEHAVIORAL_FLAG_UNKNOWN")

    human = packet["human_decision"]
    if human.get("status") not in set(c["human_decision"]["allowed_statuses"]):
        raise RuntimeError("PACKET_HUMAN_DECISION_STATUS_INVALID")
    if generation_phase and human.get("status") != "UNSET":
        raise RuntimeError("PACKET_MUST_DEFAULT_TO_UNSET_HUMAN_DECISION")
    if human.get("status") == "USER_OVERRIDE_OF_FROZEN_RULES_RECORDED" and not str(human.get("override_reason") or "").strip():
        raise RuntimeError("PACKET_USER_OVERRIDE_REASON_REQUIRED")

    if not packet.get("packet_id") or len(packet["packet_id"]) != 64:
        raise RuntimeError("PACKET_ID_INVALID")
    if not packet.get("packet_sha256") or len(packet["packet_sha256"]) != 64:
        raise RuntimeError("PACKET_SHA_INVALID")

    prehash = copy.deepcopy(packet)
    claimed = prehash.pop("packet_sha256")
    if canonical_sha(prehash) != claimed:
        raise RuntimeError("PACKET_SHA_MISMATCH")

    expected_packet_id = canonical_sha({
        "canonical_security_id": packet.get("canonical_security_id"),
        "research_as_of_date": packet.get("research_as_of_date"),
        "research_state": packet.get("research_state"),
        "frozen_discipline_plan": packet.get("frozen_discipline_plan"),
    })
    if packet["packet_id"] != expected_packet_id:
        raise RuntimeError("PACKET_ID_MISMATCH")

    return "PASS_HUMAN_REVIEW_PACKET_INTERFACE"


def synthetic_payload(state: str = "RESEARCH_CONDITIONS_SATISFIED") -> dict:
    return {
        "packet_created_at_utc": "2026-09-28T06:30:00Z",
        "canonical_security_id": "SZSE:300001",
        "research_as_of_date": "2026-09-28",
        "research_state": state,
        "capital_action_related": True,
        "requires_human_decision": True,
        "order_execution_authorized": False,
        "research_provenance": {
            "U_authority": "synthetic://U/PASS",
            "E_authority": "synthetic://E/PASS",
            "T_authority": "synthetic://T/STATE",
            "X_authority": "synthetic://X/RISK",
            "strategy_or_setup_receipt": "synthetic://strategy/PASS",
            "human_decision_gate_contract": str(HUMAN_GATE),
        },
        "research_snapshot": {
            "U_state": "PASS",
            "E_state": "PASS",
            "T_state": "RESEARCH_STATE_ONLY",
            "X_state": "WITHIN_SYNTHETIC_LIMITS",
            "setup_or_strategy_state": "PASS_SYNTHETIC",
            "evidence_for": ["synthetic evidence for"],
            "evidence_against": ["synthetic counterevidence"],
            "missing_or_uncertain": [],
            "risk_summary": "Synthetic interface validation only; no market data consumed.",
        },
        "frozen_discipline_plan": {
            "thesis": "Synthetic thesis frozen before contemplated action.",
            "thesis_invalidation_conditions": ["Synthetic invalidation condition"],
            "stop_rule": "Synthetic precommitted stop rule",
            "take_profit_rule": "Synthetic precommitted take-profit rule",
            "add_position_rule": "Synthetic add-position rule",
            "reduce_exposure_rule": "Synthetic reduce-exposure rule",
            "maximum_risk_budget_rule": "Synthetic risk budget",
            "maximum_position_or_exposure_rule": "Synthetic exposure cap",
            "rule_snapshot_frozen_before_current_action": True,
        },
        "rule_conformance": {
            "thesis_still_valid": "PASS",
            "invalidation_triggered": "NOT_APPLICABLE",
            "stop_condition_triggered": "NOT_APPLICABLE",
            "take_profit_condition_triggered": "NOT_APPLICABLE",
            "add_position_preconditions_satisfied": "NOT_APPLICABLE",
            "reduce_exposure_condition_triggered": "NOT_APPLICABLE",
            "risk_budget_within_limit": "PASS",
            "position_or_exposure_within_limit": "PASS",
            "contemplated_action_supported_by_frozen_rules": "PASS",
        },
        "behavioral_discipline_flags": ["NO_BEHAVIORAL_DEVIATION_DETECTED"],
        "human_decision": {"status": "UNSET", "override_reason": ""},
    }


def self_test() -> dict:
    tests = []

    def check(name: str, ok: bool):
        tests.append({"name": name, "pass": bool(ok)})

    c, _, _ = contract_guard()
    shadow = read_json(SHADOW_ACTIVATION)

    p = build_packet(synthetic_payload())
    check("P01_complete_packet_validates", validate_packet(p) == "PASS_HUMAN_REVIEW_PACKET_INTERFACE")
    check("P02_human_decision_defaults_unset", p["human_decision"]["status"] == "UNSET")
    check("P03_order_execution_false", p["order_execution_authorized"] is False)

    auto_block = False
    try:
        build_packet(synthetic_payload("AUTO_BUY"))
    except RuntimeError:
        auto_block = True
    check("P04_auto_buy_rejected", auto_block)

    execution_block = False
    try:
        x = synthetic_payload(); x["order_execution_authorized"] = True; build_packet(x)
    except RuntimeError:
        execution_block = True
    check("P05_order_execution_true_rejected", execution_block)

    no_human_block = False
    try:
        x = synthetic_payload(); x["requires_human_decision"] = False; build_packet(x)
    except RuntimeError:
        no_human_block = True
    check("P06_missing_human_gate_rejected", no_human_block)

    e_only_block = False
    try:
        x = synthetic_payload(); x["research_provenance"]["strategy_or_setup_receipt"] = ""; build_packet(x)
    except RuntimeError:
        e_only_block = True
    check("P07_E_only_without_strategy_receipt_rejected", e_only_block)

    plan_block = False
    try:
        x = synthetic_payload(); del x["frozen_discipline_plan"]["stop_rule"]; build_packet(x)
    except RuntimeError:
        plan_block = True
    check("P08_missing_precommitted_plan_rejected", plan_block)

    unknown_block = False
    try:
        x = synthetic_payload(); x["rule_conformance"]["risk_budget_within_limit"] = "UNKNOWN_INSUFFICIENT_EVIDENCE"; build_packet(x)
    except RuntimeError:
        unknown_block = True
    check("P09_unknown_not_coerced_to_positive", unknown_block)

    add = synthetic_payload("ADD_POSITION_NOT_SUPPORTED_BY_FROZEN_RULES")
    add["rule_conformance"]["add_position_preconditions_satisfied"] = "FAIL"
    add["rule_conformance"]["contemplated_action_supported_by_frozen_rules"] = "FAIL"
    add["behavioral_discipline_flags"] = ["AVERAGING_DOWN_WITHOUT_PRECOMMITTED_BASIS"]
    addp = build_packet(add)
    check("P10_unsupported_add_position_packet_allowed_as_warning", addp["research_state"] == "ADD_POSITION_NOT_SUPPORTED_BY_FROZEN_RULES")
    check("P11_unsupported_add_preserves_original_plan", addp["frozen_discipline_plan"]["rule_snapshot_frozen_before_current_action"] is True)

    exitp = synthetic_payload("EXIT_CONDITION_TRIGGERED_REQUIRES_HUMAN_CONFIRMATION")
    exitp["rule_conformance"]["stop_condition_triggered"] = "PASS"
    exitp = build_packet(exitp)
    check("P12_exit_trigger_still_no_order_authority", exitp["order_execution_authorized"] is False and exitp["requires_human_decision"] is True)

    override = copy.deepcopy(p)
    override["human_decision"] = {"status": "USER_OVERRIDE_OF_FROZEN_RULES_RECORDED", "override_reason": "Synthetic explicit user reason"}
    prehash = copy.deepcopy(override); prehash.pop("packet_sha256", None)
    override["packet_sha256"] = canonical_sha(prehash)
    check("P13_user_override_can_be_recorded_without_rewriting_plan", validate_packet(override, generation_phase=False) == "PASS_HUMAN_REVIEW_PACKET_INTERFACE")

    check("P14_shadow_accumulation_still_active", shadow["status"] == "ACTIVE_PROSPECTIVE_SHADOW_ACCUMULATION")
    check("P15_real_packet_generation_not_yet_authorized", c["governance"]["real_candidate_packet_generation_authorized"] is False)
    check("P16_decision_log_not_yet_activated", c["governance"]["decision_discipline_log_activation_authorized"] is False)

    source = Path(__file__).read_text(encoding="utf-8").split("def self_test():")[0].lower()
    check("P17_no_broker_or_order_execution_code", all(t not in source for t in ["submit_order(", "place_order(", "brokerage_api", "broker_client"]))

    result = {
        "schema": "AI_CORE_EVID_V2_8_12_HUMAN_REVIEW_PACKET_SELFTEST_V1",
        "tests": tests,
        "passed": sum(t["pass"] for t in tests),
        "total": len(tests),
        "all_pass": all(t["pass"] for t in tests),
        "real_candidate_packet_generated": False,
        "price_or_return_data_consumed": False,
        "brokerage_or_order_action_executed": False,
        "decision_log_modified": False,
        "shadow_accumulation_modified": False,
        "fold3_4_accessed": False,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["all_pass"]:
        raise SystemExit(2)
    return result


if __name__ == "__main__":
    self_test()
