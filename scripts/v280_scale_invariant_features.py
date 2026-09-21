from __future__ import annotations

import math
from typing import Iterable

import numpy as np
import pandas as pd

REQUIRED = [
    "canonical_security_id",
    "bar_date",
    "open",
    "high",
    "low",
    "close",
    "amount",
]

FORBIDDEN_INPUT_PREFIXES = ("fwd", "future_", "outcome_", "target_")

PRICE_SCALE_INVARIANT = [
    "ret_5","ret_10","ret_20","ret_60",
    "close_vs_ma20","close_vs_ma50","close_vs_ma150","close_vs_ma200",
    "ma50_vs_ma150","ma150_vs_ma200","ma200_slope20",
    "dist_high20","dist_high60","dist_high252",
    "rv10","rv20","rv60","rv10_over_rv60",
    "tr_pct","tr_pct_mean10","tr_pct_mean60","tr10_over_tr60",
    "gap1","bar_range_pct",
]

FEATURE_COLUMNS = PRICE_SCALE_INVARIANT + [
    "amount_med20",
    "amount_vs_med20",
]

def _safe_ratio(a: pd.Series, b: pd.Series) -> pd.Series:
    b = b.replace(0.0, np.nan)
    return a / b

def validate_input(df: pd.DataFrame) -> None:
    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        raise ValueError(f"missing required columns: {missing}")
    bad = [c for c in df.columns if c.lower().startswith(FORBIDDEN_INPUT_PREFIXES)]
    if bad:
        raise ValueError(f"forward/outcome-like columns forbidden in feature input: {bad}")

def build_features(df: pd.DataFrame) -> pd.DataFrame:
    validate_input(df)
    x = df.copy()
    x["bar_date"] = pd.to_datetime(x["bar_date"]).dt.date
    x = x.sort_values(["canonical_security_id", "bar_date"], kind="mergesort").reset_index(drop=True)

    out = []
    for cid, g in x.groupby("canonical_security_id", sort=False):
        g = g.copy()
        close = pd.to_numeric(g["close"], errors="coerce")
        open_ = pd.to_numeric(g["open"], errors="coerce")
        high = pd.to_numeric(g["high"], errors="coerce")
        low = pd.to_numeric(g["low"], errors="coerce")
        amount = pd.to_numeric(g["amount"], errors="coerce")

        prev = close.shift(1)
        logret = np.log(_safe_ratio(close, prev))

        for w in (5, 10, 20, 60):
            g[f"ret_{w}"] = _safe_ratio(close, close.shift(w)) - 1.0

        mas = {}
        for w in (20, 50, 150, 200):
            mas[w] = close.rolling(w, min_periods=w).mean()
            g[f"close_vs_ma{w}"] = _safe_ratio(close, mas[w]) - 1.0

        g["ma50_vs_ma150"] = _safe_ratio(mas[50], mas[150]) - 1.0
        g["ma150_vs_ma200"] = _safe_ratio(mas[150], mas[200]) - 1.0
        g["ma200_slope20"] = _safe_ratio(mas[200], mas[200].shift(20)) - 1.0

        for w in (20, 60, 252):
            hi = close.rolling(w, min_periods=w).max()
            g[f"dist_high{w}"] = _safe_ratio(close, hi) - 1.0

        rv = {}
        for w in (10, 20, 60):
            rv[w] = logret.rolling(w, min_periods=w).std(ddof=0)
            g[f"rv{w}"] = rv[w]
        g["rv10_over_rv60"] = _safe_ratio(rv[10], rv[60])

        tr_abs = pd.concat(
            [
                high - low,
                (high - prev).abs(),
                (low - prev).abs(),
            ],
            axis=1,
        ).max(axis=1)
        g["tr_pct"] = _safe_ratio(tr_abs, prev)
        g["tr_pct_mean10"] = g["tr_pct"].rolling(10, min_periods=10).mean()
        g["tr_pct_mean60"] = g["tr_pct"].rolling(60, min_periods=60).mean()
        g["tr10_over_tr60"] = _safe_ratio(g["tr_pct_mean10"], g["tr_pct_mean60"])

        g["gap1"] = _safe_ratio(open_, prev) - 1.0
        g["bar_range_pct"] = _safe_ratio(high - low, prev)

        g["amount_med20"] = amount.rolling(20, min_periods=20).median()
        g["amount_vs_med20"] = _safe_ratio(amount, g["amount_med20"])

        out.append(g)

    result = pd.concat(out, ignore_index=True) if out else x.copy()
    return result

def add_cross_sectional_ranks(
    features: pd.DataFrame,
    factor_columns: Iterable[str],
) -> pd.DataFrame:
    x = features.copy()
    cols = list(factor_columns)
    missing = [c for c in cols if c not in x.columns]
    if missing:
        raise ValueError(f"factor columns missing: {missing}")
    for c in cols:
        x[f"{c}__pct_rank"] = x.groupby("bar_date", sort=False)[c].rank(
            method="average",
            pct=True,
            na_option="keep",
        )
    return x
