from __future__ import annotations

from typing import Dict, List, Tuple


ORDER = {"INSUFFICIENT": 0, "WEAK": 1, "MODERATE": 2, "STRONG": 3}
VALID_STATUSES = {
    "SUPPORTED",
    "MIXED_OR_UNSTABLE",
    "FAILED",
    "INSUFFICIENT_DATA",
    "NOT_APPLICABLE_PREDECLARED",
}
VALID_ROLES = {"ANCHOR", "SUPPORTING"}
VALID_FAILURE_EFFECTS = {"CAP_AT_WEAK", "CAP_AT_MODERATE", "UNCERTAINTY_ONLY"}
REQUIRED_ANCHORS = {
    "baseline_comparison",
    "out_of_sample",
    "transaction_cost_and_execution_constraints",
}


def _cap(current: str, ceiling: str) -> str:
    return current if ORDER[current] <= ORDER[ceiling] else ceiling


def synthesize_strength(prereg: dict, result: dict) -> Tuple[str, List[str]]:
    reasons: List[str] = []

    if result.get("integrity_prerequisite_status") != "PASS":
        return "INSUFFICIENT", ["integrity_prerequisite_not_pass"]
    if result.get("minimum_sample_or_resolved_data_floor_pass") is not True:
        return "INSUFFICIENT", ["minimum_sample_or_resolved_data_floor_failed"]
    if result.get("untouched_oos_completed") is not True:
        return "INSUFFICIENT", ["untouched_oos_missing"]
    if result.get("primary_baseline_comparison_completed") is not True:
        return "INSUFFICIENT", ["primary_baseline_comparison_missing"]

    prereg_dims: Dict[str, dict] = {d["dimension"]: d for d in prereg["dimensions"]}
    result_dims: Dict[str, dict] = {d["dimension"]: d for d in result["dimensions"]}

    if set(prereg_dims) != set(result_dims):
        raise RuntimeError("DIMENSION_SET_MISMATCH")

    anchors = {name for name, d in prereg_dims.items() if d.get("role") == "ANCHOR"}
    if not REQUIRED_ANCHORS.issubset(anchors):
        missing = sorted(REQUIRED_ANCHORS - anchors)
        raise RuntimeError(f"REQUIRED_ANCHORS_MISSING:{','.join(missing)}")

    strength = "STRONG"
    applicable_count = 0

    for name, pd in prereg_dims.items():
        role = pd.get("role")
        failure_effect = pd.get("failure_effect")
        if role not in VALID_ROLES:
            raise RuntimeError(f"INVALID_DIMENSION_ROLE:{name}:{role}")
        if failure_effect not in VALID_FAILURE_EFFECTS:
            raise RuntimeError(f"INVALID_FAILURE_EFFECT:{name}:{failure_effect}")

        status = result_dims[name].get("status")
        if status not in VALID_STATUSES:
            raise RuntimeError(f"INVALID_DIMENSION_STATUS:{name}:{status}")
        if status == "NOT_APPLICABLE_PREDECLARED":
            continue
        applicable_count += 1

        if status == "INSUFFICIENT_DATA":
            if role == "ANCHOR":
                return "INSUFFICIENT", [f"anchor_insufficient_data:{name}"]
            strength = _cap(strength, "MODERATE")
            reasons.append(f"supporting_insufficient_data:{name}")
            continue

        if status == "FAILED":
            if failure_effect == "CAP_AT_WEAK":
                strength = _cap(strength, "WEAK")
                reasons.append(f"failed_cap_weak:{name}")
            elif failure_effect == "CAP_AT_MODERATE":
                strength = _cap(strength, "MODERATE")
                reasons.append(f"failed_cap_moderate:{name}")
            else:
                strength = _cap(strength, "MODERATE")
                reasons.append(f"failed_uncertainty_only:{name}")
            continue

        if status == "MIXED_OR_UNSTABLE":
            if role == "ANCHOR":
                strength = _cap(strength, "MODERATE")
                reasons.append(f"anchor_mixed_cap_moderate:{name}")
            else:
                strength = _cap(strength, "MODERATE")
                reasons.append(f"supporting_mixed:{name}")

    if applicable_count == 0:
        return "INSUFFICIENT", ["no_applicable_dimension_results"]

    if not reasons:
        reasons.append("all_applicable_preregistered_dimensions_supported")
    return strength, reasons
