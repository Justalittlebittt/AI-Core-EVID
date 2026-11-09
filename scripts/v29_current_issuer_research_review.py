#!/usr/bin/env python3
"""Read-only, source-bound *research reviews* of two real 2026 Q3 A shares.

These are NOT V2.9 Decision Packets: neither strategy alpha nor a user trade
plan is established. Never fill risk fields using synthetic demo values.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo
from pathlib import Path

from v29_growth_310_conditional_result import FRAME, FLAGS, load_fixed

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "research/V2.9_ISSUER_VALUATION_SENSITIVITY_20261030.json"
SCHEMA = "V29_REAL_ISSUER_RESEARCH_REVIEW_V1"
ISSUER_IDS = {"SZSE:300408", "SSE:688002"}
FINANCIAL_CAPTURE_DAY = "2026-10-30"


def build_reviews(original_bytes: bytes) -> dict:
    source = json.loads(original_bytes)
    if (source.get("schema") != "V2.9_ISSUER_EPS_PE_SENSITIVITY_V1"
            or source.get("buy_eligibility") != "NOT_AUTHORIZED"
            or source.get("independent_alpha_evidence") is not False
            or source.get("company_pit_certification") is not False
            or source.get("price_target_certification") is not False):
        raise ValueError("SOURCE_RESEARCH_ONLY_INVARIANTS_CHANGED")

    study_day = date.fromisoformat(source["as_of"])
    reference_day = date.fromisoformat(source["reference_price_session"])
    if reference_day >= study_day:
        raise ValueError("RESEARCH_QUOTE_MUST_PRECEDE_STUDY_DAY")

    cases = source["cases"]
    if (len(cases) != len(ISSUER_IDS)
            or {item["security_id"] for item in cases} != ISSUER_IDS):
        raise ValueError("UNEXPECTED_OR_DUPLICATED_ISSUER_CASES")

    # Reuse already frozen source identities and accounting-risk membership.
    # The vendor snapshot is NOT proof of original issuer publication-time PIT.
    _, _, frozen_selected, _ = load_fixed(ROOT)
    with (ROOT / FRAME).open(encoding="utf-8-sig", newline="") as fp:
        financial_rows = {row["security_id"]: row for row in csv.DictReader(fp)}
    with (ROOT / FLAGS).open(encoding="utf-8-sig", newline="") as fp:
        risk_rows = {row["security_id"]: row for row in csv.DictReader(fp)}
    if (not ISSUER_IDS.issubset(frozen_selected)
            or not ISSUER_IDS.issubset(financial_rows)
            or not ISSUER_IDS.issubset(risk_rows)):
        raise ValueError("REAL_ISSUER_NOT_IN_FROZEN_122")
    frozen_source_hashes = {
        "preoutcome_financial_frame_sha256": hashlib.sha256((ROOT / FRAME).read_bytes()).hexdigest(),
        "preoutcome_source_risk_flags_sha256": hashlib.sha256((ROOT / FLAGS).read_bytes()).hexdigest(),
    }

    reports = []
    for case in cases:
        quote_time = datetime.strptime(case["quote_asof_beijing"], "%Y-%m-%d %H:%M")
        if quote_time.date() != reference_day:
            raise ValueError("QUOTE_DATE_SOURCE_MISMATCH")
        price, pe = case["reference_price_cny"], case["vendor_pe_ttm"]
        if not (isinstance(price, (int, float)) and isinstance(pe, (int, float))
                and not isinstance(price, bool) and not isinstance(pe, bool)
                and math.isfinite(price) and math.isfinite(pe) and price > 0 and pe > 0):
            raise ValueError("NONPOSITIVE_OR_INVALID_QUOTE_OR_PE")
        sources = case["sources"]
        if (not isinstance(sources.get("report"), str)
                or not sources["report"].startswith("https://")
                or not isinstance(sources.get("quote"), str)
                or not sources["quote"].startswith("https://")):
            raise ValueError("MISSING_PUBLIC_RESEARCH_SOURCE")
        sid = case["security_id"]
        fin = financial_rows[sid]
        flags = risk_rows[sid]
        if (fin["group"] != "SELECTED_122" or fin["core_source_match_status"] != "MATCHED_BOTH"
                or flags["frozen_selected_122"] != "1"
                or flags["no_specified_risk_flags"] != "1"
                or flags["numeric_growth_and_core_pass"] != "1"
                or flags["source_risk_flags"]):
            raise ValueError("REAL_ISSUER_FROZEN_FINANCIAL_STATUS_MISMATCH:" + sid)
        disclosed = date.fromisoformat(fin["disclosure_date_q3"])
        if disclosed > study_day:
            raise ValueError("REAL_ISSUER_REPORT_DISCLOSED_AFTER_RESEARCH_DATE:" + sid)
        revenue_q3 = float(fin["revenue_yoy_q3_ytd_pct"])
        revenue_h1 = float(fin["revenue_yoy_h1_ytd_pct"])
        reports.append({
            "security_id": sid,
            "issuer": case["name"],
            "research_as_of": study_day.isoformat(),
            "quote_session": reference_day.isoformat(),
            "quote_observation_beijing": case["quote_asof_beijing"],
            "observed_reference_price_cny": price,
            "vendor_labeled_pe_ttm": pe,
            "ytd_gross_margin_2025_pct": case["ytd_gross_margin_2025_pct"],
            "ytd_gross_margin_2026_pct": case["ytd_gross_margin_2026_pct"],
            "frozen_forward_cohort": "V29_122_GROWTH_COHORT_PROSPECTIVE_20261030",
            "frozen_cohort_membership": "SELECTED_122_RESEARCH_ONLY",
            "frozen_financial_capture_date": FINANCIAL_CAPTURE_DAY,
            "financial_data_original_publication_vintage_independently_certified": False,
            "q3_report_disclosure_date": disclosed.isoformat(),
            "quote_and_report_same_calendar_day_release_order_unverified": disclosed == reference_day,
            "financial_source_identity_match": fin["core_source_match_status"],
            "specified_accounting_risk_flags_at_frozen_capture": [],
            "q3_ytd_revenue_yoy_pct": revenue_q3,
            "h1_ytd_revenue_yoy_pct": revenue_h1,
            "revenue_growth_acceleration_pp": revenue_q3 - revenue_h1,
            "q3_ytd_parent_profit_yoy_pct": float(fin["parent_profit_yoy_q3_ytd_pct"]),
            "q3_ytd_weighted_roe_pct": float(fin["roe_pct_q3_ytd"]),
            "q3_ytd_operating_cash_flow_per_share_cny": float(fin["cfo_per_share_q3_ytd"]),
            "standalone_q3_deducted_parent_profit_yuan": float(fin["standalone_q3_deducted_parent_profit_yuan"]),
            "source_urls": sources,
            "candidate_status": "REAL_ISSUER_RESEARCH_ONLY",
            "contemplated_action": None,
            "decision_packet": None,
            "discipline_decision": "NOT_EVALUATED_NO_REAL_TRADE_PLAN_OR_VALIDATED_STRATEGY",
            "human_stop_take_profit_position_size": None,
            "financial_vintage_verified_as_original_release": False,
            "quote_vendor_pe_denominator_independently_verified": False,
            "current_quote_or_executable_fill_verified": False,
            "strategy_alpha_and_untouched_oos_verified": False,
            "buy_add_authorized": False,
            "next_allowed_step": "RESEARCH_OR_COLLECT_FRESH_EVIDENCE_NOT_PLACE_ORDER",
        })

    return {
        "schema": SCHEMA,
        "research_as_of": study_day.isoformat(),
        "financial_research_source_path": str(SOURCE.relative_to(ROOT)),
        "financial_research_source_sha256": hashlib.sha256(original_bytes).hexdigest(),
        "frozen_cohort_financial_source_hashes": frozen_source_hashes,
        "frozen_cohort_preoutcome_snapshot_not_current_market": True,
        "selection_basis": "TWO_PURPOSIVELY_STUDIED_ISSUERS_NOT_OUT_OF_SAMPLE",
        "cases": reports,
        "trade_authorized": False,
        "live_buy_eligibility": "NOT_AUTHORIZED",
        "synthetic_risk_fields_used": False,
        "no_trade_decision_claimed_from_discipline_engine": True,
    }



def render_research_brief(report: dict) -> str:
    """Human-readable historical research only; not a Decision Packet or trade advice."""
    if (report.get("schema") != SCHEMA
            or report.get("trade_authorized") is not False
            or report.get("live_buy_eligibility") != "NOT_AUTHORIZED"
            or report.get("synthetic_risk_fields_used") is not False
            or not isinstance(report.get("financial_research_source_sha256"), str)
            or len(report["financial_research_source_sha256"]) != 64):
        raise ValueError("RESEARCH_BRIEF_SOURCE_NOT_AUTHENTICATED")
    cases = report.get("cases")
    if (not isinstance(cases, list) or len(cases) != len(ISSUER_IDS)
            or {r.get("security_id") for r in cases if isinstance(r, dict)} != ISSUER_IDS
            or any(r.get("decision_packet") is not None
                   or r.get("contemplated_action") is not None
                   or r.get("buy_add_authorized") is not False
                   or r.get("strategy_alpha_and_untouched_oos_verified") is not False
                   for r in cases)):
        raise ValueError("RESEARCH_BRIEF_CANNOT_PROMOTE_TO_DECISION_PACKET")
    lines = [
        "# V2.9 真实公司研究摘要（仅历史观察，不授权交易）", "",
        f"**研究时点：** {report['research_as_of']}；**数据状态：** 不是当前市场行情。",
        "**研究范围：** 两家定向挑选的历史研究案例；非事前盲选，亦非独立样本外策略验证。",
        "**交易资格：** NOT_AUTHORIZED；无真实交易计划，未运行实际交易纪律判定。", "",
    ]
    for case in cases:
        lines.extend([
            f"## {case['issuer']}（{case['security_id']}）", "",
            f"- 历史参考行情：{case['quote_session']} 收盘参考价 ¥{case['observed_reference_price_cny']:.2f}；供应商标记 PE(TTM) {case['vendor_labeled_pe_ttm']:.2f} 倍。",
            f"- 2026 Q3 年初至今营收同比：{case['q3_ytd_revenue_yoy_pct']:+.2f}%；H1 同比：{case['h1_ytd_revenue_yoy_pct']:+.2f}%；差值 {case['revenue_growth_acceleration_pp']:+.2f} 个百分点。",
            f"- 研究来源：财报 {case['source_urls']['report']}；行情 {case['source_urls']['quote']}。",
            "- 未补足的证明：原始披露时点数据版本核验、PE 分母独立核验、独立 OOS 策略有效性、当前可交易行情及真实风险计划。",
            "- **当前允许的下一步：** 补证据、继续观察；不得根据本摘要下单。", "",
        ])
        if case["quote_and_report_same_calendar_day_release_order_unverified"]:
            lines.insert(len(lines)-2, "- **额外时间风险：** 报价与财报披露同日，先后顺序未核实。")
    lines.extend([
        "## 事后原始公告核对（不升级PIT认证）", "",
        "- 2026-11-07追溯核查：research/V2.9_TWO_ISSUER_ORIGINAL_DISCLOSURE_CHECK_20261107.md",
        "- 三环集团原始PDF主要字段已交叉核对；10月28日16:28、17:27和18:30的公开媒体页面提供参考报价前传播旁证，但官方精确披露时刻、历史网页存证及原始文件版本仍未认证。",
        "- 睿创微纳2026-10-27巨潮原始三季报PDF的营业收入、归母/扣非净利润、经营现金流及ROE已直接核对；原件二进制字节、历史版本和其他研究输入字段仍未封存或认证。",
        "- 睿创微纳早在2026-10-16已预告前三季度归母净利润22.50–23.50亿元；10月27日正式净利润约23.00亿元落在此前区间内，不能把正式季报视为盈利增长首次公开。",
        "- 2026-11-09另核对具名、具日期的财报前后机构**全年**盈利预测：research/V2.9_TWO_ISSUER_PRE_EVENT_FORECAST_EVIDENCE_20261109.md；不等同于Q3共识或已认证超预期。",
        "- 后补来源只能改进证据说明，不能追溯认证原始研究的披露时点、PE历史分母或独立OOS。", "",
        "## 证据身份与使用限制", "",
        f"- 原始研究输入 SHA256：`{report['financial_research_source_sha256']}`",
        f"- 输入位置：`{report['financial_research_source_path']}`",
        "- SHA256 为输入身份记录，不能替代公告原件核验；该摘要不是 Decision Packet、估值目标价、未来收益预测或仓位建议。",
        "- **NO BUY / NO ADD：** 证据或纪律证明缺失，不得自动升级为可执行动作。", "",
    ])
    return "\n".join(lines)


def assess_private_capital_capacity(research: dict, account: dict) -> dict:
    """Bounded cash/stop/lot feasibility for two research issuers, NEVER a buy decision.

    All account values and quotes are supplied privately by the caller. No
    brokerage login, public quote retrieval, commission inference or holdings
    aggregation; each security is an ALTERNATIVE stand-alone new position.
    """
    if research["live_buy_eligibility"] != "NOT_AUTHORIZED" or research["trade_authorized"]:
        raise ValueError("UNEXPECTED_REAL_RESEARCH_BUY_AUTHORITY")
    if not isinstance(account, dict):
        raise ValueError("PRIVATE_ACCOUNT_INPUT_NOT_OBJECT")

    def positive(value, field):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("INVALID_PRIVATE_FIELD:" + field)
        number = Decimal(str(value))
        if not number.is_finite() or number <= 0:
            raise ValueError("INVALID_PRIVATE_FIELD:" + field)
        return number

    as_of = datetime.fromisoformat(account["as_of"])
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("PRIVATE_REVIEW_TIME_MUST_HAVE_OFFSET")
    equity = positive(account["account_equity_cny"], "account_equity_cny")
    cash = positive(account["available_cash_cny"], "available_cash_cny")
    if cash > equity:
        raise ValueError("MARGIN_OR_CASH_OVER_EQUITY_NOT_MODELED")
    reserve = account["buy_fee_reserve_cny"]
    if isinstance(reserve, bool) or not isinstance(reserve, (int, float)) or not math.isfinite(reserve) or reserve < 0:
        raise ValueError("INVALID_PRIVATE_FIELD:buy_fee_reserve_cny")
    reserve = Decimal(str(reserve))
    if reserve >= cash:
        raise ValueError("CASH_EXHAUSTED_BY_EXPLICIT_FEE_RESERVE")
    fraction = positive(account["max_single_name_position_fraction"], "max_single_name_position_fraction")
    loss_fraction = positive(account["max_single_name_risk_fraction"], "max_single_name_risk_fraction")
    if fraction > 1 or loss_fraction > 1:
        raise ValueError("RISK_FRACTION_OUTSIDE_ZERO_TO_ONE")
    name_budget = min(cash-reserve, equity*fraction)
    loss_budget = equity*loss_fraction

    known = {r["security_id"] for r in research["cases"]}
    def by_security(records, name):
        if not isinstance(records, list):
            raise ValueError("INVALID_PRIVATE_" + name)
        found = {}
        for item in records:
            if not isinstance(item, dict) or item.get("security_id") not in known or item["security_id"] in found:
                raise ValueError("UNKNOWN_OR_DUPLICATED_PRIVATE_" + name)
            found[item["security_id"]] = item
        return found

    quotes = by_security(account.get("quotes", []), "QUOTES")
    stops = by_security(account.get("stops", []), "STOPS")
    permissions = account.get("permissions", {})
    if not isinstance(permissions, dict):
        raise ValueError("INVALID_ACCOUNT_PERMISSIONS")
    if any(key not in {"chinext", "star"} or type(value) is not bool
           for key, value in permissions.items()):
        raise ValueError("INVALID_ACCOUNT_PERMISSION_VALUE")

    results = []
    for research_case in research["cases"]:
        sid = research_case["security_id"]
        star = sid.startswith("SSE:688")
        board = "star" if star else "chinext"
        minimum, increment = (200, 1) if star else (100, 100)
        quote, stop = quotes.get(sid), stops.get(sid)
        reason = None
        price = None
        if quote is None:
            reason = "NO_USER_SUPPLIED_SAME_DAY_QUOTE"
        else:
            if quote.get("source") != "USER_SUPPLIED_UNVERIFIED":
                raise ValueError("UNVERIFIED_QUOTE_SOURCE_MUST_BE_EXPLICIT")
            price = positive(quote["price_cny"], "price_cny")
            quote_at = datetime.fromisoformat(quote["as_of"])
            if quote_at.tzinfo is None or quote_at.utcoffset() is None:
                raise ValueError("PRIVATE_QUOTE_TIME_MUST_HAVE_OFFSET")
            age_seconds = (as_of-quote_at).total_seconds()
            if (age_seconds < 0 or age_seconds > 7200
                    or quote_at.astimezone(ZoneInfo("Asia/Shanghai")).date()
                    != as_of.astimezone(ZoneInfo("Asia/Shanghai")).date()):
                reason = "QUOTE_STALE_FUTURE_OR_DIFFERENT_SESSION_DAY"

        if reason is None and permissions.get(board) is not True:
            reason = "TRADING_PERMISSION_UNKNOWN_OR_DISABLED"
        if reason is None and stop is None:
            reason = "STOP_PRICE_NOT_SUPPLIED"
        stop_price = positive(stop["stop_price_cny"], "stop_price_cny") if stop is not None else None
        if reason is None and stop_price >= price:
            reason = "STOP_NOT_BELOW_REFERENCE_PRICE"
        minimum_notional = float(minimum*price) if price is not None else None
        hypothetical_shares = None
        if reason is None:
            max_by_notional = int(name_budget/price)
            max_by_loss = int(loss_budget/(price-stop_price))
            allowable = min(max_by_notional, max_by_loss)
            hypothetical_shares = allowable if star else (allowable//increment)*increment
            if hypothetical_shares < minimum:
                reason = "MINIMUM_ORDER_EXCEEDS_CASH_POSITION_OR_RISK_LIMIT"
                hypothetical_shares = None

        results.append({
            "security_id": sid,
            "board": board.upper(),
            "minimum_buy_shares": minimum,
            "subsequent_quantity_increment_shares": increment,
            "minimum_quote_notional_cny": minimum_notional,
            "standalone_hypothetical_max_shares_not_order": hypothetical_shares,
            "standalone_hypothetical_notional_cny":
                float(price*hypothetical_shares) if hypothetical_shares is not None else None,
            "standalone_hypothetical_stop_distance_loss_cny":
                float((price-stop_price)*hypothetical_shares) if hypothetical_shares is not None else None,
            "capacity_status": reason or "PAPER_CAPACITY_ONLY_NOT_TRADE_CLEARANCE",
            "quote_not_broker_authenticated": True,
            "strategy_validated": False,
            "live_buy_eligibility": "NOT_AUTHORIZED",
        })
    return {
        "schema": "V29_TWO_REAL_ISSUER_PRIVATE_CAPITAL_LOT_FEASIBILITY_V1",
        "as_of": account["as_of"],
        "name_budget_cny": float(name_budget),
        "name_stop_loss_budget_cny": float(loss_budget),
        "cash_reserve_cny_user_supplied": float(reserve),
        "cases": results,
        "standalone_alternatives_not_an_aggregate_portfolio": True,
        "stop_gap_risk_can_exceed_quote_stop_loss_estimate": True,
        "quote_not_exchange_or_broker_authenticated": True,
        "fees_not_independently_modeled": True,
        "no_order_execution_or_market_limit_checks": True,
        "research_alpha_still_unvalidated": True,
        "trade_authorized": False,
        "live_buy_eligibility": "NOT_AUTHORIZED",
    }



def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--out", type=Path, help="Optional local research review JSON, never a trade")
    parser.add_argument("--brief-out", type=Path,
                        help="Optional historical Markdown brief; NO BUY and no private account fields")
    parser.add_argument("--private-account-input", type=Path,
                        help="Local-only budget, unverified quotes, stops and permissions; no order")
    args = parser.parse_args()
    report = build_reviews(args.source.read_bytes())
    if args.brief_out:
        if args.brief_out.exists():
            raise ValueError("REFUSE_OVERWRITE_RESEARCH_BRIEF")
        args.brief_out.write_text(render_research_brief(report), encoding="utf-8")
    if args.private_account_input:
        account = json.loads(args.private_account_input.read_text(encoding="utf-8"))
        report = {"research": report,
                  "private_capital_feasibility": assess_private_capital_capacity(report, account)}
    encoded = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        if args.out.exists():
            raise ValueError("REFUSE_OVERWRITE_RESEARCH_REVIEW")
        args.out.write_text(encoded, encoding="utf-8")
    else:
        print(encoded, end="")


if __name__ == "__main__":
    main()
