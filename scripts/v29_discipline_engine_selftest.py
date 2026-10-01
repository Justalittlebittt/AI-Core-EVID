from __future__ import annotations

import math

from v29_discipline_engine import evaluate


def base(**overrides):
    p = {
        "evidence_strength": "MODERATE",
        "projected_post_action_position_size": 0.10,
        "position_limit": 0.20,
        "projected_post_action_risk_budget_used": 0.03,
        "risk_budget_limit": 0.05,
        "stop_loss_defined": True,
        "stop_loss_breached": False,
        "take_profit_defined": True,
        "invalidation_triggered": False,
        "adjustment_condition_satisfied": False,
        "exit_rule_revision_type": "NONE",
        "exit_rule_triggered": False,
        "exit_rule_relaxation_condition_satisfied_before_trigger": False,
        "is_averaging_down": False,
        "independent_add_eligibility": False,
        "is_chasing": False,
        "chase_rule_satisfied": False,
        "override_requested": False,
        "override_reason": "",
    }
    p.update(overrides)
    return p


def expect(payload, expected):
    got = evaluate(payload)
    assert got["decision"] == expected, (payload, got, expected)
    return got


def expect_error(payload, marker):
    try:
        evaluate(payload)
        raise AssertionError(f"expected error: {marker}")
    except ValueError as exc:
        assert marker in str(exc), (payload, exc, marker)


def main() -> None:
    expect(base(action_type="BUY", current_exposure_exists=False), "ACTION_ELIGIBLE")
    expect(base(action_type="ADD", current_exposure_exists=True, is_averaging_down=True, independent_add_eligibility=False), "ACTION_BLOCKED_BY_RISK")
    expect(base(action_type="ADD", current_exposure_exists=True, is_averaging_down=True, independent_add_eligibility=True), "ACTION_ELIGIBLE")
    expect(base(action_type="HOLD", current_exposure_exists=True, stop_loss_breached=True), "EXIT_REQUIRED")

    # P1 regression: the legacy adjustment flag must never exempt an already-breached active stop.
    got = expect(
        base(
            action_type="HOLD",
            current_exposure_exists=True,
            stop_loss_breached=True,
            adjustment_condition_satisfied=True,
        ),
        "EXIT_REQUIRED",
    )
    assert "STOP_LOSS_BREACHED" in got["reasons"]

    # A precommitted exit/take-profit trigger has the same no-post-trigger-relaxation priority.
    got = expect(
        base(
            action_type="HOLD",
            current_exposure_exists=True,
            exit_rule_triggered=True,
            exit_rule_revision_type="RELAX",
            exit_rule_relaxation_condition_satisfied_before_trigger=True,
        ),
        "EXIT_REQUIRED",
    )
    assert "EXIT_RULE_TRIGGERED" in got["reasons"]

    # Tightening is risk-reducing and remains eligible when no higher-priority rule fires.
    expect(
        base(
            action_type="HOLD",
            current_exposure_exists=True,
            exit_rule_revision_type="TIGHTEN",
        ),
        "ACTION_ELIGIBLE",
    )

    # Relaxing an active exit rule is blocked unless its predeclared condition was satisfied pre-trigger.
    got = expect(
        base(
            action_type="HOLD",
            current_exposure_exists=True,
            exit_rule_revision_type="RELAX",
            exit_rule_relaxation_condition_satisfied_before_trigger=False,
        ),
        "ACTION_BLOCKED_BY_RISK",
    )
    assert "EXIT_RULE_RELAXATION_NOT_PREAUTHORIZED" in got["reasons"]
    expect(
        base(
            action_type="HOLD",
            current_exposure_exists=True,
            exit_rule_revision_type="RELAX",
            exit_rule_relaxation_condition_satisfied_before_trigger=True,
        ),
        "ACTION_ELIGIBLE",
    )

    expect(base(action_type="BUY", current_exposure_exists=False, evidence_strength="INSUFFICIENT"), "NO_ACTION_INSUFFICIENT_EVIDENCE")
    expect(base(action_type="EXIT", current_exposure_exists=True, evidence_strength="WEAK"), "ACTION_ELIGIBLE")

    got = expect(
        base(action_type="BUY", current_exposure_exists=False, is_chasing=True, chase_rule_satisfied=False, override_requested=True, override_reason="human override for audit only"),
        "ACTION_BLOCKED_BY_RISK",
    )
    assert got["override_logged"] is True

    expect(base(action_type="ADD", current_exposure_exists=True, projected_post_action_position_size=0.25), "ACTION_BLOCKED_BY_RISK")
    expect(base(action_type="BUY", current_exposure_exists=False, invalidation_triggered=True), "ACTION_BLOCKED_BY_EVIDENCE")

    expect_error(base(action_type="BUY", current_exposure_exists="false"), "current_exposure_exists_MUST_BE_BOOLEAN")
    expect_error(base(action_type="BUY", current_exposure_exists=False, stop_loss_defined="false"), "stop_loss_defined_MUST_BE_BOOLEAN")
    expect_error(base(action_type="BUY", current_exposure_exists=False, is_chasing="false"), "is_chasing_MUST_BE_BOOLEAN")
    expect_error(base(action_type="BUY", current_exposure_exists=False, override_requested="false"), "override_requested_MUST_BE_BOOLEAN")
    expect_error(base(action_type="BUY", current_exposure_exists=False, exit_rule_triggered="false"), "exit_rule_triggered_MUST_BE_BOOLEAN")
    expect_error(base(action_type="BUY", current_exposure_exists=False, exit_rule_revision_type="relax"), "INVALID_EXIT_RULE_REVISION_TYPE")
    expect_error(base(action_type="BUY", current_exposure_exists=False, exit_rule_revision_type="RELAX"), "EXIT_RULE_REVISION_REQUIRES_EXISTING_EXPOSURE")
    expect_error(base(action_type="BUY", current_exposure_exists=False, exit_rule_triggered=True), "EXIT_RULE_TRIGGER_REQUIRES_EXISTING_EXPOSURE")

    expect_error(base(action_type="buy", current_exposure_exists=False), "INVALID_ACTION_TYPE")
    expect_error(base(action_type="BUY", current_exposure_exists=False, evidence_strength="moderate"), "INVALID_EVIDENCE_STRENGTH")
    expect_error(base(action_type="BUY", current_exposure_exists=False, projected_post_action_position_size=math.nan), "projected_post_action_position_size_MUST_BE_FINITE")
    expect_error(base(action_type="BUY", current_exposure_exists=False, risk_budget_limit=math.inf), "risk_budget_limit_MUST_BE_FINITE")
    expect_error(base(action_type="BUY", current_exposure_exists=False, override_reason=1), "override_reason_MUST_BE_STRING")

    print("V2.9 Discipline Engine v1 + post-baseline repair 1 self-test PASS")


if __name__ == "__main__":
    main()
