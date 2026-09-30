from __future__ import annotations

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


def main() -> None:
    expect(base(action_type="BUY", current_exposure_exists=False), "ACTION_ELIGIBLE")

    expect(
        base(
            action_type="ADD",
            current_exposure_exists=True,
            is_averaging_down=True,
            independent_add_eligibility=False,
        ),
        "ACTION_BLOCKED_BY_RISK",
    )

    expect(
        base(
            action_type="ADD",
            current_exposure_exists=True,
            is_averaging_down=True,
            independent_add_eligibility=True,
        ),
        "ACTION_ELIGIBLE",
    )

    expect(
        base(action_type="HOLD", current_exposure_exists=True, stop_loss_breached=True),
        "EXIT_REQUIRED",
    )

    expect(
        base(action_type="BUY", current_exposure_exists=False, evidence_strength="INSUFFICIENT"),
        "NO_ACTION_INSUFFICIENT_EVIDENCE",
    )

    expect(
        base(action_type="EXIT", current_exposure_exists=True, evidence_strength="WEAK"),
        "ACTION_ELIGIBLE",
    )

    got = expect(
        base(
            action_type="BUY",
            current_exposure_exists=False,
            is_chasing=True,
            chase_rule_satisfied=False,
            override_requested=True,
            override_reason="human override for audit only",
        ),
        "ACTION_BLOCKED_BY_RISK",
    )
    assert got["override_logged"] is True

    expect(
        base(
            action_type="ADD",
            current_exposure_exists=True,
            projected_post_action_position_size=0.25,
        ),
        "ACTION_BLOCKED_BY_RISK",
    )

    expect(
        base(action_type="BUY", current_exposure_exists=False, invalidation_triggered=True),
        "ACTION_BLOCKED_BY_EVIDENCE",
    )

    print("V2.9 Discipline Engine v1 self-test PASS")


if __name__ == "__main__":
    main()
