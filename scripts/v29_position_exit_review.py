#!/usr/bin/env python3
"""Read-only review of user-supplied A-share positions and precommitted exits.

No brokerage interaction, no inferred rule revision, no market data download.
When prices are missing/stale or no exit rule can be assessed, report UNKNOWN.
The existing V2.9 discipline engine is the sole eligibility authority.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from datetime import datetime
from pathlib import Path

from v29_discipline_engine import evaluate as evaluate_discipline

REQUIRED = {"security_id", "as_of", "quantity", "entry_price", "current_price",
            "stop_price", "take_profit_price", "position_fraction", "position_limit",
            "risk_budget_used", "risk_budget_limit", "invalidation_triggered"}
EXTRA = {"override_requested", "override_reason"}


def number(obj, name, positive=False):
    value = obj[name]
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
        raise ValueError("INVALID_NUMERIC:" + name)
    if value < 0 or (positive and value == 0):
        raise ValueError("INVALID_RANGE:" + name)
    return float(value)


def review(position: dict) -> dict:
    if not isinstance(position, dict) or not REQUIRED.issubset(position):
        raise ValueError("MISSING_REQUIRED_POSITION_FIELDS")
    if not set(position).issubset(REQUIRED | EXTRA):
        raise ValueError("UNRECOGNIZED_POSITION_FIELDS")
    security = position["security_id"]
    if not isinstance(security, str) or not security.strip():
        raise ValueError("INVALID_SECURITY_ID")
    timestamp = position["as_of"]
    if not isinstance(timestamp, str):
        raise ValueError("INVALID_AS_OF")
    dt = datetime.fromisoformat(timestamp)
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError("AS_OF_MUST_BE_OFFSET_AWARE")
    if not isinstance(position["quantity"], int) or isinstance(position["quantity"], bool) or position["quantity"] <= 0:
        raise ValueError("INVALID_QUANTITY")
    entry = number(position, "entry_price", positive=True)
    current = position["current_price"]
    stop = number(position, "stop_price", positive=True)
    target = number(position, "take_profit_price", positive=True)
    size = number(position, "position_fraction")
    limit = number(position, "position_limit")
    used = number(position, "risk_budget_used")
    budget = number(position, "risk_budget_limit")
    invalidated = position["invalidation_triggered"]
    if type(invalidated) is not bool:
        raise ValueError("INVALID_INVALIDATION_FLAG")
    override = position.get("override_requested", False)
    reason = position.get("override_reason", "")
    if type(override) is not bool or not isinstance(reason, str) or (override and not reason.strip()):
        raise ValueError("INVALID_OVERRIDE")
    if stop >= target:
        raise ValueError("STOP_MUST_BE_BELOW_TAKE_PROFIT")

    # Explicit unknown quote: do not hallucinate stop/target breach states.
    if current is None and not invalidated:
        status = "PRICE_MISSING"
        decision = None
        breached = None
        triggered = None
        unrealized = None
    else:
        current_value = number(position, "current_price", positive=True) if current is not None else None
        breached = current_value <= stop if current_value is not None else False
        triggered = current_value >= target if current_value is not None else False
        # An independent invalidation forces EXIT_REQUIRED even without price.
        # Unknown stop/target flags are neutral inputs, not evidence of safety.
        discipline_input = {
            "action_type": "EXIT", "current_exposure_exists": True,
            "evidence_strength": "INSUFFICIENT",
            "projected_post_action_position_size": 0.0,
            "position_limit": limit,
            "projected_post_action_risk_budget_used": 0.0,
            "risk_budget_limit": budget,
            "stop_loss_defined": True, "stop_loss_breached": breached,
            "take_profit_defined": True, "invalidation_triggered": invalidated,
            "adjustment_condition_satisfied": False,
            "exit_rule_revision_type": "NONE",
            "exit_rule_triggered": triggered,
            "exit_rule_relaxation_condition_satisfied_before_trigger": False,
            "is_averaging_down": False, "independent_add_eligibility": False,
            "is_chasing": False, "chase_rule_satisfied": False,
            "override_requested": override, "override_reason": reason,
        }
        decision = evaluate_discipline(discipline_input)
        status = "EXIT_TRIGGERED" if decision["decision"] == "EXIT_REQUIRED" else "NO_PRECOMMITTED_EXIT_TRIGGER"
        unrealized = current_value / entry - 1.0 if current_value is not None else None
        if current_value is None:
            breached = None
            triggered = None
    identity = hashlib.sha256(json.dumps(position, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {
        "schema": "AI_CORE_EVID_POSITION_EXIT_REVIEW_V1",
        "security_id": security, "as_of": timestamp,
        "input_sha256": identity,
        "market_data_origin": "USER_SUPPLIED_NOT_INDEPENDENTLY_VERIFIED",
        "quantity": position["quantity"], "position_fraction": size,
        "risk_budget_used": used, "risk_budget_limit": budget,
        "unrealized_return_fraction": unrealized,
        "stop_breached": breached, "take_profit_triggered": triggered,
        "invalidation_triggered": invalidated,
        "status": status, "discipline_decision": decision,
        "execution_status": "NO_BROKERAGE_EXECUTION",
        "caveat": "Threshold checks only on explicitly supplied snapshot; market tradability and execution not verified.",
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("input_json", type=Path)
    a = p.parse_args()
    payload = json.loads(a.input_json.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("EXPECTED_POSITION_LIST")
    out = [review(x) for x in payload]
    print(json.dumps({"schema": "AI_CORE_EVID_POSITION_REVIEW_BATCH_V1", "positions": out}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
