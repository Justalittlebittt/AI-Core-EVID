#!/usr/bin/env python3
"""Exploratory 2025 factor-conditioned study on 128 frozen historical A-share issuers.

IMPORTANT: 2024 financial YSTZ/WEIGHTAVG_ROE values are 2026 retrospectively
retrieved, NOT 2025-vintage-certified. This is NOT untouched OOS or BUY evidence.
The code reuses the existing V2.9 event and matched-random evaluators.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from v29_growth_candidate_snapshot import _security
from v29_2025_filing_source_coverage import acquire_pages, valid_pages
from v29_historical_universe_sampling import build_frame
from v290_strategy_validity_evaluator import evaluate_observations
from v292_matched_random_baseline import evaluate_matched_random

ROOT = Path(__file__).resolve().parents[1]
FINANCIAL = ROOT / "research/V2.9_2025_128_FILING_SOURCE_COVERAGE.json"
PRICE = ROOT / "research/v29_2025_post_disclosure_price_128/PRICE_PATH_128.json"
SPEC = ROOT / "research/V2.9_2025_128_GROWTH_QUALITY_EXPLORATORY_SPEC.json"
FEATURE_SCHEMA = "V29_2025_128_RETROSPECTIVE_GROWTH_QUALITY_FEATURES_V1"
RESULT_SCHEMA = "V29_2025_128_GROWTH_QUALITY_EXACT_DAY_MATCHED_RANDOM_V1"
METRICS = ("revenue_growth_yoy_pct", "weighted_roe_pct")
SCREENS = ("growth_plus_roe_equal_rank", "revenue_growth_yoy_pct_only",
           "weighted_roe_pct_only")
REPLICATES, SEED, MIN_DAY_SIZE, COST = 3000, 290131, 5, 0.003


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def feature_source_join(raw_vendor_rows, archived_coverage, ordered_ids):
    """Strict 1:1 identity/content match against archived vendor 2026-vintage rows."""
    prior = {x["security_id"]: x for x in archived_coverage["rows"]}
    if (len(prior) != 128 or len(ordered_ids) != 128 or
            set(prior) != set(ordered_ids)):
        raise ValueError("FROZEN_COVERAGE_MEMBER_IDENTITY_MISMATCH")
    matched = {}
    for row in raw_vendor_rows:
        sid = _security(row)
        if sid not in prior:
            continue
        if sid in matched:
            raise ValueError("DUPLICATE_2024_FINANCIAL_SOURCE_ISSUER")
        digest = sha(json.dumps(row, sort_keys=True, ensure_ascii=False,
                                separators=(",", ":")).encode())
        expected = prior[sid]
        if digest not in expected["source_row_hashes"]:
            raise ValueError("RETRIEVED_VENDOR_SOURCE_ROW_HAS_CHANGED:" + sid)
        if (str(row.get("REPORTDATE", ""))[:10] != "2024-12-31" or
            str(row.get("NOTICE_DATE", ""))[:10] not in expected["vendor_announcement_dates"] or
            str(row.get("UPDATE_DATE", ""))[:10] not in expected["vendor_update_dates"] or
            float(row["TOTAL_OPERATE_INCOME"]) != float(expected["vendor_revenue_yuan"]) or
            float(row["PARENT_NETPROFIT"]) != float(expected["vendor_parent_profit_yuan"])):
            raise ValueError("FROZEN_FINANCIAL_PERIOD_NOTICE_OR_VALUES_DRIFT:" + sid)
        matched[sid] = (row, digest)
    if set(matched) != set(ordered_ids):
        raise ValueError("MISSING_FROZEN_VENDOR_FINANCIAL_ROWS")
    output = []
    for sid in ordered_ids:
        row, digest = matched[sid]
        values = {}
        for key, field in (("revenue_growth_yoy_pct", "YSTZ"),
                           ("weighted_roe_pct", "WEIGHTAVG_ROE")):
            raw = row.get(field)
            try:
                value = float(raw)
                values[key] = value if math.isfinite(value) else None
            except (ValueError, TypeError):
                values[key] = None
        output.append({
            "security_id": sid,
            **values,
            "historical_annual_report_notice_day": str(row["NOTICE_DATE"])[:10],
            "vendor_update_day_2026_vintage": str(row["UPDATE_DATE"])[:10],
            "frozen_source_row_sha256": digest,
            "original_asof_financial_field_certified": False,
            "outcome_or_future_price_used_for_feature": False,
            "buy_eligibility": "NOT_AUTHORIZED",
        })
    return output


def _ranking_by_entry_day(features, outcomes):
    feature_map = {r["security_id"]: r for r in features}
    if len(feature_map) != 128 or len(outcomes) != 128:
        raise ValueError("FROZEN_128_FEATURE_OR_OUTCOME_DENOMINATOR_LOST")
    if [x["security_id"] for x in features] != [x["security_id"] for x in outcomes]:
        raise ValueError("FEATURE_AND_OUTCOME_ORDER_MISMATCH")
    population = []
    for outcome in outcomes:
        sid = outcome["security_id"]
        feat = feature_map[sid]
        if feat["historical_annual_report_notice_day"] != outcome["original_report_publication_day"]:
            raise ValueError("FINANCIAL_AND_ORIGINAL_REPORT_NOTICE_MISMATCH:" + sid)
        eligible = (outcome["comparison_eligible"] and
                    all(feat[k] is not None and math.isfinite(feat[k]) for k in METRICS))
        record = {
            "security_id": sid,
            "entry_session": outcome.get("entry_session"),
            "source_notice_day": outcome["original_report_publication_day"],
            "price_observation_status": outcome["price_observation_status"],
            "market_price_comparison_eligible": outcome["comparison_eligible"],
            "factor_source_complete": all(feat[k] is not None for k in METRICS),
            "factor_candidate_eligible": bool(eligible),
            **{k: feat[k] for k in METRICS},
            "selected_by_primary": False,
            "selected_by_revenue": False,
            "selected_by_roe": False,
        }
        if eligible:
            record["stock_unadjusted_price_only_return"] = outcome["stock_price_only_return"]
            record["benchmark_price_index_return"] = outcome["csi300_price_index_return"]
            record["net_stock_price_only_return_after_30bps"] = (
                outcome["stock_price_only_return"] - COST)
            record["net_excess_price_return_vs_csi300"] = (
                outcome["price_only_excess_after_30bps_vs_zero_cost_index"])
        population.append(record)
    groups = defaultdict(list)
    for row in population:
        if row["factor_candidate_eligible"]:
            groups[row["entry_session"]].append(row)
    for day, g in groups.items():
        if len(g) < MIN_DAY_SIZE:
            continue
        k = math.ceil(len(g) / 3)
        rev_order = sorted(g, key=lambda r: (-r["revenue_growth_yoy_pct"], r["security_id"]))
        roe_order = sorted(g, key=lambda r: (-r["weighted_roe_pct"], r["security_id"]))
        rev_rank = {r["security_id"]: i for i, r in enumerate(rev_order)}
        roe_rank = {r["security_id"]: i for i, r in enumerate(roe_order)}
        combined = sorted(g, key=lambda r: (rev_rank[r["security_id"]] +
                                             roe_rank[r["security_id"]], r["security_id"]))
        for r in combined[:k]:
            r["selected_by_primary"] = True
        for r in rev_order[:k]:
            r["selected_by_revenue"] = True
        for r in roe_order[:k]:
            r["selected_by_roe"] = True
    return population


def compare(features, outcomes, spec):
    if (spec.get("schema") != "V29_2025_FIXED_128_GROWTH_QUALITY_EXPLORATORY_COMPARISON_SPEC_V1"
            or spec.get("status") !=
            "EXPLORATORY_RULES_FROZEN_BEFORE_THIS_FACTOR_CONDITIONED_RUN_BUT_2025_RETURNS_ALREADY_OBSERVED"
            or spec.get("same_day_random_baseline", {}).get("seed") != SEED
            or spec.get("same_day_random_baseline", {}).get("replicates") != REPLICATES
            or spec.get("minimum_tradeable_companies_per_same_entry_session") != MIN_DAY_SIZE
            or spec.get("selection_count") != "ceil(number of eligible candidates in exact entry session / 3); stable security_id ascending tie-break"
            or spec.get("primary_rule") != "Rank highest 2024 annual revenue growth YoY and ROE within exact first trade session, combine two rank positions using equal weights, select best one-third of groups with >=5 eligible issuers"
            or spec.get("live_buy_eligibility") != "NOT_AUTHORIZED"):
        raise ValueError("EXPLORATORY_RULES_OR_CONFIG_DRIFT")
    rows = _ranking_by_entry_day(features, outcomes)
    tradable = [r for r in rows if r["factor_candidate_eligible"]]
    selected = [r for r in rows if r["selected_by_primary"]]
    if not selected:
        raise ValueError("NO_UNBIASED_EXACT_DAY_SELECTION_GROUP")
    summaries = {}
    for screen, flag in zip(SCREENS,
                            ("selected_by_primary", "selected_by_revenue",
                             "selected_by_roe")):
        opportunities = pd.DataFrame([{
            "opportunity_set_id": r["entry_session"],
            "security_id": r["security_id"],
            "system_selected": r[flag],
            "realized_net_return": r["net_stock_price_only_return_after_30bps"],
        } for r in tradable])
        random = evaluate_matched_random(opportunities, replicate_count=REPLICATES,
                                         seed=SEED)
        picked = [r for r in tradable if r[flag]]
        events = pd.DataFrame([{
            "observation_id": r["security_id"],
            "security_id": r["security_id"],
            "strategy_return": r["stock_unadjusted_price_only_return"],
            "benchmark_return": r["benchmark_price_index_return"],
            "transaction_cost": COST,
        } for r in picked])
        event = evaluate_observations(events)
        summaries[screen] = {
            "selected_count": len(picked),
            "selected_issuers": [r["security_id"] for r in picked],
            "selected_date_set_count": len({r["entry_session"] for r in picked}),
            "stock_return_vs_market_price_index": event.metrics["overall"],
            "same_day_random_net_stock_return": random.metrics,
            "random_not_a_pristine_p_value": True,
            "event_evaluator_evidence_strength": event.evidence_strength,
        }
    status_counts = {}
    for r in rows:
        st = r["price_observation_status"]
        status_counts[st] = status_counts.get(st, 0) + 1
    qualifying_date_counts = {
        d: sum(r["factor_candidate_eligible"] for r in rows if r["entry_session"] == d)
        for d in sorted({r["entry_session"] for r in tradable})
    }
    return {
        "schema": RESULT_SCHEMA,
        "retrospective_2026_vendor_metrics_not_original_2025_pit": True,
        "fiscal_report":"FY2024_DISCLOSED_IN_2025",
        "frozen_sample_count": len(rows),
        "market_price_comparison_eligible_count":
            sum(r["market_price_comparison_eligible"] for r in rows),
        "factor_complete_tradeable_count": len(tradable),
        "excluded_from_factor_comparison_count": len(rows)-len(tradable),
        "primary_selected_count": len(selected),
        "qualifying_same_entry_session_counts": qualifying_date_counts,
        "same_day_minimum_market_candidates": MIN_DAY_SIZE,
        "identical_entry_date_random_selection": True,
        "multiple_factor_diagnostics_not_strategy_search": len(SCREENS),
        "outcome_status_counts": status_counts,
        "screens": summaries,
        "independent_untouched_oos_validated": False,
        "strategy_admission":"BLOCKED_RETROSPECTIVE_AND_NO_UNTOUCHED_OOS",
        "evidence_strength":"INSUFFICIENT",
        "trade_authorized":False,
        "live_buy_eligibility":"NOT_AUTHORIZED",
        "rows":rows,
    }


def capture(out):
    if out.exists():
        raise ValueError("NO_OVERWRITE_OF_EXPLORATORY_SOURCE_AND_RESULT")
    spec_blob=SPEC.read_bytes()
    spec=json.loads(spec_blob)
    market_blob=PRICE.read_bytes()
    market=json.loads(market_blob)
    if (market.get("schema") != "V29_FY2024_FILING_128_RETROSPECTIVE_20_SESSION_PRICE_PATH_V1"
            or market.get("sample_size") != 128
            or market.get("strategy_validated") is not False
            or market.get("live_buy_eligibility") != "NOT_AUTHORIZED"):
        raise ValueError("FROZEN_128_PRICE_EVIDENCE_INVALID")
    frame=build_frame()
    if [r["security_id"] for r in market["rows"]] != frame["selected_ids"]:
        raise ValueError("HISTORICAL_UNIVERSE_ORDER_NOT_FROZEN")
    coverage=json.loads(FINANCIAL.read_text(encoding="utf-8"))
    if coverage["full_selected_issuer_ids_sha256"] != frame["selected_ids_sha256"]:
        raise ValueError("FINANCIAL_SOURCE_NOT_SAME_FROZEN_SAMPLE")
    pages=acquire_pages()
    vendor_rows, receipts=valid_pages(pages)
    features=feature_source_join(vendor_rows,coverage,frame["selected_ids"])
    report=compare(features,market["rows"],spec)
    feature_document={
        "schema":FEATURE_SCHEMA,
        "captured_at_utc":datetime.now(timezone.utc).isoformat(),
        "frozen_sample_sha256":frame["selected_ids_sha256"],
        "financial_vendor_retrospective_capture_2026":True,
        "vendor_source_total_rows":len(vendor_rows),
        "vendor_pages_count":len(receipts),
        "vendor_current_page_sha256":receipts,
        "matched_archived_frozen_source_row_sha256_count":len(features),
        "original_2025_asof_feature_vintage_certified":False,
        "rows":features,
    }
    report.update({
        "captured_at_utc":datetime.now(timezone.utc).isoformat(),
        "fixed_exploratory_spec_sha256":sha(spec_blob),
        "frozen_price_evidence_sha256":sha(market_blob),
        "frozen_membership_sample_sha256":frame["selected_ids_sha256"],
        "feature_document_sha256":sha(json.dumps(feature_document,ensure_ascii=False,
                                                 sort_keys=True,separators=(",",":")).encode()),
        "source_vendor_row_hashes_match_archived_2026_capture":True,
        "source_vendor_records_not_2025_timestamp_sealed":True,
    })
    out.mkdir(parents=True)
    (out/"FEATURES_128.json").write_text(json.dumps(feature_document,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    (out/"EXPLORATORY_FACTOR_COMPARISON.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({
        "sample_count":report["frozen_sample_count"],
        "tradeable":report["factor_complete_tradeable_count"],
        "primary_selected":report["primary_selected_count"],
        "primary_selected_mean_net_excess":
            report["screens"][SCREENS[0]]["stock_return_vs_market_price_index"]["mean_excess_return"],
        "same_day_random_return_comparison":
            report["screens"][SCREENS[0]]["same_day_random_net_stock_return"]["matched_random"]["mean_net_return"],
        "unseen_oos_validated":False,"live_buy_eligibility":"NOT_AUTHORIZED",
    },ensure_ascii=False),flush=True)
    return report


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--out",type=Path,required=True)
    args=p.parse_args()
    capture(args.out)


if __name__=="__main__":
    main()
