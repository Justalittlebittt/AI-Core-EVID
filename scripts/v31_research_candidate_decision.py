#!/usr/bin/env python3
"""One-command REAL historical A-share candidates + empirical evidence boundary.

Reuses already-sealed Oct-2026 selection/Nov-02 entry and the 2025 *different*
historical exploratory verdict. No new signal, no outcome read, no broker orders,
and no synthetic stop/position risk fields.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from v29_eight_portfolio_capacity import ROOT, FROZEN, sealed_readiness

HISTORICAL = ROOT / "research/v29_2025_growth_quality_nonpromotion/NONPROMOTION_VERDICT.json"
SCHEMA = "V31_SOURCE_BOUND_REAL_A_SHARE_RESEARCH_DECISION_V1"


def sha256(blob):
    return hashlib.sha256(blob).hexdigest()


def build(root=ROOT):
    root = Path(root)
    # Existing source binding verifies the frozen eight Git blob and the
    # original real Nov-02 entry snapshot, without querying future outcomes.
    ready = sealed_readiness(root)
    pilot_bytes = (root / FROZEN.relative_to(ROOT)).read_bytes()
    historical_bytes = (root / HISTORICAL.relative_to(ROOT)).read_bytes()
    pilot = json.loads(pilot_bytes)
    historical = json.loads(historical_bytes)
    if (historical.get("schema") != "V29_2025_GROWTH_QUALITY_POSTHOC_NONPROMOTION_V1"
            or historical.get("primary_rule_admission") != "DO_NOT_PROMOTE"
            or historical.get("evidence_strength") != "INSUFFICIENT"
            or historical.get("live_buy_eligibility") != "NOT_AUTHORIZED"
            or historical.get("trade_authorized") is not False):
        raise ValueError("HISTORICAL_NONPROMOTION_PROOF_NOT_ACCEPTABLE")
    source_rows = pilot["archived_descriptive_source_only"]["selected_rows"]
    sealed = ready["names_in_original_registered_order"]
    if (len(source_rows) != 8 or
            [x["security_id"] for x in source_rows] != [x["security_id"] for x in sealed] or
            pilot["pre_outcome_rule"]["selected_ids_in_rank_order"] !=
            [x["security_id"] for x in sealed] or
            pilot["strategy_validated"] is not False):
        raise ValueError("FROZEN_SELECTION_AND_SEALED_ENTRY_DIVERGED")
    candidates = []
    for rank, (source, market) in enumerate(zip(source_rows, sealed), 1):
        candidates.append({
            "rank_in_predeclared_2026_research": rank,
            "security_id": source["security_id"],
            "2026_q3_weighted_roe_pct": source["source_roe_pct"],
            "2026_q3_revenue_growth_acceleration_pp": source["revenue_yoy_acceleration_pp"],
            "2026_q3_cash_flow_per_share_cny": source["source_cfo_per_share_yuan"],
            "original_report_notice_day": source["source_disclosure_date"],
            "pre_entry_selection_reference_close_cny": source["reference_close_cny"],
            "sealed_nov02_paper_entry_close_cny": market["sealed_2026_11_02_entry_close_cny"],
            "min_exchange_lot_shares": market["minimum_lot_shares"],
            "min_lot_paper_entry_notional_cny": market["minimum_lot_reference_notional_cny"],
            "risk_and_account_inputs": None,
            "action": "NO_ACTION_INSUFFICIENT_PREDICTIVE_EVIDENCE",
        })
    primary = historical["screen_results"]["growth_plus_roe_equal_rank"]
    return {
        "schema": SCHEMA,
        "candidate_research_asof": "2026-10-30",
        "selection_uses_nov02_entry_quotes": False,
        "quote_reference_session_not_current": ready["reference_session"],
        "current_quote_or_executable_fill_certified": False,
        "candidate_origin": "FROZEN_2026_122_SUBSET_PREOUTCOME_EIGHT",
        "candidate_strategy_independently_validated": False,
        "separate_2025_historical_screen_not_equivalent_to_2026_eight": {
            "interpretation": "CONTEXT_ONLY_DIFFERENT_RULE_DIFFERENT_FINANCIAL_VINTAGE",
            "historical_rule": "GROWTH_PLUS_ROE_EQUAL_RANK",
            "historical_selected_count": primary["selected_count"],
            "historical_selected_minus_same_entry_day_random_net": primary[
                "selection_minus_same_day_random_mean_net_stock_return"],
            "historical_admission": historical["primary_rule_admission"],
        },
        "source_sha256": {
            "frozen_preentry_eight": sha256(pilot_bytes),
            "sealed_122_nov02_entry": ready["source_entry_sha256"],
            "2025_historical_nonpromotion": sha256(historical_bytes),
        },
        "eight_minimum_lot_paper_entry_notional_cny": ready["minimum_lot_gross_reference_cost_cny"],
        "candidates": candidates,
        "candidate_count": len(candidates),
        "future_outcomes_read": False,
        "paper_closes_not_real_buy_fills": True,
        "real_user_stop_size_cash_permissions_provided": False,
        "action": "NO_ACTION_INSUFFICIENT_PREDICTIVE_EVIDENCE",
        "trade_authorized": False,
        "live_buy_eligibility": "NOT_AUTHORIZED",
    }


def render(report):
    if (report.get("schema") != SCHEMA or report.get("trade_authorized") is not False
            or report.get("live_buy_eligibility") != "NOT_AUTHORIZED"
            or report.get("candidate_strategy_independently_validated") is not False
            or report.get("candidate_count") != 8
            or any(x.get("action") != "NO_ACTION_INSUFFICIENT_PREDICTIVE_EVIDENCE"
                   for x in report.get("candidates", []))):
        raise ValueError("UNSAFE_CANDIDATE_BRIEF_CANNOT_PROMOTE_BUY")
    lines = [
        "# A股真实股票研究候选｜非买入建议",
        "",
        "原始选股日：2026-10-30；行情参考日：2026-11-02（非最新行情、非真实成交）。",
        "固定8股属于已观察财务信息下的探索性子集；没有独立样本外预测优势证明。",
        "2025年的增长+ROE历史研究是**另一套规则**，只能作为负面背景证据，不能充当2026年8股策略的有效性检验。",
        "",
        "| 研究排名 | 股票 | Q3 ROE | 营收增速加速度 | 最低一手收盘参考金额 | 当前决策 |",
        "|---:|---|---:|---:|---:|---|",
    ]
    for r in report["candidates"]:
        lines.append(
            f"| {r['rank_in_predeclared_2026_research']} | {r['security_id']} | "
            f"{r['2026_q3_weighted_roe_pct']:.2f}% | "
            f"{r['2026_q3_revenue_growth_acceleration_pp']:+.2f}pp | "
            f"¥{r['min_lot_paper_entry_notional_cny']:,.2f} | 不授权买入 |"
        )
    lines += [
        "",
        f"最低交易单位收盘代理金额合计：¥{report['eight_minimum_lot_paper_entry_notional_cny']:,.2f}；"
        "未计真实交易费用、滑点和个人风险约束。",
        f"**结论：{report['action']}。**",
        "没有读取尚未成熟的前瞻结果；无当前行情验证；不填造个人止损或仓位。",
        "",
    ]
    return "\n".join(lines)


def main():
    p = argparse.ArgumentParser(description="Read-only genuine historical candidates and decision evidence.")
    p.add_argument("--format", choices=("markdown", "json"), default="markdown")
    args = p.parse_args()
    report = build()
    print(json.dumps(report, ensure_ascii=False, indent=2) if args.format == "json" else render(report))


if __name__ == "__main__":
    main()
