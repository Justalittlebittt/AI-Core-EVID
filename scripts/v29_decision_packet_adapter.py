from __future__ import annotations

import re
from typing import Any

from v29_discipline_engine import evaluate as evaluate_discipline

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
VALID_PACKET_VERSION = "V2.9_DECISION_PACKET_V1"


class DecisionPacketError(ValueError):
    pass


def _section(packet: dict[str, Any], name: str) -> dict[str, Any]:
    value = packet.get(name)
    if not isinstance(value, dict):
        raise DecisionPacketError(f"MISSING_OR_INVALID_SECTION:{name}")
    return value


def _require_fields(section_name: str, section: dict[str, Any], fields: list[str]) -> None:
    missing = [f for f in fields if f not in section]
    if missing:
        raise DecisionPacketError(f"MISSING_FIELDS:{section_name}:{','.join(missing)}")


def _require_sha(name: str, value: Any) -> str:
    s = str(value or "")
    if not SHA256_RE.fullmatch(s):
        raise DecisionPacketError(f"INVALID_SHA256:{name}")
    return s


def adapt_and_evaluate(packet: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(packet, dict):
        raise DecisionPacketError("PACKET_MUST_BE_OBJECT")
    if packet.get("packet_version") != VALID_PACKET_VERSION:
        raise DecisionPacketError("INVALID_PACKET_VERSION")

    research = _section(packet, "research_context")
    validity = _section(packet, "validity")
    action = _section(packet, "action_context")
    risk = _section(packet, "risk_context")
    behavior = _section(packet, "behavior_context")
    override = _section(packet, "override_context")

    _require_fields("research_context", research, [
        "strategy_id", "experiment_version", "evaluation_timestamp", "evidence_artifact_sha256"
    ])
    _require_fields("validity", validity, [
        "evidence_strength", "validity_result_sha256", "pre_registration_sha256",
        "all_required_dimensions_reported", "post_outcome_rule_change_detected"
    ])
    _require_fields("action_context", action, ["action_type", "current_exposure_exists"])
    _require_fields("risk_context", risk, [
        "projected_post_action_position_size", "position_limit",
        "projected_post_action_risk_budget_used", "risk_budget_limit",
        "stop_loss_defined", "stop_loss_breached", "take_profit_defined",
        "invalidation_triggered", "adjustment_condition_satisfied"
    ])
    _require_fields("behavior_context", behavior, [
        "is_averaging_down", "independent_add_eligibility", "is_chasing", "chase_rule_satisfied"
    ])
    _require_fields("override_context", override, ["override_requested", "override_reason"])

    _require_sha("evidence_artifact_sha256", research["evidence_artifact_sha256"])
    _require_sha("validity_result_sha256", validity["validity_result_sha256"])
    _require_sha("pre_registration_sha256", validity["pre_registration_sha256"])

    reported_strength = str(validity["evidence_strength"]).upper()
    all_dims = validity["all_required_dimensions_reported"] is True
    post_outcome_change = validity["post_outcome_rule_change_detected"] is True

    effective_strength = reported_strength
    downgraded = False
    downgrade_reasons: list[str] = []
    if not all_dims:
        effective_strength = "INSUFFICIENT"
        downgraded = True
        downgrade_reasons.append("VALIDITY_DIMENSIONS_INCOMPLETE")
    if post_outcome_change:
        effective_strength = "INSUFFICIENT"
        downgraded = True
        downgrade_reasons.append("POST_OUTCOME_RULE_CHANGE_DETECTED")

    discipline_input = {
        "action_type": action["action_type"],
        "current_exposure_exists": action["current_exposure_exists"],
        "evidence_strength": effective_strength,
        "projected_post_action_position_size": risk["projected_post_action_position_size"],
        "position_limit": risk["position_limit"],
        "projected_post_action_risk_budget_used": risk["projected_post_action_risk_budget_used"],
        "risk_budget_limit": risk["risk_budget_limit"],
        "stop_loss_defined": risk["stop_loss_defined"],
        "stop_loss_breached": risk["stop_loss_breached"],
        "take_profit_defined": risk["take_profit_defined"],
        "invalidation_triggered": risk["invalidation_triggered"],
        "adjustment_condition_satisfied": risk["adjustment_condition_satisfied"],
        "is_averaging_down": behavior["is_averaging_down"],
        "independent_add_eligibility": behavior["independent_add_eligibility"],
        "is_chasing": behavior["is_chasing"],
        "chase_rule_satisfied": behavior["chase_rule_satisfied"],
        "override_requested": override["override_requested"],
        "override_reason": override["override_reason"],
    }

    decision = evaluate_discipline(discipline_input)
    return {
        "packet_status": (
            "PACKET_VALIDITY_DOWNGRADED_TO_INSUFFICIENT" if downgraded else "PACKET_VALID"
        ),
        "discipline_input": discipline_input,
        "discipline_decision": decision,
        "adapter_metadata": {
            "strategy_id": research["strategy_id"],
            "experiment_version": research["experiment_version"],
            "evaluation_timestamp": research["evaluation_timestamp"],
            "reported_evidence_strength": reported_strength,
            "effective_evidence_strength": effective_strength,
            "validity_downgrade_reasons": downgrade_reasons,
            "action_type_preserved": True,
            "risk_fields_inferred_or_optimized": False,
            "override_passthrough": True,
        },
    }
