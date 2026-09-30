from __future__ import annotations

from dataclasses import dataclass
from typing import Any


VALID_ACTIONS = {"BUY", "ADD", "HOLD", "REDUCE", "EXIT"}
VALID_EVIDENCE = {"STRONG", "MODERATE", "WEAK", "INSUFFICIENT"}


@dataclass(frozen=True)
class DisciplineDecision:
    decision: str
    reasons: tuple[str, ...]
    override_logged: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "reasons": list(self.reasons),
            "override_logged": self.override_logged,
        }


def _require_number(name: str, value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name}_MUST_BE_NUMERIC")
    return float(value)


def evaluate(payload: dict[str, Any]) -> dict[str, Any]:
    action = str(payload.get("action_type", "")).upper()
    evidence = str(payload.get("evidence_strength", "")).upper()
    if action not in VALID_ACTIONS:
        raise ValueError("INVALID_ACTION_TYPE")
    if evidence not in VALID_EVIDENCE:
        raise ValueError("INVALID_EVIDENCE_STRENGTH")

    position_size = _require_number("position_size", payload.get("position_size"))
    position_limit = _require_number("position_limit", payload.get("position_limit"))
    risk_used = _require_number("risk_budget_used", payload.get("risk_budget_used"))
    risk_limit = _require_number("risk_budget_limit", payload.get("risk_budget_limit"))
    if min(position_size, position_limit, risk_used, risk_limit) < 0:
        raise ValueError("NEGATIVE_RISK_OR_POSITION_VALUE")

    stop_loss_defined = bool(payload.get("stop_loss_defined"))
    stop_loss_breached = bool(payload.get("stop_loss_breached"))
    take_profit_defined = bool(payload.get("take_profit_defined"))
    invalidation_triggered = bool(payload.get("invalidation_triggered"))
    adjustment_condition_satisfied = bool(payload.get("adjustment_condition_satisfied"))
    is_averaging_down = bool(payload.get("is_averaging_down"))
    independent_add_eligibility = bool(payload.get("independent_add_eligibility"))
    is_chasing = bool(payload.get("is_chasing"))
    chase_rule_satisfied = bool(payload.get("chase_rule_satisfied"))
    override_requested = bool(payload.get("override_requested"))
    override_reason = str(payload.get("override_reason") or "").strip()

    if override_requested and not override_reason:
        raise ValueError("OVERRIDE_REASON_REQUIRED")

    reasons: list[str] = []

    # Highest priority: mandatory exit states.
    if stop_loss_breached and not adjustment_condition_satisfied:
        reasons.append("STOP_LOSS_BREACHED")
        return DisciplineDecision("EXIT_REQUIRED", tuple(reasons), override_requested).as_dict()

    if invalidation_triggered:
        reasons.append("INVALIDATION_TRIGGERED")
        if action in {"REDUCE", "EXIT"}:
            return DisciplineDecision("EXIT_REQUIRED", tuple(reasons), override_requested).as_dict()
        return DisciplineDecision("EXIT_REQUIRED", tuple(reasons), override_requested).as_dict()

    # Missing precommitments block risk-increasing actions.
    if action in {"BUY", "ADD"}:
        if not stop_loss_defined:
            reasons.append("STOP_LOSS_NOT_DEFINED")
        if not take_profit_defined:
            reasons.append("TAKE_PROFIT_OR_EXIT_RULE_NOT_DEFINED")
        if reasons:
            return DisciplineDecision("ACTION_BLOCKED_BY_RISK", tuple(reasons), override_requested).as_dict()

    # Hard capacity constraints.
    if action in {"BUY", "ADD"}:
        if position_size > position_limit:
            reasons.append("POSITION_LIMIT_EXCEEDED")
        if risk_used > risk_limit:
            reasons.append("RISK_BUDGET_EXCEEDED")
        if reasons:
            return DisciplineDecision("ACTION_BLOCKED_BY_RISK", tuple(reasons), override_requested).as_dict()

    # Behavioral guards for risk-increasing actions.
    if action == "ADD" and is_averaging_down and not independent_add_eligibility:
        reasons.append("AVERAGING_DOWN_WITHOUT_INDEPENDENT_ELIGIBILITY")
        return DisciplineDecision("ACTION_BLOCKED_BY_RISK", tuple(reasons), override_requested).as_dict()

    if action in {"BUY", "ADD"} and is_chasing and not chase_rule_satisfied:
        reasons.append("ANTI_FOMO_CHASE_RULE_NOT_SATISFIED")
        return DisciplineDecision("ACTION_BLOCKED_BY_RISK", tuple(reasons), override_requested).as_dict()

    # Evidence rules. Exit/reduce are risk-reducing and remain eligible under weak evidence.
    if action in {"BUY", "ADD"}:
        if evidence == "INSUFFICIENT":
            reasons.append("INSUFFICIENT_EVIDENCE")
            return DisciplineDecision("NO_ACTION_INSUFFICIENT_EVIDENCE", tuple(reasons), override_requested).as_dict()
        if evidence == "WEAK":
            reasons.append("WEAK_EVIDENCE_FOR_RISK_INCREASE")
            return DisciplineDecision("ACTION_BLOCKED_BY_EVIDENCE", tuple(reasons), override_requested).as_dict()

    if action == "HOLD" and evidence == "INSUFFICIENT":
        reasons.append("INSUFFICIENT_EVIDENCE_FOR_HOLD_ELIGIBILITY")
        return DisciplineDecision("NO_ACTION_INSUFFICIENT_EVIDENCE", tuple(reasons), override_requested).as_dict()

    reasons.append("PRECOMMITTED_DISCIPLINE_SATISFIED")
    return DisciplineDecision("ACTION_ELIGIBLE", tuple(reasons), override_requested).as_dict()
