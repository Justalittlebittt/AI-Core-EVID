from __future__ import annotations

import math

from v29_decision_packet_adapter import DecisionPacketError, adapt_and_evaluate

SHA = "a" * 64


def packet() -> dict:
    return {
        "packet_version": "V2.9_DECISION_PACKET_V1",
        "research_context": {
            "strategy_id": "TEST_STRATEGY",
            "experiment_version": "EXP_V1",
            "evaluation_timestamp": "2026-09-30T00:00:00Z",
            "evidence_artifact_sha256": SHA,
        },
        "validity": {
            "evidence_strength": "MODERATE",
            "validity_result_sha256": SHA,
            "pre_registration_sha256": SHA,
            "all_required_dimensions_reported": True,
            "post_outcome_rule_change_detected": False,
        },
        "action_context": {"action_type": "BUY", "current_exposure_exists": False},
        "risk_context": {
            "projected_post_action_position_size": 0.10,
            "position_limit": 0.20,
            "projected_post_action_risk_budget_used": 0.30,
            "risk_budget_limit": 1.00,
            "stop_loss_defined": True,
            "stop_loss_breached": False,
            "take_profit_defined": True,
            "invalidation_triggered": False,
            "adjustment_condition_satisfied": False,
        },
        "behavior_context": {
            "is_averaging_down": False,
            "independent_add_eligibility": False,
            "is_chasing": False,
            "chase_rule_satisfied": False,
        },
        "override_context": {"override_requested": False, "override_reason": ""},
    }


def expect_packet_error(p: dict, marker: str) -> None:
    try:
        adapt_and_evaluate(p)
        raise AssertionError(f"expected packet error: {marker}")
    except DecisionPacketError as exc:
        assert marker in str(exc), (exc, marker)


def main() -> None:
    base = adapt_and_evaluate(packet())
    assert base["packet_status"] == "PACKET_VALID"
    assert base["discipline_input"]["evidence_strength"] == "MODERATE"
    assert base["discipline_decision"]["decision"] == "ACTION_ELIGIBLE"

    p = packet(); p["validity"]["all_required_dimensions_reported"] = False
    r = adapt_and_evaluate(p)
    assert r["packet_status"] == "PACKET_VALIDITY_DOWNGRADED_TO_INSUFFICIENT"
    assert r["adapter_metadata"]["reported_evidence_strength"] == "MODERATE"
    assert r["adapter_metadata"]["effective_evidence_strength"] == "INSUFFICIENT"
    assert r["discipline_decision"]["decision"] == "NO_ACTION_INSUFFICIENT_EVIDENCE"

    p = packet(); p["validity"]["post_outcome_rule_change_detected"] = True
    r = adapt_and_evaluate(p)
    assert "POST_OUTCOME_RULE_CHANGE_DETECTED" in r["adapter_metadata"]["validity_downgrade_reasons"]
    assert r["discipline_decision"]["decision"] == "NO_ACTION_INSUFFICIENT_EVIDENCE"

    p = packet(); p["risk_context"].pop("position_limit")
    expect_packet_error(p, "MISSING_FIELDS:risk_context:position_limit")

    p = packet(); p["research_context"]["evidence_artifact_sha256"] = "bad"
    expect_packet_error(p, "INVALID_SHA256:evidence_artifact_sha256")

    p = packet(); p["validity"]["post_outcome_rule_change_detected"] = "false"
    expect_packet_error(p, "validity.post_outcome_rule_change_detected_MUST_BE_BOOLEAN")

    p = packet(); p["validity"]["all_required_dimensions_reported"] = 1
    expect_packet_error(p, "validity.all_required_dimensions_reported_MUST_BE_BOOLEAN")

    p = packet(); p["action_context"]["action_type"] = "buy"
    expect_packet_error(p, "INVALID_ACTION_TYPE")

    p = packet(); p["validity"]["evidence_strength"] = "moderate"
    expect_packet_error(p, "INVALID_EVIDENCE_STRENGTH")

    p = packet(); p["risk_context"]["projected_post_action_position_size"] = math.nan
    expect_packet_error(p, "risk_context.projected_post_action_position_size_MUST_BE_FINITE")

    p = packet(); p["risk_context"]["risk_budget_limit"] = math.inf
    expect_packet_error(p, "risk_context.risk_budget_limit_MUST_BE_FINITE")

    p = packet(); p["override_context"]["override_reason"] = 123
    expect_packet_error(p, "override_context.override_reason_MUST_BE_STRING")

    p = packet()
    p["action_context"]["action_type"] = "ADD"
    p["action_context"]["current_exposure_exists"] = True
    p["behavior_context"]["is_averaging_down"] = True
    p["behavior_context"]["independent_add_eligibility"] = False
    r = adapt_and_evaluate(p)
    assert r["discipline_input"]["action_type"] == "ADD"
    assert r["discipline_decision"]["decision"] == "ACTION_BLOCKED_BY_RISK"

    p = packet()
    p["override_context"]["override_requested"] = True
    p["override_context"]["override_reason"] = "manual preference"
    p["behavior_context"]["is_chasing"] = True
    p["behavior_context"]["chase_rule_satisfied"] = False
    r = adapt_and_evaluate(p)
    assert r["discipline_decision"]["decision"] == "ACTION_BLOCKED_BY_RISK"
    assert r["discipline_decision"]["override_logged"] is True

    print("V2.9 decision packet self-test PASS")


if __name__ == "__main__": main()
