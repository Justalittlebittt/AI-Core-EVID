import pandas as pd

from scripts.v290_strategy_validity_evaluator import (
    EVIDENCE_STRENGTH,
    evaluate_observations,
    validate_observations,
)


def main() -> None:
    df = pd.DataFrame(
        {
            "observation_id": ["a", "b", "c", "d"],
            "strategy_return": [0.10, -0.04, 0.06, 0.02],
            "benchmark_return": [0.03, -0.01, 0.02, 0.01],
            "transaction_cost": [0.01, 0.01, 0.01, 0.01],
            "sample_partition": ["train", "train", "oos", "oos"],
            "regime": ["bull", "bear", "bull", "range"],
            "security_id": ["S1", "S1", "S2", "S3"],
            "predicted_probability": [0.8, 0.3, 0.7, 0.6],
            "realized_positive": [1, 0, 1, 1],
            "parameter_variant": ["base", "base", "alt", "alt"],
        }
    )

    result = evaluate_observations(df)
    assert result.evidence_strength == EVIDENCE_STRENGTH
    assert result.metrics["overall"]["n"] == 4
    assert abs(result.metrics["overall"]["mean_net_return"] - 0.025) < 1e-12
    assert abs(result.metrics["overall"]["mean_excess_return"] - 0.0125) < 1e-12
    assert result.metrics["cross_sectional_concentration"]["distinct_security_count"] == 3
    assert abs(result.metrics["cross_sectional_concentration"]["maximum_single_security_observation_share"] - 0.5) < 1e-12
    assert result.metrics["calibration"]["n"] == 4
    assert result.metrics["drawdown"]["status"] == "NOT_COMPUTED_FROM_UNORDERED_EVENT_OBSERVATIONS"
    assert set(result.metrics["by_sample_partition"]) == {"oos", "train"}
    assert result.metrics["by_sample_partition"]["oos"]["n"] == 2
    assert set(result.metrics["by_regime"]) == {"bear", "bull", "range"}
    assert set(result.metrics["by_parameter_variant"]) == {"alt", "base"}

    try:
        validate_observations(df.assign(observation_id=["a", "a", "c", "d"]))
        raise AssertionError("duplicate observation_id should fail")
    except ValueError as exc:
        assert "unique" in str(exc)

    try:
        evaluate_observations(df.assign(predicted_probability=[0.8, 1.3, 0.7, 0.6]))
        raise AssertionError("invalid probability should fail")
    except ValueError as exc:
        assert "[0, 1]" in str(exc)

    try:
        evaluate_observations(df.assign(realized_positive=[1, 2, 1, 1]))
        raise AssertionError("non-binary realized_positive should fail")
    except ValueError as exc:
        assert "binary 0/1" in str(exc)

    try:
        evaluate_observations(df.assign(transaction_cost=[0.01, -0.01, 0.01, 0.01]))
        raise AssertionError("negative transaction cost should fail")
    except ValueError as exc:
        assert "cannot be negative" in str(exc)

    print("V2.9 strategy validity synthetic selftest: PASS")


if __name__ == "__main__":
    main()
