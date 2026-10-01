from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any


VALID_ACTIONS = {"BUY", "ADD", "HOLD", "REDUCE", "EXIT"}
VALID_EVIDENCE = {"STRONG", "MODERATE", "WEAK", "INSUFFICIENT"}
VALID_EXIT_RULE_REVISIONS = {"NONE", "TIGHTEN", "RELAX"}


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
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{name}_MUST_BE_FINITE")
    return number


def _require_bool(name: str, value: Any) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{name}_MUST_BE_BOOLEAN")
    return value


def _require_exact_enum(name: str, value: Any, allowed: set[str]) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise ValueError(f"INVALID_{name}")
    return value


def evaluate(payload: dict[str, Any]) -> dict[str, Any]:
    action = _require_exact_enum("ACTION_TYPE", payload.get("action_type"), VALID_ACTIONS)
    evidence = _require_exact_enum(
        "EVIDENCE_STRENGTH", payload.get("evidence_strength"), VALID_EVIDENCE
    )

    current_exposure_exists = _require_bool(
        "current_exposure_exists", payload.get("current_exposure_exists")
    )
    if action == "BUY" and current_exposure_exists:
        raise ValueError("BUY_REQUIRES_NO_EXISTING_EXPOSURE_USE_ADD_INSTEAD")
    if action in {"ADD", "HOLD", "REDUCE", "EXIT"} and not current_exposure_exists:
        raise ValueError(f"{action}_REQUIRES_EXISTING_EXPOSURE")

    projected_position = _require_number(
        "projected_post_action_position_size",
        payload.get("projected_post_action_position_size"),
    )
    position_limit = _require_number("position_limit", payload.get("position_limit"))
    projected_risk = _require_number(
        "projected_post_action_risk_budget_used",
        payload.get("projected_post_action_risk_budget_used"),
    )
    risk_limit = _require_number("risk_budget_limit", payload.get("risk_budget_limit"))
    if min(projected_position, position_limit, projected_risk, risk_limit) < 0:
        raise ValueError("NEGATIVE_RISK_OR_POSITION_VALUE")

    stop_loss_defined = _require_bool("stop_loss_defined", payload.get("stop_loss_defined"))
    stop_loss_breached = _require_bool("stop_loss_breached", payload.get("stop_loss_breached"))
    take_profit_defined = _require_bool("take_profit_defined", payload.get("take_profit_defined"))
    invalidation_triggered = _require_bool(
        "invalidation_triggered", payload.get("invalidation_triggered")
    )
    # Retained for V1 packet compatibility/audit. It can no longer exempt an already-breached active stop.
    adjustment_condition_satisfied = _require_bool(
        "adjustment_condition_satisfied", payload.get("adjustment_condition_satisfied")
    )
    exit_rule_revision_type = _require_exact_enum(
        "EXIT_RULE_REVISION_TYPE",
        payload.get("exit_rule_revision_type"),
        VALID_EXIT_RULE_REVISIONS,
    )
    exit_rule_triggered = _require_bool(
        "exit_rule_triggered", payload.get("exit_rule_triggered")
    )
    exit_rule_relaxation_condition_satisfied_before_trigger = _require_bool(
        "exit_rule_relaxation_condition_satisfied_before_trigger",
        payload.get("exit_rule_relaxation_condition_satisfied_before_trigger"),
    )
    is_averaging_down = _require_bool("is_averaging_down", payload.get("is_averaging_down"))
    independent_add_eligibility = _require_bool(
        "independent_add_eligibility", payload.get("independent_add_eligibility")
    )
    is_chasing = _require_bool("is_chasing", payload.get("is_chasing"))
    chase_rule_satisfied = _require_bool(
        "chase_rule_satisfied", payload.get("chase_rule_satisfied")
    )
    override_requested = _require_bool("override_requested", payload.get("override_requested"))
    override_reason_raw = payload.get("override_reason")
    if not isinstance(override_reason_raw, str):
        raise ValueError("override_reason_MUST_BE_STRING")
    override_reason = override_reason_raw.strip()

    if stop_loss_breached and not current_exposure_exists:
        raise ValueError("STOP_LOSS_BREACH_REQUIRES_EXISTING_EXPOSURE")
    if exit_rule_triggered and not current_exposure_exists:
        raise ValueError("EXIT_RULE_TRIGGER_REQUIRES_EXISTING_EXPOSURE")
    if exit_rule_revision_type != "NONE" and not current_exposure_exists:
        raise ValueError("EXIT_RULE_REVISION_REQUIRES_EXISTING_EXPOSURE")
    if override_requested and not override_reason:
        raise ValueError("OVERRIDE_REASON_REQUIRED")

    reasons: list[str] = []

    # The active stop is authoritative. A legitimate pre-breach transition must update the active
    # stop before this packet is evaluated; once that active stop is breached there is no exception.
    if current_exposure_exists and stop_loss_breached:
        reasons.append("STOP_LOSS_BREACHED")
        return DisciplineDecision("EXIT_REQUIRED", tuple(reasons), override_requested).as_dict()

    # A precommitted exit/take-profit rule that has already triggered cannot be relaxed afterward.
    if current_exposure_exists and exit_rule_triggered:
        reasons.append("EXIT_RULE_TRIGGERED")
        return DisciplineDecision("EXIT_REQUIRED", tuple(reasons), override_requested).as_dict()

    if invalidation_triggered:
        reasons.append("INVALIDATION_TRIGGERED")
        if current_exposure_exists:
            return DisciplineDecision("EXIT_REQUIRED", tuple(reasons), override_requested).as_dict()
        return DisciplineDecision("ACTION_BLOCKED_BY_EVIDENCE", tuple(reasons), override_requested).as_dict()

    # Tightening is risk-reducing. Relaxation is allowed only when its predeclared condition is
    # explicitly recorded as having been satisfied before any exit-rule trigger.
    if current_exposure_exists and exit_rule_revision_type == "RELAX":
        if not exit_rule_relaxation_condition_satisfied_before_trigger:
            reasons.append("EXIT_RULE_RELAXATION_NOT_PREAUTHORIZED")
            return DisciplineDecision("ACTION_BLOCKED_BY_RISK", tuple(reasons), override_requested).as_dict()

    if action in {"BUY", "ADD"}:
        if not stop_loss_defined:
            reasons.append("STOP_LOSS_NOT_DEFINED")
        if not take_profit_defined:
            reasons.append("TAKE_PROFIT_OR_EXIT_RULE_NOT_DEFINED")
        if reasons:
            return DisciplineDecision("ACTION_BLOCKED_BY_RISK", tuple(reasons), override_requested).as_dict()

    if action in {"BUY", "ADD"}:
        if projected_position > position_limit:
            reasons.append("POST_ACTION_POSITION_LIMIT_EXCEEDED")
        if projected_risk > risk_limit:
            reasons.append("POST_ACTION_RISK_BUDGET_EXCEEDED")
        if reasons:
            return DisciplineDecision("ACTION_BLOCKED_BY_RISK", tuple(reasons), override_requested).as_dict()

    if action == "ADD" and is_averaging_down and not independent_add_eligibility:
        reasons.append("AVERAGING_DOWN_WITHOUT_INDEPENDENT_ELIGIBILITY")
        return DisciplineDecision("ACTION_BLOCKED_BY_RISK", tuple(reasons), override_requested).as_dict()

    if action in {"BUY", "ADD"} and is_chasing and not chase_rule_satisfied:
        reasons.append("ANTI_FOMO_CHASE_RULE_NOT_SATISFIED")
        return DisciplineDecision("ACTION_BLOCKED_BY_RISK", tuple(reasons), override_requested).as_dict()

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
