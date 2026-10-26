#!/usr/bin/env python3
"""Isolated Decision Case wiring check. Illustrative inputs, NEVER investment evidence."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from v29_decision_packet_adapter import adapt_and_evaluate

SOURCE = {
    "kind": "SYNTHETIC_TEST_FIXTURE",
    "security": "DEMO:000001",
    "as_of": "2020-01-02T15:00:00+08:00",
    "market_data": "NONE",
    "validated_candidate_signal": False,
    "note": "No real A-share data, strategy result, backtest, trading recommendation or prospective outcomes."
}


def canonical_sha(obj: dict) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def build_case() -> dict:
    """Bind demonstrative data identities; fail-closed because no validated evidence exists."""
    packet = {
        "packet_version": "V2.9_DECISION_PACKET_V1",
        "research_context": {
            "strategy_id": "UNVALIDATED_SYNTHETIC_FIXTURE",
            "experiment_version": "DEMO_ONLY_V1",
            "evaluation_timestamp": SOURCE["as_of"],
            "evidence_artifact_sha256": canonical_sha(SOURCE),
        },
        "validity": {
            "evidence_strength": "INSUFFICIENT",
            "validity_result_sha256": canonical_sha({"status": "NOT_EVALUATED", "sample": "NONE"}),
            "pre_registration_sha256": canonical_sha({"status": "NO_QUALIFYING_PREREGISTRATION"}),
            "all_required_dimensions_reported": False,
            "post_outcome_rule_change_detected": False,
        },
        "action_context": {"action_type": "BUY", "current_exposure_exists": False},
        "risk_context": {
            # These are explicit illustrative inputs, not inferred trading parameters.
            "projected_post_action_position_size": 0.01,
            "position_limit": 0.02,
            "projected_post_action_risk_budget_used": 0.001,
            "risk_budget_limit": 0.002,
            "stop_loss_defined": True,
            "stop_loss_breached": False,
            "take_profit_defined": True,
            "invalidation_triggered": False,
            "adjustment_condition_satisfied": False,
            "exit_rule_revision_type": "NONE",
            "exit_rule_triggered": False,
            "exit_rule_relaxation_condition_satisfied_before_trigger": False,
        },
        "behavior_context": {
            "is_averaging_down": False,
            "independent_add_eligibility": False,
            "is_chasing": False,
            "chase_rule_satisfied": False,
        },
        "override_context": {"override_requested": False, "override_reason": ""},
    }
    result = adapt_and_evaluate(packet)
    return {"case_type": "SYNTHETIC_INTEGRATION_TEST_NOT_INVESTMENT_ADVICE",
            "source": SOURCE, "packet": packet, "evaluation": result}


def main() -> None:
    result = build_case()
    actual = result["evaluation"]["discipline_decision"]["decision"]
    if actual != "NO_ACTION_INSUFFICIENT_EVIDENCE":
        raise SystemExit("FAIL_CLOSED_INVARIANT_BROKEN:" + actual)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
