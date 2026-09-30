from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict

import pandas as pd


REQUIRED_COLUMNS = {"observation_id", "strategy_return", "benchmark_return"}
EVIDENCE_STRENGTH = "UNSCORED_PENDING_THRESHOLD_CONTRACT"


@dataclass(frozen=True)
class EvaluationResult:
    evidence_strength: str
    metrics: Dict[str, Any]


def _numeric(series: pd.Series, name: str) -> pd.Series:
    out = pd.to_numeric(series, errors="coerce")
    if out.isna().any():
        bad = int(out.isna().sum())
        raise ValueError(f"{name} contains {bad} non-numeric/null values")
    return out.astype(float)


def validate_observations(df: pd.DataFrame) -> pd.DataFrame:
    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(f"missing required columns: {sorted(missing)}")
    if df.empty:
        raise ValueError("observation table is empty")
    if df["observation_id"].isna().any() or df["observation_id"].astype(str).str.len().eq(0).any():
        raise ValueError("observation_id must be non-empty")
    if df["observation_id"].duplicated().any():
        raise ValueError("observation_id must be unique")

    out = df.copy()
    out["strategy_return"] = _numeric(out["strategy_return"], "strategy_return")
    out["benchmark_return"] = _numeric(out["benchmark_return"], "benchmark_return")

    if "transaction_cost" in out.columns:
        out["transaction_cost"] = _numeric(out["transaction_cost"], "transaction_cost")
        if (out["transaction_cost"] < 0).any():
            raise ValueError("transaction_cost cannot be negative")
    else:
        out["transaction_cost"] = 0.0

    out["net_return"] = out["strategy_return"] - out["transaction_cost"]
    out["excess_return"] = out["net_return"] - out["benchmark_return"]
    return out


def _core_metrics(df: pd.DataFrame) -> Dict[str, Any]:
    return {
        "n": int(len(df)),
        "mean_strategy_return": float(df["strategy_return"].mean()),
        "median_strategy_return": float(df["strategy_return"].median()),
        "mean_net_return": float(df["net_return"].mean()),
        "median_net_return": float(df["net_return"].median()),
        "mean_benchmark_return": float(df["benchmark_return"].mean()),
        "mean_excess_return": float(df["excess_return"].mean()),
        "median_excess_return": float(df["excess_return"].median()),
        "positive_net_return_share": float((df["net_return"] > 0).mean()),
        "p10_net_return": float(df["net_return"].quantile(0.10)),
        "mean_transaction_cost": float(df["transaction_cost"].mean()),
        "mean_gross_to_net_drag": float((df["strategy_return"] - df["net_return"]).mean()),
    }


def _group_metrics(df: pd.DataFrame, column: str) -> Dict[str, Any]:
    return {
        str(k): _core_metrics(g)
        for k, g in df.groupby(column, dropna=False, sort=True)
    }


def evaluate_observations(df: pd.DataFrame) -> EvaluationResult:
    x = validate_observations(df)
    metrics: Dict[str, Any] = {"overall": _core_metrics(x)}

    if "sample_partition" in x.columns:
        metrics["by_sample_partition"] = _group_metrics(x, "sample_partition")

    if "regime" in x.columns:
        metrics["by_regime"] = _group_metrics(x, "regime")

    if "parameter_variant" in x.columns:
        metrics["by_parameter_variant"] = _group_metrics(x, "parameter_variant")

    if "security_id" in x.columns:
        counts = x["security_id"].astype(str).value_counts(dropna=False)
        metrics["cross_sectional_concentration"] = {
            "distinct_security_count": int(counts.size),
            "maximum_single_security_observation_share": float(counts.iloc[0] / len(x)),
        }

    if {"predicted_probability", "realized_positive"}.issubset(x.columns):
        p = _numeric(x["predicted_probability"], "predicted_probability")
        y = _numeric(x["realized_positive"], "realized_positive")
        if ((p < 0) | (p > 1)).any():
            raise ValueError("predicted_probability must be within [0, 1]")
        if not y.isin([0.0, 1.0]).all():
            raise ValueError("realized_positive must be binary 0/1")
        metrics["calibration"] = {
            "n": int(len(x)),
            "mean_predicted_probability": float(p.mean()),
            "realized_positive_rate": float(y.mean()),
            "brier_score": float(((p - y) ** 2).mean()),
        }

    metrics["drawdown"] = {
        "status": "NOT_COMPUTED_FROM_UNORDERED_EVENT_OBSERVATIONS",
        "reason": "requires an explicitly defined chronological portfolio return series",
    }
    return EvaluationResult(EVIDENCE_STRENGTH, metrics)
