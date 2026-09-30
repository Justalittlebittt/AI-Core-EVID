from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any, Dict, Optional

import pandas as pd


REQUIRED_COLUMNS = {
    "date",
    "security_id",
    "exposure_weight",
    "security_return",
    "transaction_cost",
}


@dataclass(frozen=True)
class PortfolioPathResult:
    daily: pd.DataFrame
    metrics: Dict[str, Any]


def _numeric(series: pd.Series, name: str) -> pd.Series:
    out = pd.to_numeric(series, errors="coerce")
    if out.isna().any():
        raise ValueError(f"{name} contains non-numeric/null values")
    out = out.astype(float)
    if not out.map(isfinite).all():
        raise ValueError(f"{name} contains non-finite values")
    return out


def validate_path_rows(df: pd.DataFrame) -> pd.DataFrame:
    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(f"missing required columns: {sorted(missing)}")
    if df.empty:
        raise ValueError("portfolio path rows are empty")

    x = df.copy()
    x["date"] = pd.to_datetime(x["date"], errors="coerce")
    if x["date"].isna().any():
        raise ValueError("date contains invalid/null values")
    if x["security_id"].isna().any() or x["security_id"].astype(str).str.len().eq(0).any():
        raise ValueError("security_id must be non-empty")
    if x.duplicated(["date", "security_id"]).any():
        raise ValueError("date/security_id pair must be unique")

    for col in ("exposure_weight", "security_return", "transaction_cost"):
        x[col] = _numeric(x[col], col)
    if (x["transaction_cost"] < 0).any():
        raise ValueError("transaction_cost cannot be negative")
    if (x["security_return"] <= -1.0).any():
        raise ValueError("security_return must be greater than -1.0")

    if "benchmark_return" in x.columns:
        x["benchmark_return"] = _numeric(x["benchmark_return"], "benchmark_return")
        conflicts = x.groupby("date")["benchmark_return"].nunique(dropna=False)
        if (conflicts > 1).any():
            raise ValueError("benchmark_return conflicts within one date")
    for col in ("sample_partition", "regime"):
        if col in x.columns:
            conflicts = x.groupby("date")[col].nunique(dropna=False)
            if (conflicts > 1).any():
                raise ValueError(f"{col} conflicts within one date")

    return x.sort_values(["date", "security_id"]).reset_index(drop=True)


def evaluate_portfolio_path(
    df: pd.DataFrame,
    *,
    periods_per_year: Optional[float] = None,
    risk_free_per_period: Optional[float] = None,
) -> PortfolioPathResult:
    x = validate_path_rows(df)
    x["weighted_return"] = x["exposure_weight"] * x["security_return"]

    agg = {
        "weighted_return": "sum",
        "transaction_cost": "sum",
        "exposure_weight": lambda s: float(s.abs().sum()),
    }
    daily = x.groupby("date", sort=True).agg(agg).rename(
        columns={
            "weighted_return": "gross_return",
            "transaction_cost": "transaction_cost",
            "exposure_weight": "gross_exposure",
        }
    )
    daily["net_return"] = daily["gross_return"] - daily["transaction_cost"]
    if (daily["net_return"] <= -1.0).any():
        raise ValueError("daily net_return must be greater than -1.0")

    if "benchmark_return" in x.columns:
        daily["benchmark_return"] = x.groupby("date")["benchmark_return"].first()
        daily["excess_return"] = daily["net_return"] - daily["benchmark_return"]
    if "sample_partition" in x.columns:
        daily["sample_partition"] = x.groupby("date")["sample_partition"].first()
    if "regime" in x.columns:
        daily["regime"] = x.groupby("date")["regime"].first()

    daily["equity_curve"] = (1.0 + daily["net_return"]).cumprod()
    daily["running_peak"] = daily["equity_curve"].cummax()
    daily["drawdown"] = daily["equity_curve"] / daily["running_peak"] - 1.0

    metrics: Dict[str, Any] = {
        "n_days": int(len(daily)),
        "cumulative_net_return": float(daily["equity_curve"].iloc[-1] - 1.0),
        "maximum_drawdown": float(daily["drawdown"].min()),
        "mean_daily_net_return": float(daily["net_return"].mean()),
        "daily_net_return_volatility": float(daily["net_return"].std(ddof=1)) if len(daily) > 1 else 0.0,
        "positive_day_share": float((daily["net_return"] > 0).mean()),
        "worst_day_return": float(daily["net_return"].min()),
        "best_day_return": float(daily["net_return"].max()),
        "mean_daily_gross_exposure": float(daily["gross_exposure"].mean()),
        "maximum_daily_gross_exposure": float(daily["gross_exposure"].max()),
        "total_transaction_cost": float(daily["transaction_cost"].sum()),
    }

    if "benchmark_return" in daily.columns:
        benchmark_curve = (1.0 + daily["benchmark_return"]).cumprod()
        metrics["cumulative_benchmark_return"] = float(benchmark_curve.iloc[-1] - 1.0)
        metrics["cumulative_excess_return_difference"] = float(
            metrics["cumulative_net_return"] - metrics["cumulative_benchmark_return"]
        )

    if periods_per_year is not None:
        periods_per_year = float(periods_per_year)
        if not isfinite(periods_per_year) or periods_per_year <= 0:
            raise ValueError("periods_per_year must be finite and positive")
        years = len(daily) / periods_per_year
        metrics["annualized_return"] = float(daily["equity_curve"].iloc[-1] ** (1.0 / years) - 1.0)
        metrics["annualized_volatility"] = float(metrics["daily_net_return_volatility"] * periods_per_year ** 0.5)
        if risk_free_per_period is None:
            metrics["sharpe_like"] = {"status": "NOT_COMPUTED_RISK_FREE_NOT_SUPPLIED"}
        else:
            risk_free_per_period = float(risk_free_per_period)
            if not isfinite(risk_free_per_period):
                raise ValueError("risk_free_per_period must be finite")
            excess = daily["net_return"] - risk_free_per_period
            std = float(excess.std(ddof=1)) if len(excess) > 1 else 0.0
            metrics["sharpe_like"] = None if std == 0 else float(excess.mean() / std * periods_per_year ** 0.5)
    else:
        metrics["annualization"] = {"status": "NOT_COMPUTED_PERIODS_PER_YEAR_NOT_SUPPLIED"}

    return PortfolioPathResult(daily=daily, metrics=metrics)
