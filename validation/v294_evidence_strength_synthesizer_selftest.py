from copy import deepcopy

from scripts.v294_evidence_strength_synthesizer import synthesize_strength


def prereg_template() -> dict:
    dims = [
        ("effect_size", "SUPPORTING", "CAP_AT_MODERATE"),
        ("baseline_comparison", "ANCHOR", "CAP_AT_WEAK"),
        ("out_of_sample", "ANCHOR", "CAP_AT_WEAK"),
        ("regime_stability", "SUPPORTING", "CAP_AT_MODERATE"),
        ("cross_sectional_stability", "SUPPORTING", "CAP_AT_MODERATE"),
        ("transaction_cost_and_execution_constraints", "ANCHOR", "CAP_AT_WEAK"),
        ("drawdown_and_loss_sequences", "SUPPORTING", "CAP_AT_MODERATE"),
        ("probability_calibration_where_applicable", "SUPPORTING", "UNCERTAINTY_ONLY"),
        ("reasonable_parameter_sensitivity", "SUPPORTING", "CAP_AT_MODERATE"),
        ("failure_region_identification", "SUPPORTING", "UNCERTAINTY_ONLY"),
    ]
    return {
        "dimensions": [
            {"dimension": name, "role": role, "failure_effect": effect}
            for name, role, effect in dims
        ]
    }


def result_all_supported(prereg: dict) -> dict:
    return {
        "integrity_prerequisite_status": "PASS",
        "minimum_sample_or_resolved_data_floor_pass": True,
        "untouched_oos_completed": True,
        "primary_baseline_comparison_completed": True,
        "dimensions": [
            {"dimension": d["dimension"], "status": "SUPPORTED"}
            for d in prereg["dimensions"]
        ],
    }


def set_status(result: dict, name: str, status: str) -> None:
    for d in result["dimensions"]:
        if d["dimension"] == name:
            d["status"] = status
            return
    raise AssertionError(name)


def main() -> None:
    prereg = prereg_template()

    base = result_all_supported(prereg)
    strength, reasons = synthesize_strength(prereg, base)
    assert strength == "STRONG"
    assert reasons == ["all_applicable_preregistered_dimensions_supported"]

    supporting_failed = deepcopy(base)
    set_status(supporting_failed, "regime_stability", "FAILED")
    strength, reasons = synthesize_strength(prereg, supporting_failed)
    assert strength == "MODERATE"
    assert "failed_cap_moderate:regime_stability" in reasons

    supporting_mixed = deepcopy(base)
    set_status(supporting_mixed, "reasonable_parameter_sensitivity", "MIXED_OR_UNSTABLE")
    strength, _ = synthesize_strength(prereg, supporting_mixed)
    assert strength == "MODERATE"

    anchor_failed = deepcopy(base)
    set_status(anchor_failed, "baseline_comparison", "FAILED")
    strength, reasons = synthesize_strength(prereg, anchor_failed)
    assert strength == "WEAK"
    assert "failed_cap_weak:baseline_comparison" in reasons

    anchor_mixed = deepcopy(base)
    set_status(anchor_mixed, "out_of_sample", "MIXED_OR_UNSTABLE")
    strength, _ = synthesize_strength(prereg, anchor_mixed)
    assert strength == "MODERATE"

    supporting_insufficient = deepcopy(base)
    set_status(supporting_insufficient, "drawdown_and_loss_sequences", "INSUFFICIENT_DATA")
    strength, _ = synthesize_strength(prereg, supporting_insufficient)
    assert strength == "MODERATE"

    anchor_insufficient = deepcopy(base)
    set_status(anchor_insufficient, "transaction_cost_and_execution_constraints", "INSUFFICIENT_DATA")
    strength, reasons = synthesize_strength(prereg, anchor_insufficient)
    assert strength == "INSUFFICIENT"
    assert reasons == ["anchor_insufficient_data:transaction_cost_and_execution_constraints"]

    no_oos = deepcopy(base)
    no_oos["untouched_oos_completed"] = False
    strength, reasons = synthesize_strength(prereg, no_oos)
    assert strength == "INSUFFICIENT"
    assert reasons == ["untouched_oos_missing"]

    bad_prereg = deepcopy(prereg)
    for d in bad_prereg["dimensions"]:
        if d["dimension"] == "out_of_sample":
            d["role"] = "SUPPORTING"
    try:
        synthesize_strength(bad_prereg, base)
        raise AssertionError("missing required anchor should fail")
    except RuntimeError as exc:
        assert "REQUIRED_ANCHORS_MISSING" in str(exc)

    print("V2.9 evidence strength synthesizer selftest: PASS")


if __name__ == "__main__":
    main()
