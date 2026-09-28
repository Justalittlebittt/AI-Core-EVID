from __future__ import annotations

import json
from pathlib import Path

CONTRACT = Path("evidence/V2.8.12_HUMAN_DECISION_GATE_CONTRACT.json")
SUPERSESSION = Path("evidence/V2.8.12_DOWNSTREAM_DECISION_SEMANTICS_SUPERSESSION.json")
SETUP_ENVELOPE = Path("evidence/V2.8.4_SETUP_ADMISSION_ENVELOPE_CONTRACT.json")
SHADOW_ACTIVATION = Path("evidence/V2.8.12_SHADOW_ACCUMULATION_ACTIVATION.json")
ACTIVE_E_WORKFLOW = Path(".github/workflows/v284-controlled-prospective-e-layer.yml")


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def contract_guard() -> tuple[dict, dict]:
    c = read_json(CONTRACT)
    s = read_json(SUPERSESSION)
    if c.get("status") != "FROZEN_DOWNSTREAM_HUMAN_DECISION_BOUNDARY":
        raise RuntimeError("HUMAN_DECISION_CONTRACT_NOT_FROZEN")
    if s.get("status") != "ACTIVE_PROSPECTIVE_SEMANTIC_SUPERSESSION":
        raise RuntimeError("DOWNSTREAM_SUPERSESSION_NOT_ACTIVE")
    if s.get("authority") != str(CONTRACT):
        raise RuntimeError("DOWNSTREAM_SUPERSESSION_AUTHORITY_MISMATCH")
    return c, s


def validate_active_research_architecture() -> dict:
    c, _ = contract_guard()
    setup = read_json(SETUP_ENVELOPE)
    shadow = read_json(SHADOW_ACTIVATION)
    workflow = ACTIVE_E_WORKFLOW.read_text(encoding="utf-8")

    checks = {
        "setup_envelope_remains_dry": (
            setup["output"]["first60_append_authorized"] is False
            and setup["output"]["episode_emission_authorized"] is False
            and setup["output"]["live_authorized"] is False
        ),
        "shadow_has_no_outcome_authority": shadow["governance"]["outcome_research_authorized"] is False,
        "shadow_has_no_setup_live_authority": (
            shadow["governance"]["setup_emission_authorized"] is False
            and shadow["governance"]["first60_append_authorized"] is False
            and shadow["governance"]["episode_emission_authorized"] is False
            and shadow["governance"]["live_authorized"] is False
        ),
        "human_gate_requires_user_decision": (
            c["human_decision_gate"]["final_decision_authority"] == "USER"
            and c["human_decision_gate"]["required_for_every_capital_action"] is True
        ),
        "human_gate_disables_order_execution": (
            c["human_decision_gate"]["order_execution_authorized"] is False
            and c["human_decision_gate"]["brokerage_connector_authorized"] is False
        ),
        "active_e_workflow_has_no_broker_execution": all(
            token not in workflow.lower()
            for token in ["brokerage", "submit_order", "place_order", "execute_trade"]
        ),
    }
    if not all(checks.values()):
        raise RuntimeError("ACTIVE_RESEARCH_ARCHITECTURE_BOUNDARY_FAIL")
    return checks


def validate_downstream_output(payload: dict) -> str:
    c, _ = contract_guard()
    prohibited = set(c["prohibited_executable_statuses"])
    status = str(payload.get("research_state") or payload.get("status") or "").strip()
    if status in prohibited:
        raise RuntimeError(f"PROHIBITED_EXECUTABLE_STATUS:{status}")
    if payload.get("order_execution_authorized") is True:
        raise RuntimeError("ORDER_EXECUTION_AUTHORIZATION_FORBIDDEN")
    if payload.get("brokerage_execution_authorized") is True:
        raise RuntimeError("BROKERAGE_EXECUTION_AUTHORIZATION_FORBIDDEN")

    capital_action = bool(payload.get("capital_action_related"))
    if capital_action:
        if payload.get("requires_human_decision") is not True:
            raise RuntimeError("CAPITAL_ACTION_REQUIRES_HUMAN_DECISION")
        if payload.get("order_execution_authorized") is not False:
            raise RuntimeError("CAPITAL_ACTION_MUST_EXPLICITLY_DISABLE_ORDER_EXECUTION")
        if not str(payload.get("rule_basis") or "").strip():
            raise RuntimeError("CAPITAL_ACTION_RULE_BASIS_REQUIRED")
    return "PASS_HUMAN_DECISION_BOUNDARY"


