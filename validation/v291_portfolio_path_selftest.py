import pandas as pd

from scripts.v291_portfolio_path_evaluator import evaluate_portfolio_path, validate_path_rows


def main() -> None:
    df = pd.DataFrame(
        {
            "date": ["2026-01-05", "2026-01-05", "2026-01-06", "2026-01-06", "2026-01-07"],
            "security_id": ["S1", "S2", "S1", "S2", "S1"],
            "exposure_weight": [0.5, 0.5, 0.5, 0.5, 1.0],
            "security_return": [0.02, -0.01, -0.03, 0.01, 0.04],
            "transaction_cost": [0.001, 0.001, 0.0, 0.0, 0.001],
            "benchmark_return": [0.004, 0.004, -0.005, -0.005, 0.01],
            "sample_partition": ["train", "train", "oos", "oos", "oos"],
            "regime": ["range", "range", "bear", "bear", "bull"],
        }
    )

    result = evaluate_portfolio_path(df)
    daily = result.daily
    assert len(daily) == 3
    assert abs(daily.iloc[0]["gross_return"] - 0.005) < 1e-12
    assert abs(daily.iloc[0]["net_return"] - 0.003) < 1e-12
    assert result.metrics["maximum_drawdown"] <= 0.0
    assert result.metrics["total_transaction_cost"] == 0.003
    assert result.metrics["annualization"]["status"] == "NOT_COMPUTED_PERIODS_PER_YEAR_NOT_SUPPLIED"
    assert set(daily["sample_partition"]) == {"train", "oos"}

    annualized = evaluate_portfolio_path(df, periods_per_year=252, risk_free_per_period=0.0)
    assert "annualized_return" in annualized.metrics
    assert "annualized_volatility" in annualized.metrics
    assert "sharpe_like" in annualized.metrics

    try:
        validate_path_rows(pd.concat([df, df.iloc[[0]]], ignore_index=True))
        raise AssertionError("duplicate date/security_id should fail")
    except ValueError as exc:
        assert "unique" in str(exc)

    try:
        evaluate_portfolio_path(df.assign(transaction_cost=[0.001, -0.001, 0.0, 0.0, 0.001]))
        raise AssertionError("negative transaction cost should fail")
    except ValueError as exc:
        assert "cannot be negative" in str(exc)

    bad_benchmark = df.copy()
    bad_benchmark.loc[1, "benchmark_return"] = 0.02
    try:
        evaluate_portfolio_path(bad_benchmark)
        raise AssertionError("conflicting benchmark within date should fail")
    except ValueError as exc:
        assert "conflicts" in str(exc)

    try:
        evaluate_portfolio_path(df.assign(security_return=[0.02, -1.0, -0.03, 0.01, 0.04]))
        raise AssertionError("return <= -100% should fail")
    except ValueError as exc:
        assert "greater than -1.0" in str(exc)

    print("V2.9 portfolio path synthetic selftest: PASS")


if __name__ == "__main__":
    main()
