import pandas as pd

from scripts.v292_matched_random_baseline import evaluate_matched_random, validate_opportunities


def main() -> None:
    df = pd.DataFrame(
        {
            "opportunity_set_id": ["D1", "D1", "D1", "D2", "D2", "D2"],
            "security_id": ["A", "B", "C", "D", "E", "F"],
            "system_selected": [True, False, False, False, True, False],
            "realized_net_return": [0.10, -0.02, 0.01, -0.03, 0.08, 0.00],
            "sample_partition": ["dev", "dev", "dev", "oos", "oos", "oos"],
            "regime": ["bull", "bull", "bull", "range", "range", "range"],
        }
    )

    result = evaluate_matched_random(df, replicate_count=500, seed=2901)
    assert result.metrics["status"] == "MATCHED_RANDOM_BASELINE_COMPUTED"
    assert result.metrics["coverage"]["evaluated_candidate_count"] == 6
    assert result.metrics["coverage"]["eligible_candidate_count"] == 2
    assert abs(result.metrics["coverage"]["selection_rate"] - (2 / 6)) < 1e-12
    assert result.metrics["coverage"]["opportunity_set_selection_coverage"] == 1.0
    assert result.metrics["system"]["n"] == 2
    assert abs(result.metrics["system"]["hit_rate"] - 1.0) < 1e-12
    assert len(result.random_replicates) == 500
    assert set(result.random_replicates.columns) >= {
        "replicate_id", "hit_rate", "mean_net_return", "geometric_mean_return"
    }

    same = evaluate_matched_random(df, replicate_count=500, seed=2901)
    pd.testing.assert_frame_equal(result.random_replicates, same.random_replicates)

    zero = evaluate_matched_random(df.assign(system_selected=False), replicate_count=100, seed=1)
    assert zero.metrics["status"] == "INSUFFICIENT_BASELINE_COMPARISON"
    assert zero.metrics["coverage"]["selection_rate"] == 0.0

    try:
        validate_opportunities(pd.concat([df, df.iloc[[0]]], ignore_index=True))
        raise AssertionError("duplicate opportunity/security should fail")
    except ValueError as exc:
        assert "unique" in str(exc)

    bad_bool = df.copy()
    bad_bool["system_selected"] = ["true", False, False, False, True, False]
    try:
        validate_opportunities(bad_bool)
        raise AssertionError("non-native bool should fail")
    except ValueError as exc:
        assert "native booleans" in str(exc)

    try:
        validate_opportunities(df.assign(realized_net_return=[0.10, -1.0, 0.01, -0.03, 0.08, 0.00]))
        raise AssertionError("return <= -100% should fail")
    except ValueError as exc:
        assert "greater than -1.0" in str(exc)

    conflict = df.copy()
    conflict.loc[1, "sample_partition"] = "oos"
    try:
        validate_opportunities(conflict)
        raise AssertionError("partition conflict within opportunity set should fail")
    except ValueError as exc:
        assert "conflicts" in str(exc)

    print("V2.9 matched random baseline synthetic selftest: PASS")


if __name__ == "__main__":
    main()
