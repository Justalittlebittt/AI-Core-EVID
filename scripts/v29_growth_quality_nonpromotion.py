#!/usr/bin/env python3
"""Offline, post-hoc robustness audit of the already frozen 2025 factor experiment.
NO new ranking, optimized threshold, clean OOS claim, or trading authorization.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import statistics
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "research/v29_2025_growth_quality_matched_baseline/EXPLORATORY_FACTOR_COMPARISON.json"
FEATURES = ROOT / "research/v29_2025_growth_quality_matched_baseline/FEATURES_128.json"
SPEC = ROOT / "research/V2.9_2025_128_GROWTH_QUALITY_EXPLORATORY_SPEC.json"
PRIMARY = "growth_plus_roe_equal_rank"
SCREENS = (PRIMARY, "revenue_growth_yoy_pct_only", "weighted_roe_pct_only")
FLAGS = ("selected_by_primary", "selected_by_revenue", "selected_by_roe")
SCHEMA = "V29_2025_GROWTH_QUALITY_POSTHOC_NONPROMOTION_V1"

def sha(raw):
    return hashlib.sha256(raw).hexdigest()

def mean_excess(rows):
    return statistics.mean(r["net_excess_price_return_vs_csi300"] for r in rows)

def audit(result, features, spec):
    if (result.get("schema") != "V29_2025_128_GROWTH_QUALITY_EXACT_DAY_MATCHED_RANDOM_V1"
            or features.get("schema") != "V29_2025_128_RETROSPECTIVE_GROWTH_QUALITY_FEATURES_V1"
            or spec.get("schema") != "V29_2025_FIXED_128_GROWTH_QUALITY_EXPLORATORY_COMPARISON_SPEC_V1"):
        raise ValueError("FROZEN_EVIDENCE_SCHEMA_MISMATCH")
    rows = result["rows"]
    ids = [r["security_id"] for r in rows]
    source_ids = [r["security_id"] for r in features["rows"]]
    if (len(ids) != 128 or len(set(ids)) != 128 or source_ids != ids
            or result.get("frozen_sample_count") != 128
            or result.get("market_price_comparison_eligible_count") != 120
            or result.get("evidence_strength") != "INSUFFICIENT"
            or result.get("independent_untouched_oos_validated") is not False
            or result.get("live_buy_eligibility") != "NOT_AUTHORIZED"
            or features.get("original_2025_asof_feature_vintage_certified") is not False
            or result.get("source_vendor_records_not_2025_timestamp_sealed") is not True):
        raise ValueError("FROZEN_128_INTEGRITY_OR_ADMISSION_BOUNDARY")
    if (result.get("fixed_exploratory_spec_sha256") !=
            sha((json.dumps(spec, ensure_ascii=False, indent=2)+"\n").encode())):
        raise ValueError("FROZEN_SELECTION_SPEC_HASH_CHANGED")
    if any(r.get("original_asof_financial_field_certified") is not False
           for r in features["rows"]):
        raise ValueError("RETROSPECTIVE_FEATURE_WRONGLY_PROMOTED_TO_PIT")
    if sum(r["market_price_comparison_eligible"] for r in rows) != 120:
        raise ValueError("MISSING_NONTRADEABLE_DENOMINATOR")
    results = {}
    for name, flag in zip(SCREENS, FLAGS):
        chosen = [r for r in rows if r[flag]]
        prior = result["screens"][name]
        if (len(chosen) != prior["selected_count"]
                or [r["security_id"] for r in chosen] != prior["selected_issuers"]
                or any(r["factor_candidate_eligible"] is not True for r in chosen)):
            raise ValueError("STORED_STOCK_SELECTION_MISMATCH:" + name)
        avg = mean_excess(chosen)
        median = statistics.median(r["net_excess_price_return_vs_csi300"] for r in chosen)
        old = prior["stock_return_vs_market_price_index"]
        if (abs(avg-old["mean_excess_return"]) > 1e-12
                or abs(median-old["median_excess_return"]) > 1e-12):
            raise ValueError("STORED_EXCESS_MATH_MISMATCH:" + name)
        matched = prior["same_day_random_net_stock_return"]
        if (matched["seed"] != 290131 or matched["replicate_count"] != 3000
                or matched["baseline_scope"] != "CONDITIONAL_SELECTION_ONLY"):
            raise ValueError("MATCHED_RANDOM_PROTOCOL_DRIFT")
        dates = defaultdict(list)
        for r in chosen:
            dates[r["entry_session"]].append(r)
        days = [{
            "entry_session": day,
            "selected_count": len(dates[day]),
            "mean_net_excess": mean_excess(dates[day]),
        } for day in sorted(dates)]
        top = max(chosen,key=lambda r:(r["net_excess_price_return_vs_csi300"],
                                      r["security_id"]))
        except_top = [r for r in chosen if r["security_id"] != top["security_id"]]
        results[name] = {
            "selected_count":len(chosen),
            "mean_excess":avg,
            "median_excess":median,
            "positive_excess_count":sum(r["net_excess_price_return_vs_csi300"]>0 for r in chosen),
            "same_entry_session_group_count":len(days),
            "negative_mean_excess_group_count":sum(r["mean_net_excess"]<0 for r in days),
            "same_entry_session_results":days,
            "largest_excess_issuer":top["security_id"],
            "largest_excess_value":top["net_excess_price_return_vs_csi300"],
            "largest_issuer_contribution_to_mean":top["net_excess_price_return_vs_csi300"]/len(chosen),
            "mean_excess_excluding_largest_issuer":mean_excess(except_top),
            "selection_minus_same_day_random_mean_net_stock_return":
                matched["matched_random"]["mean_net_return"]["system_minus_random_mean"],
            "same_day_random_draws_at_or_above_selection_share":
                matched["matched_random"]["mean_net_return"]["random_replicates_at_or_above_system_share"],
            "random_tail_share_is_not_an_unseen_oos_p_value":True,
        }
    first=results[PRIMARY]
    reasons=[
        "2026_VENDOR_FINANCIAL_VALUES_NOT_CERTIFIED_HISTORICAL_ASOF",
        "2025_OUTCOMES_ALREADY_OBSERVED_NO_UNTOUCHED_OOS",
        "UNADJUSTED_PRICE_ONLY_VS_PRICE_INDEX_NOT_TOTAL_RETURN",
        "SEVEN_CONCENTRATED_DISCLOSURE_TRADING_EPISODES",
        "ORIGINAL_REPORT_AMOUNT_TEXT_NOT_SEMANTIC_FIELD_VINTAGE_CERTIFICATION",
        "NO_VERIFIED_REALISTIC_EXECUTABLE_FILL_OR_STOP_TAKE_PROFIT_PATH",
    ]
    if first["selection_minus_same_day_random_mean_net_stock_return"]<=0:
        reasons.append("PRIMARY_NOT_BETTER_THAN_SAME_ENTRY_DAY_RANDOM")
    if first["median_excess"]<=0:
        reasons.append("PRIMARY_NONPOSITIVE_MEDIAN_EXCESS")
    if first["mean_excess_excluding_largest_issuer"]<=0:
        reasons.append("PRIMARY_MEAN_REVERSES_WITHOUT_ONE_TOP_WINNER")
    return {
        "schema":SCHEMA,
        "previous_factor_rules_unchanged":True,
        "post_hoc_robustness_not_a_new_predictive_test":True,
        "entire_frozen_sample_count":128,
        "market_comparison_eligible":120,
        "excluded_ST_or_untradeable":8,
        "screen_results":results,
        "primary_rule_admission":"DO_NOT_PROMOTE",
        "revenue_only_diagnostic_admission":"NOT_PROMOTED_AFTER_OBSERVING_2025_OUTCOMES",
        "roe_only_diagnostic_admission":"NOT_PROMOTED_AFTER_OBSERVING_2025_OUTCOMES",
        "reasons":reasons,
        "evidence_strength":"INSUFFICIENT",
        "independent_untouched_oos_validated":False,
        "trade_authorized":False,
        "live_buy_eligibility":"NOT_AUTHORIZED",
    }

def markdown(report):
    data=report["screen_results"]
    primary=data[PRIMARY]
    money=lambda value:f"{100*value:+.3f} pp"
    lines=[
        "# V2.9 FY2024/2025 growth-quality experiment: DO NOT PROMOTE",
        "",
        "Post-hoc robustness audit on already observed 2025 outcomes. No parameter retuning; no OOS claim.",
        "",
        "| Measure | Growth + ROE primary | Revenue growth only | ROE only |",
        "|---|---:|---:|---:|",
    ]
    columns=[data[x] for x in SCREENS]
    measures=[
        ("Selected issuers",lambda x:str(x["selected_count"])),
        ("Mean net price-index excess",lambda x:money(x["mean_excess"])),
        ("Median net price-index excess",lambda x:money(x["median_excess"])),
        ("Stock mean net return minus matched-day random stock mean",
         lambda x:money(x["selection_minus_same_day_random_mean_net_stock_return"])),
        ("Random draws at or above screen (NOT p-value)",
         lambda x:f"{x['same_day_random_draws_at_or_above_selection_share']*100:.2f}%"),
        ("Mean excess removing largest winner (post hoc)",
         lambda x:money(x["mean_excess_excluding_largest_issuer"])),
    ]
    for title,fn in measures:
        lines.append("| "+title+" | "+" | ".join(fn(x) for x in columns)+" |")
    lines.extend(["",f"Primary selection: {primary['positive_excess_count']}/{primary['selected_count']} positive excess outcomes; "
                  f"{primary['negative_mean_excess_group_count']}/{primary['same_entry_session_group_count']} "
                  "entry-day groups have negative mean excess. "
                  f"Single top name {primary['largest_excess_issuer']} contributes "
                  f"{money(primary['largest_issuer_contribution_to_mean'])} to the average.",
                  "",
                  "## Per entry session: primary rule", "",
                  "| Entry session | Selected | Mean net price-index excess |",
                  "|---|---:|---:|"])
    for d in primary["same_entry_session_results"]:
        lines.append(f"| {d['entry_session']} | {d['selected_count']} | {money(d['mean_net_excess'])} |")
    lines.extend([
        "", "## Decision boundary", "",
        "Evidence strength: INSUFFICIENT. Primary rule: DO NOT PROMOTE. BUY: NOT AUTHORIZED.",
        "Revenue-only looks better inside this already inspected sample but may not be promoted based on that observation.",
        "These are price-only close-to-close proxies with a 30bp cost assumption, not verified economic total returns or live fills.",
        "Same-entry-day conditional random is not matched on industry, size, liquidity or other risks.",
        "Random tail percentages must not be treated as untouched-OOS p-values.",
        "",
        "Blocking evidence:", "",
    ])
    lines.extend("- "+r for r in report["reasons"])
    lines.extend([
        "",
        "No more optimization on this 2025 cohort. Continue with the already registered 2026-10-30 "
        "122-issuer prospective experiment and preserve its ORIGINAL CSI300 total-return benchmark, fixed "
        "entry/exit definition, 30bp costs, and all 122 missing-data outcomes.",
        "",
        "Inputs are the frozen 128-company factor result, feature rows and exploratory specification. "
        "Run the standalone v29_growth_quality_nonpromotion.py script with --out-dir to regenerate both files.",
        "",
    ])
    return "\n".join(lines)

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--out-dir",type=Path,required=True)
    args=parser.parse_args()
    if args.out_dir.exists():
        raise ValueError("REFUSE_TO_OVERWRITE_PREVIOUS_AUDIT")
    raw=SOURCE.read_bytes()
    features=FEATURES.read_bytes()
    spec=SPEC.read_bytes()
    report=audit(json.loads(raw),json.loads(features),json.loads(spec))
    report["source_sha256"]={
        "frozen_factor_result":sha(raw),
        "frozen_financial_features":sha(features),
        "fixed_screen_spec":sha(spec),
    }
    args.out_dir.mkdir(parents=True)
    (args.out_dir/"NONPROMOTION_VERDICT.json").write_text(
        json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    (args.out_dir/"NONPROMOTION_VERDICT.md").write_text(markdown(report),encoding="utf-8")
    print(json.dumps({
        "primary_mean_excess":report["screen_results"][PRIMARY]["mean_excess"],
        "primary_excluding_max":report["screen_results"][PRIMARY]["mean_excess_excluding_largest_issuer"],
        "primary_vs_matched_random":
            report["screen_results"][PRIMARY]["selection_minus_same_day_random_mean_net_stock_return"],
        "evidence_strength":"INSUFFICIENT",
        "live_buy_eligibility":"NOT_AUTHORIZED",
    },ensure_ascii=False))

if __name__=="__main__":
    main()
