#!/usr/bin/env python3
"""Precommitted close-location exploratory research. Not a trading signal.

The research contract was committed before any outcomes for this hypothesis
were processed. Historical partitions are NOT pristine OOS.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

import v281_stage1_factor_screen as frozen

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "research/EXPLORATORY_CLOSE_LOCATION_V1.json"
RESULT = ROOT / "research_results/exploratory_close_location_v1.json"


def block_bootstrap_mean(values, seed: int, replicates: int, block_len: int):
    """Resample consecutive signal-date blocks; not security-event IID draws."""
    a = np.asarray(values, dtype=float)
    n = len(a)
    if not n or not np.isfinite(a).all():
        raise ValueError("BOOTSTRAP_REQUIRES_FINITE_DAILY_EXCESS")
    rng = np.random.default_rng(seed)
    starts = np.arange(max(1, n - block_len + 1))
    means = []
    for _ in range(replicates):
        sequence = []
        while len(sequence) < n:
            start = int(rng.choice(starts))
            sequence.extend(a[start:min(n, start + block_len)].tolist())
        means.append(float(np.mean(sequence[:n])))
    return {"replicates": replicates, "seed": seed,
            "block_len_signal_days": block_len,
            "p05": float(np.quantile(means, 0.05)),
            "p95": float(np.quantile(means, 0.95))}


def evaluate_panel(panel: pd.DataFrame, calendar: list[date], benchmark: dict[date, float], contract: dict):
    signal = contract["signal"]
    population = contract["population"]
    outcome = contract["outcome"]
    test = contract["test_plan"]
    first = date.fromisoformat(population["first_signal_date"])
    last = date.fromisoformat(population["last_signal_date"])
    horizon = outcome["primary_horizon_joint_sessions"]
    target = frozen.target_map(calendar, horizon)

    required = {"canonical_security_id", "bar_date", "high", "low", "close"}
    if not required.issubset(panel.columns):
        raise ValueError("MISSING_STOCK_PANEL_FIELDS")
    if panel.duplicated(["canonical_security_id", "bar_date"]).any():
        raise ValueError("DUPLICATE_SECURITY_DATE")

    # The lookup is exclusively for outcomes; no target value enters the signal.
    close_index = panel.set_index(["canonical_security_id", "bar_date"])["close"]
    x = panel.loc[
        (panel["bar_date"] >= first) & (panel["bar_date"] <= last),
        ["canonical_security_id", "bar_date", "high", "low", "close"],
    ].copy()
    for col in ("high", "low", "close"):
        x[col] = pd.to_numeric(x[col], errors="coerce")
    valid = (
        np.isfinite(x["high"]) & np.isfinite(x["low"]) & np.isfinite(x["close"])
        & (x["low"] > 0) & (x["high"] > x["low"])
        & (x["close"] >= x["low"]) & (x["close"] <= x["high"])
    )
    dropped_invalid_signal = int((~valid).sum())
    x = x.loc[valid].copy()
    x["close_location"] = (x["close"] - x["low"]) / (x["high"] - x["low"])
    x["target_date"] = x["bar_date"].map(target)
    dropped_no_horizon = int(x["target_date"].isna().sum())
    x = x[x["target_date"].notna()].copy()
    lookup = pd.MultiIndex.from_arrays(
        [x["canonical_security_id"], x["target_date"]]
    )
    x["target_close"] = close_index.reindex(lookup).to_numpy()
    x["gross_return"] = x["target_close"] / x["close"] - 1.0
    x.loc[~np.isfinite(x["gross_return"]) | (x["gross_return"] <= -1.0),
          "gross_return"] = np.nan

    daily = []
    total_selected = 0
    total_selected_resolved = 0
    total_broad = 0
    total_broad_resolved = 0
    for d, g in x.groupby("bar_date", sort=True):
        if len(g) < signal["minimum_signal_universe_size"]:
            continue
        g = g.sort_values(
            ["close_location", "canonical_security_id"],
            ascending=[False, True], kind="stable",
        )
        k = max(1, int(np.ceil(len(g) * 0.10)))
        chosen = g.head(k)
        chosen_resolved = chosen["gross_return"].dropna()
        market_resolved = g["gross_return"].dropna()
        total_selected += k
        total_selected_resolved += len(chosen_resolved)
        total_broad += len(g)
        total_broad_resolved += len(market_resolved)
        if not len(chosen_resolved) or not len(market_resolved):
            daily.append({"date": d.isoformat(), "status": "OUTCOME_MISSING",
                          "selected_count": k,
                          "selected_resolved": len(chosen_resolved),
                          "universe_count": len(g),
                          "universe_resolved": len(market_resolved)})
            continue
        start_bench = benchmark.get(d)
        end_bench = benchmark.get(target[d])
        csi = (end_bench / start_bench - 1.0
               if start_bench is not None and end_bench is not None
               and np.isfinite(start_bench) and np.isfinite(end_bench)
               and start_bench > 0 and end_bench > 0 else None)
        net = float(chosen_resolved.mean() - outcome["cost_round_trip_fraction"])
        market = float(market_resolved.mean())
        daily.append({
            "date": d.isoformat(), "status": "EVALUATED",
            "period": "DEVELOPMENT" if d.year == 2025 else "CHRONOLOGICAL_NONPRISTINE",
            "selected_count": k, "selected_resolved": len(chosen_resolved),
            "universe_count": len(g), "universe_resolved": len(market_resolved),
            "selected_ids_sha256": hashlib.sha256(
                "\n".join(sorted(chosen["canonical_security_id"])).encode()
            ).hexdigest(),
            "selected_net_return": net, "market_gross_return": market,
            "excess_vs_market": net - market,
            "CSI300_return": float(csi) if csi is not None else None,
            "excess_vs_CSI300": net - csi if csi is not None else None,
        })
    evaluated = [d for d in daily if d["status"] == "EVALUATED"]
    if not evaluated:
        raise ValueError("NO_EVALUABLE_SIGNAL_DATES")
    excess = [d["excess_vs_market"] for d in evaluated]
    bcfg = test["block_bootstrap"]
    bootstrap = block_bootstrap_mean(
        excess, bcfg["seed"], bcfg["replicates"],
        bcfg["consecutive_day_block_length"]
    )
    means = {}
    for part in ("DEVELOPMENT", "CHRONOLOGICAL_NONPRISTINE"):
        a = [d["excess_vs_market"] for d in evaluated if d["period"] == part]
        means[part] = {"evaluated_days": len(a),
                       "mean_excess": float(np.mean(a)) if a else None}
    quarters = {}
    for row in evaluated:
        key = row["date"][:4] + "Q" + str((int(row["date"][5:7]) - 1) // 3 + 1)
        quarters.setdefault(key, []).append(row["excess_vs_market"])
    coverage = (total_selected_resolved / total_selected
                if total_selected else 0.0)
    sufficient = (
        len(evaluated) >= test["minimum_evaluated_days"]
        and coverage >= test["minimum_selected_outcome_coverage"]
    )
    positive = sufficient and (
        float(np.mean(excess)) > 0 and bootstrap["p05"] > 0
        and all(means[part]["mean_excess"] is not None
                and means[part]["mean_excess"] > 0 for part in means)
    )
    status = ("EXPLORATORY_POSITIVE_NONPRISTINE_NO_TRADE_AUTHORITY"
              if positive else "EXPLORATORY_NOT_SUPPORTED_OR_INSUFFICIENT")
    return {
        "schema": contract["schema"] + "_RESULT",
        "research_status": status,
        "research_class": contract["research_class"],
        "strength": "UNSCORED_NO_PRISTINE_OOS",
        "trade_authorized": False,
        "signal": "TOP_DECILE_CLOSE_LOCATION_V1",
        "period": [first.isoformat(), last.isoformat()],
        "evaluated_signal_days": len(evaluated),
        "selected_events": total_selected,
        "selected_outcomes": total_selected_resolved,
        "selected_outcome_coverage": coverage,
        "broad_events": total_broad, "broad_outcomes": total_broad_resolved,
        "broad_outcome_coverage": total_broad_resolved / total_broad,
        "invalid_signal_bars_excluded": dropped_invalid_signal,
        "missing_horizon_rows_excluded": dropped_no_horizon,
        "mean_selected_net_return": float(np.mean(
            [d["selected_net_return"] for d in evaluated])),
        "mean_market_gross_return": float(np.mean(
            [d["market_gross_return"] for d in evaluated])),
        "primary_mean_excess_vs_market": float(np.mean(excess)),
        "mean_excess_vs_CSI300": float(np.mean(
            [d["excess_vs_CSI300"] for d in evaluated
             if d["excess_vs_CSI300"] is not None]))
            if any(d["excess_vs_CSI300"] is not None for d in evaluated) else None,
        "period_summaries": means,
        "quarter_mean_excess": {
            k: float(np.mean(v)) for k, v in sorted(quarters.items())
        },
        "daily_block_bootstrap_mean_excess": bootstrap,
        "minimum_information_floor_pass": bool(sufficient),
        "exploratory_positive_criterion_pass": bool(positive),
        "daily": daily,
        "limitations": [
            "Historical overlapping outcomes, not portfolio returns",
            "2026 chronological partition already indirectly inspected; not pristine OOS",
            "Close_D reference cannot prove entry executable at price known after close",
            "Uncertified price adjustment and live tradeability",
            "Neither positive nor negative results authorize BUY or ADD",
        ],
    }


def main():
    raw = CONTRACT.read_bytes()
    contract = json.loads(raw)
    if contract["status"] != "FROZEN_BEFORE_THIS_EXPERIMENT_OUTCOME_EVALUATION":
        raise RuntimeError("EXPERIMENT_NOT_FROZEN")
    if contract["signal"]["formula"] != "CLV_D=(close_D-low_D)/(high_D-low_D)":
        raise RuntimeError("EXPERIMENT_SIGNAL_DRIFT")

    intervals = frozen.load_intervals()
    stable, mapping = frozen.load_stable_symbols(intervals)
    calendar = frozen.build_joint_calendar()
    stock, bench = frozen.download_sources()
    panel, _, diag = frozen.load_price_panel(
        stock, stable["symbol"].astype(str).tolist(), mapping, intervals
    )
    con = duckdb.connect()
    try:
        bench_rows = con.execute("""
            SELECT CAST(bar_time AS DATE) AS bar_date,
                   CAST(close AS DOUBLE) AS close
            FROM read_parquet(?)
            WHERE CAST(symbol AS VARCHAR)='000300.SS'
              AND CAST(kline_t AS VARCHAR)='1D'
              AND CAST(bar_time AS DATE) <= DATE '2026-09-18'
            ORDER BY bar_date
        """, [str(bench)]).fetchall()
    finally:
        con.close()
    benchmark = {}
    for d, close in bench_rows:
        if d in benchmark:
            raise RuntimeError("DUPLICATE_CSI300_BENCHMARK_DATE")
        benchmark[d] = float(close)
    result = evaluate_panel(panel, calendar, benchmark, contract)
    result["contract_sha256"] = hashlib.sha256(raw).hexdigest()
    result["source_sha256"] = {
        "stock": frozen.KLINE_SHA,
        "benchmark": frozen.BENCH_SHA,
        "official_PIT": frozen.PIT_SHA,
    }
    result["source_panel_diagnostic"] = diag
    RESULT.parent.mkdir(exist_ok=True)
    RESULT.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({k: v for k, v in result.items() if k != "daily"},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
