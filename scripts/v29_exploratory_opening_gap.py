#!/usr/bin/env python3
"""One precommitted opening-gap exploratory historical evaluation. NEVER grants trade eligibility."""
from __future__ import annotations
import hashlib
import json
from datetime import date
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

import v281_stage1_factor_screen as frozen
from v290_strategy_validity_evaluator import evaluate_observations

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "research/EXPLORATORY_OPENING_GAP_V1.json"


def evaluate_panel(panel: pd.DataFrame, calendar: list[date], benchmark: dict[date, float], contract: dict):
    target = frozen.target_map(calendar, 5)
    previous = {calendar[i]: calendar[i - 1] for i in range(1, len(calendar))}
    x = panel[["canonical_security_id", "bar_date", "open", "close"]].copy()
    if x.duplicated(["canonical_security_id", "bar_date"]).any():
        raise ValueError("DUPLICATE_SECURITY_DATE")
    x.sort_values(["canonical_security_id", "bar_date"], inplace=True)
    x["prior_date"] = x.groupby("canonical_security_id")["bar_date"].shift(1)
    x["prior_close"] = x.groupby("canonical_security_id")["close"].shift(1)
    x["expected_previous"] = x["bar_date"].map(previous)
    x["gap"] = x["open"] / x["prior_close"] - 1.0
    close_index = x.set_index(["canonical_security_id", "bar_date"])["close"]
    first, last = date(2025, 1, 2), date(2026, 9, 9)
    x = x[(x["bar_date"] >= first) & (x["bar_date"] <= last)].copy()
    x = x[(x["prior_date"] == x["expected_previous"]) &
          np.isfinite(x["gap"]) & np.isfinite(x["close"]) &
          (x["open"] > 0) & (x["close"] > 0) & (x["prior_close"] > 0)].copy()
    x["target_date"] = x["bar_date"].map(target)
    x = x[x["target_date"].notna()].copy()
    idx = pd.MultiIndex.from_arrays([x["canonical_security_id"], x["target_date"]])
    x["target_close"] = close_index.reindex(idx).to_numpy()
    x["gross_return"] = x["target_close"] / x["close"] - 1.0
    x.loc[~np.isfinite(x["gross_return"]), "gross_return"] = np.nan
    cost = contract["outcome"]["fixed_round_trip_cost_fraction"]
    observations = []
    daily = []
    for d, g in x.groupby("bar_date", sort=True):
        if len(g) < 100:
            continue
        g = g.sort_values(["gap", "canonical_security_id"], kind="stable")
        selection_n = max(1, int(np.ceil(len(g) * 0.10)))
        chosen = g.head(selection_n)
        realized = chosen["gross_return"].dropna()
        broad = g["gross_return"].dropna()
        if not len(realized) or not len(broad):
            daily.append({"date": d.isoformat(), "selected": selection_n,
                          "selected_outcomes": len(realized), "broad_outcomes": len(broad),
                          "status": "OUTCOME_MISSING"})
            continue
        csi_start, csi_end = benchmark.get(d), benchmark.get(target[d])
        csi = csi_end / csi_start - 1 if csi_start and csi_end and csi_start > 0 else None
        selected_mean = float(realized.mean())
        broad_mean = float(broad.mean())
        period = "DEVELOPMENT" if d.year == 2025 else "CHRONOLOGICAL_NONPRISTINE"
        obs = {"observation_id": d.isoformat(), "strategy_return": selected_mean,
               "benchmark_return": broad_mean, "transaction_cost": cost,
               "sample_partition": period, "regime": d.isoformat()[:7]}
        observations.append(obs)
        daily.append({"date": d.isoformat(), "status": "EVALUATED", "selected": selection_n,
                      "selected_outcomes": len(realized), "broad_outcomes": len(broad),
                      "broad_signal_count": len(g),
                      "selected_net_return": selected_mean - cost,
                      "market_equal_weight_return": broad_mean,
                      "excess_vs_market": selected_mean - cost - broad_mean,
                      "CSI300_return": csi,
                      "excess_vs_CSI300": selected_mean - cost - csi if csi is not None else None,
                      "period": period})
    if not observations:
        raise RuntimeError("NO_EVALUABLE_DATES")
    metrics = evaluate_observations(pd.DataFrame(observations))
    evaluated = [r for r in daily if r["status"] == "EVALUATED"]
    quarter = {}
    for r in evaluated:
        q = r["date"][:4] + "Q" + str((int(r["date"][5:7]) - 1) // 3 + 1)
        quarter.setdefault(q, []).append(r["excess_vs_market"])
    total_selected = sum(r["selected"] for r in daily)
    total_resolved = sum(r.get("selected_outcomes", 0) for r in daily)
    return {
        "schema": "EXPLORATORY_OPENING_GAP_RESULT_V1",
        "study_status": "DESCRIPTIVE_RETROSPECTIVE_NOT_TRADING_AUTHORIZED",
        "precommitted_signal": "opening_gap_bottom_decile",
        "evidence_strength": metrics.evidence_strength,
        "no_trade_authorization": True,
        "days_evaluated": len(evaluated),
        "selected_events": total_selected,
        "selected_outcomes": total_resolved,
        "selected_return_coverage": total_resolved / total_selected,
        "overall": metrics.metrics["overall"],
        "by_period": metrics.metrics["by_sample_partition"],
        "by_quarter_mean_excess": {k: float(np.mean(v)) for k, v in sorted(quarter.items())},
        "mean_excess_vs_CSI300": float(np.mean([r["excess_vs_CSI300"] for r in evaluated if r["excess_vs_CSI300"] is not None])) if any(r["excess_vs_CSI300"] is not None for r in evaluated) else None,
        "daily": daily,
    }


def main():
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    if contract.get("status") != "FROZEN_BEFORE_THIS_EXPERIMENT_OUTCOME_EVALUATION":
        raise RuntimeError("EXPERIMENT_NOT_PREREGISTERED")
    if contract["feature"]["ranking"] != "Most negative opening gap first, stable canonical security ID tie-break":
        raise RuntimeError("UNEXPECTED_RESEARCH_RULE")
    intervals = frozen.load_intervals()
    stable, mapping = frozen.load_stable_symbols(intervals)
    calendar = frozen.build_joint_calendar()
    stock, bench = frozen.download_sources()
    panel, _, _ = frozen.load_price_panel(stock, stable["symbol"].astype(str).tolist(), mapping, intervals)
    con = duckdb.connect()
    try:
        b = con.execute("""
            SELECT CAST(bar_time AS DATE) as bar_date, CAST(close AS DOUBLE) as close
            FROM read_parquet(?) WHERE CAST(symbol AS VARCHAR)='000300.SS'
              AND CAST(kline_t AS VARCHAR)='1D' AND CAST(bar_time AS DATE) <= DATE '2026-09-18'
            ORDER BY bar_date
        """, [str(bench)]).fetchdf()
    finally:
        con.close()
    if b.duplicated("bar_date").any():
        raise RuntimeError("DUPLICATE_CSI300_DATES")
    benchmark = {d: float(c) for d, c in zip(b["bar_date"], b["close"])}
    result = evaluate_panel(panel, calendar, benchmark, contract)
    result["contract_sha256"] = hashlib.sha256(CONTRACT_PATH.read_bytes()).hexdigest()
    result["dataset_identity"] = {
        "stock_revision": frozen.KLINE_REV, "stock_sha256": frozen.KLINE_SHA,
        "benchmark_revision": frozen.BENCH_REV, "benchmark_sha256": frozen.BENCH_SHA,
        "PIT_sha256": frozen.PIT_SHA}
    output = Path("research_results/exploratory_opening_gap_v1.json")
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "daily"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
