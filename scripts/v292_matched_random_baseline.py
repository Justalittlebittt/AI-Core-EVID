from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict

import numpy as np
import pandas as pd


REQUIRED_COLUMNS = {
    "opportunity_set_id",
    "security_id",
    "system_selected",
    "realized_net_return",
}
BASELINE_SCOPE = "CONDITIONAL_SELECTION_ONLY"


@dataclass(frozen=True)
class MatchedRandomResult:
    metrics: Dict[str, Any]
    random_replicates: pd.DataFrame


def _validate_bool(series: pd.Series, name: str) -> pd.Series:
    if series.map(type).ne(bool).any():
        raise ValueError(f"{name} must contain native booleans only")
    return series.astype(bool)


def _numeric(series: pd.Series, name: str) -> pd.Series:
    out = pd.to_numeric(series, errors="coerce")
    if out.isna().any():
        raise ValueError(f"{name} contains non-numeric/null values")
    if not np.isfinite(out.to_numpy(dtype=float)).all():
        raise ValueError(f"{name} contains non-finite values")
    return out.astype(float)


def validate_opportunities(df: pd.DataFrame) -> pd.DataFrame:
    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(f"missing required columns: {sorted(missing)}")
    if df.empty:
        raise ValueError("opportunity table is empty")

    x = df.copy()
    for col in ("opportunity_set_id", "security_id"):
        if x[col].isna().any() or x[col].astype(str).str.strip().eq("").any():
            raise ValueError(f"{col} must be non-empty")
        x[col] = x[col].astype(str)

    if x.duplicated(["opportunity_set_id", "security_id"]).any():
        raise ValueError("opportunity_set_id/security_id pair must be unique")

    x["system_selected"] = _validate_bool(x["system_selected"], "system_selected")
    x["realized_net_return"] = _numeric(x["realized_net_return"], "realized_net_return")
    if (x["realized_net_return"] <= -1.0).any():
        raise ValueError("realized_net_return must be greater than -1.0")

    for col in ("sample_partition", "regime"):
        if col in x.columns:
            conflicts = x.groupby("opportunity_set_id")[col].nunique(dropna=False)
            if (conflicts > 1).any():
                raise ValueError(f"{col} conflicts within one opportunity_set_id")

    selected_counts = x.groupby("opportunity_set_id")["system_selected"].sum().astype(int)
    set_sizes = x.groupby("opportunity_set_id").size().astype(int)
    if (selected_counts > set_sizes).any():
        raise ValueError("selected count exceeds opportunity set size")
    return x.sort_values(["opportunity_set_id", "security_id"]).reset_index(drop=True)


def _selection_metrics(returns: np.ndarray) -> Dict[str, float]:
    if len(returns) == 0:
        raise ValueError("selection is empty")
    log_growth = np.log1p(returns)
    return {
        "n": int(len(returns)),
        "hit_rate": float((returns > 0).mean()),
        "mean_net_return": float(returns.mean()),
        "median_net_return": float(np.median(returns)),
        "geometric_mean_return": float(np.exp(log_growth.mean()) - 1.0),
    }


def evaluate_matched_random(
    df: pd.DataFrame,
    *,
    replicate_count: int = 5000,
    seed: int = 2901,
) -> MatchedRandomResult:
    if type(replicate_count) is not int or replicate_count <= 0:
        raise ValueError("replicate_count must be a positive integer")
    if type(seed) is not int:
        raise ValueError("seed must be an integer")

    x = validate_opportunities(df)
    system = x[x["system_selected"]]
    if system.empty:
        return MatchedRandomResult(
            metrics={
                "status": "INSUFFICIENT_BASELINE_COMPARISON",
                "baseline_scope": BASELINE_SCOPE,
                "reason": "zero system selections",
                "coverage": {
                    "evaluated_candidate_count": int(len(x)),
                    "eligible_candidate_count": 0,
                    "selection_rate": 0.0,
                    "opportunity_set_count": int(x["opportunity_set_id"].nunique()),
                    "opportunity_sets_with_selection": 0,
                    "opportunity_set_selection_coverage": 0.0,
                },
            },
            random_replicates=pd.DataFrame(),
        )

    system_returns = system["realized_net_return"].to_numpy(dtype=float)
    system_metrics = _selection_metrics(system_returns)

    set_count = int(x["opportunity_set_id"].nunique())
    selected_sets = int(system["opportunity_set_id"].nunique())
    coverage = {
        "evaluated_candidate_count": int(len(x)),
        "eligible_candidate_count": int(len(system)),
        "selection_rate": float(len(system) / len(x)),
        "opportunity_set_count": set_count,
        "opportunity_sets_with_selection": selected_sets,
        "opportunity_set_selection_coverage": float(selected_sets / set_count),
    }

    grouped = []
    for opportunity_set_id, g in x.groupby("opportunity_set_id", sort=True):
        k = int(g["system_selected"].sum())
        if k == 0:
            continue
        grouped.append((str(opportunity_set_id), g["realized_net_return"].to_numpy(dtype=float), k))

    rng = np.random.default_rng(seed)
    rows = []
    for replicate_id in range(replicate_count):
        chosen = []
        for _, returns, k in grouped:
            idx = rng.choice(len(returns), size=k, replace=False)
            chosen.extend(returns[idx].tolist())
        m = _selection_metrics(np.asarray(chosen, dtype=float))
        rows.append({"replicate_id": replicate_id, **m})

    reps = pd.DataFrame(rows)
    random_summary = {}
    for metric in ("hit_rate", "mean_net_return", "geometric_mean_return"):
        s = reps[metric]
        random_summary[metric] = {
            "mean": float(s.mean()),
            "median": float(s.median()),
            "p05": float(s.quantile(0.05)),
            "p95": float(s.quantile(0.95)),
            "system_minus_random_mean": float(system_metrics[metric] - s.mean()),
            "random_replicates_at_or_above_system_share": float((s >= system_metrics[metric]).mean()),
        }

    metrics = {
        "status": "CONDITIONAL_MATCHED_RANDOM_BASELINE_COMPUTED",
        "baseline_scope": BASELINE_SCOPE,
        "replicate_count": replicate_count,
        "seed": seed,
        "coverage": coverage,
        "system": system_metrics,
        "matched_random": random_summary,
        "interpretation_boundary": "Security-selection edge conditional on system activity; not a test of abstention/timing quality and not portfolio CAGR.",
    }
    return MatchedRandomResult(metrics=metrics, random_replicates=reps)
