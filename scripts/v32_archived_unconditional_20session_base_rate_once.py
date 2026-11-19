#!/usr/bin/env python3
"""Unconditional 20-session excess-return base-rate from existing archived data.

Pure read-only statistical diagnosis, no new quotes, stock selection or strategy.
The unit of inference is monthly market episode, never stock-date pseudoreplication.
"""
from __future__ import annotations
import gzip
import hashlib
import json
from pathlib import Path
from statistics import mean,median,pstdev

ROOT=Path(__file__).resolve().parents[1]
FOLDER=ROOT/"research/v31_2023_2024_lowvol_one_shot"
OBS=FOLDER/"OBSERVATIONS.json.gz"
REPORT=FOLDER/"RESULT.json"
OUTPUT=Path("/tmp/v32_unconditional_20session_base_rate.json")
COST=.003

def compute():
    raw=gzip.decompress(OBS.read_bytes())
    events=json.loads(raw)
    prior=json.loads(REPORT.read_text())
    if (len(events)!=20 or prior["requested_signal_months"]!=20
        or prior["valid_descriptive_months"]!=20
        or prior["schema"]!="V31_2023_2024_ABSOLUTE_LOW_VOL_HISTORICAL_ONE_SHOT_RESULT_V1"
        or prior["opportunities_source_gzip"]!="OBSERVATIONS.json.gz"):
        raise ValueError("ARCHIVED_SAMPLE_OR_RESULT_CONTRACT_DRIFT")
    months=[]
    for event,closed in zip(events,prior["months"]):
        if (event["signal_date"]!=closed["signal_date"]
            or not closed["admissible_descriptive_month"]):
            raise ValueError("SIGNAL_DATE_SOURCE_MISMATCH")
        # Use ALL eligible stocks, never low-vol selection membership.
        eligible=event["candidates"]
        observed=[x for x in eligible if x["outcome_return"] is not None]
        if len(observed)<40:
            raise ValueError("MONTH_PRICE_OUTCOME_COVERAGE_BELOW_FLOOR")
        benchmark=closed["csi300_price_index_same_window_return"]
        if not isinstance(benchmark,(int,float)):
            raise ValueError("BENCHMARK_RETURN_MISSING")
        net=[float(x["outcome_return"])-COST for x in observed]
        excess=[x-benchmark for x in net]
        # Outlier sensitivity is explanatory only, not a tradable rule.
        no_best=sorted(excess)[:-1]
        months.append({
          "signal_date":event["signal_date"],"year":event["year"],
          "eligible_before_outcome":len(eligible),
          "resolved_after_signal":len(observed),
          "coverage":len(observed)/len(eligible),
          "benchmark_price_index_return":benchmark,
          "base_rate_stock_net_excess_positive":sum(z>0 for z in excess)/len(excess),
          "base_rate_stock_net_return_positive":sum(z>0 for z in net)/len(net),
          "all_eligible_mean_net_excess":mean(excess),
          "all_eligible_median_net_excess":median(excess),
          "all_eligible_mean_excess_without_best_one":mean(no_best),
          "excess_decile_p10":sorted(excess)[int((len(excess)-1)*.1)],
          "excess_decile_p90":sorted(excess)[int((len(excess)-1)*.9)],
          "observed_stock_events_are_not_independent_market_episodes":True,
        })
    years={}
    for year in [2023,2024]:
        rows=[m for m in months if m["year"]==year]
        if not rows:raise ValueError("HISTORICAL_YEAR_MISSING")
        years[str(year)]={
            "month_count":len(rows),
            "monthly_equal_weight_mean_stock_beats_benchmark_fraction":
                mean(m["base_rate_stock_net_excess_positive"] for m in rows),
            "monthly_average_unconditional_stock_net_excess":
                mean(m["all_eligible_mean_net_excess"] for m in rows),
            "months_with_majority_of_stocks_beating_index":
                sum(m["base_rate_stock_net_excess_positive"]>.5 for m in rows),
            "months_all_eligible_mean_above_index":
                sum(m["all_eligible_mean_net_excess"]>0 for m in rows),
        }
    p=[m["base_rate_stock_net_excess_positive"] for m in months]
    ex=[m["all_eligible_mean_net_excess"] for m in months]
    total={
      "schema":"V32_2023_2024_20SESSION_UNCONDITIONAL_BASE_RATE_FROM_ARCHIVE_V1",
      "source_observations_gzip_sha256":hashlib.sha256(OBS.read_bytes()).hexdigest(),
      "source_result_sha256":hashlib.sha256(REPORT.read_bytes()).hexdigest(),
      "status":"RETROSPECTIVE_UNCONDITIONAL_BASE_RATE_ONLY",
      "signal_months":len(months),
      "observed_stock_months":sum(m["resolved_after_signal"] for m in months),
      "equal_month_weight_stock_outperform_probability_proxy":mean(p),
      "across_month_baseline_fraction_standard_deviation":pstdev(p),
      "monthly_rate_min":min(p),"monthly_rate_max":max(p),
      "fraction_of_months_majority_of_stocks_outperform":sum(z>.5 for z in p)/len(p),
      "monthly_mean_unconditional_net_excess":mean(ex),
      "monthly_median_unconditional_net_excess":median(ex),
      "months_with_positive_pool_mean_excess":sum(z>0 for z in ex),
      "by_year":years,"months":months,
      "outcome_fee_proxy":COST,
      "future_stock_prices_not_queried_now":True,
      "vendor_adjusted_2026_archive_not_historical_PIT":True,
      "no_certified_execution_or_total_return":True,
      "probabilities_not_calibrated_for_current_market":True,
      "unconditional_base_rate_is_not_an_alpha_signal":True,
      "existing_frozen_122_8_and_e_layer_not_read":True,
      "trade_authorized":False}
    OUTPUT.write_text(json.dumps(total,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    print("V32_UNCONDITIONAL_BASE_RATE="+json.dumps({k:v for k,v in total.items() if k!="months"},ensure_ascii=False),flush=True)

if __name__=="__main__":compute()