def self_test() -> dict:
    tests = []

    def check(name: str, condition: bool):
        tests.append({"name": name, "pass": bool(condition)})

    active = validate_active_research_architecture()
    check("H01_active_research_architecture_boundary_pass", all(active.values()))

    c, s = contract_guard()
    check(
        "H02_setup_pass_is_research_state",
        s["semantic_migrations"]["Setup_PASS"]["new_interpretation"] == "RESEARCH_CONDITIONS_SATISFIED",
    )
    check(
        "H03_first60_is_research_monitoring",
        s["semantic_migrations"]["First60"]["prospective_interpretation"] == "POST_ADMISSION_RESEARCH_MONITORING_WINDOW",
    )
    check(
        "H04_episode_is_not_broker_position",
        "BROKERAGE_POSITION" in s["semantic_migrations"]["Episode"]["not_equivalent_to"],
    )

    good_setup = {
        "research_state": "RESEARCH_CONDITIONS_SATISFIED",
        "capital_action_related": True,
        "rule_basis": "Frozen Setup contract and U/E/T/X research state",
        "requires_human_decision": True,
        "order_execution_authorized": False,
    }
    check("H05_setup_research_state_allowed", validate_downstream_output(good_setup) == "PASS_HUMAN_DECISION_BOUNDARY")

    good_add = {
        "research_state": "ADD_POSITION_PRECONDITIONS_SATISFIED_REQUIRES_HUMAN_CONFIRMATION",
        "capital_action_related": True,
        "rule_basis": "Precommitted add-position constraints",
        "requires_human_decision": True,
        "order_execution_authorized": False,
    }
    check("H06_add_position_rule_check_allowed", validate_downstream_output(good_add) == "PASS_HUMAN_DECISION_BOUNDARY")

    auto_buy_blocked = False
    try:
        validate_downstream_output({
            "research_state": "AUTO_BUY",
            "capital_action_related": True,
            "rule_basis": "x",
            "requires_human_decision": False,
            "order_execution_authorized": True,
        })
    except RuntimeError:
        auto_buy_blocked = True
    check("H07_auto_buy_blocked", auto_buy_blocked)

    execution_blocked = False
    try:
        validate_downstream_output({
            "research_state": "RESEARCH_CONDITIONS_SATISFIED",
            "capital_action_related": True,
            "rule_basis": "x",
            "requires_human_decision": True,
            "order_execution_authorized": True,
        })
    except RuntimeError:
        execution_blocked = True
    check("H08_order_execution_true_blocked", execution_blocked)

    missing_human_blocked = False
    try:
        validate_downstream_output({
            "research_state": "EXIT_CONDITION_TRIGGERED_REQUIRES_HUMAN_CONFIRMATION",
            "capital_action_related": True,
            "rule_basis": "Frozen stop/invalidation condition",
            "requires_human_decision": False,
            "order_execution_authorized": False,
        })
    except RuntimeError:
        missing_human_blocked = True
    check("H09_capital_action_without_human_gate_blocked", missing_human_blocked)

    hypothetical = {
        "research_state": "HYPOTHETICAL_OR_RULE_CONSTRAINED_SIZE_NOT_ORDER_QUANTITY",
        "capital_action_related": True,
        "rule_basis": "Risk-budget scenario calculation",
        "requires_human_decision": True,
        "order_execution_authorized": False,
        "hypothetical_position_size": 0.05,
    }
    check("H10_hypothetical_position_sizing_allowed", validate_downstream_output(hypothetical) == "PASS_HUMAN_DECISION_BOUNDARY")

    monitoring = {
        "research_state": "RESEARCH_MONITORING_STATE_UNCHANGED",
        "capital_action_related": False,
        "requires_human_decision": False,
        "order_execution_authorized": False,
    }
    check("H11_noncapital_monitoring_allowed", validate_downstream_output(monitoring) == "PASS_HUMAN_DECISION_BOUNDARY")

    check(
        "H12_no_autonomous_financial_decision_authority",
        c["governance"]["autonomous_financial_decision_authorized"] is False
        and c["governance"]["autonomous_investment_transaction_authorized"] is False,
    )

    result = {
        "schema": "AI_CORE_EVID_V2_8_12_HUMAN_DECISION_BOUNDARY_SELFTEST_V1",
        "tests": tests,
        "passed": sum(t["pass"] for t in tests),
        "total": len(tests),
        "all_pass": all(t["pass"] for t in tests),
        "price_or_return_data_consumed": False,
        "brokerage_or_order_action_executed": False,
        "historical_research_semantics_modified": False,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["all_pass"]:
        raise SystemExit(2)
    return result


if __name__ == "__main__":
    self_test()
