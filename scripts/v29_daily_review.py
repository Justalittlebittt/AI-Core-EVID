#!/usr/bin/env python3
"""One-command private daily A-share watchlist review; no orders or automation.

Composes the existing quote adapter, watchlist, and execution readiness evaluator.
A source failure, missing quote or missing broker status never means 'safe to hold'.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from datetime import date, datetime
from zoneinfo import ZoneInfo

from v29_public_quote_watchlist import fetch_watchlist
from v29_position_watchlist import evaluate_watchlist, timestamp, unique, QUOTE_KEYS
from v29_exit_execution_readiness import apply_execution_constraints


def run_daily(positions, at, expected_session, quotes=None, broker_status=None,
              max_quote_age_hours=1.0, live_fetcher=None, allow_prior_session=False):
    # Default is strict same-day. Opt-in reference mode permits an older session
    # without turning its quote into today's safety or execution clearance.
    evaluated = datetime.fromisoformat(at)
    if evaluated.tzinfo is None or evaluated.utcoffset() is None:
        raise ValueError("EVALUATION_REQUIRES_TIMEZONE")
    china_day = evaluated.astimezone(ZoneInfo("Asia/Shanghai")).date()
    expected_day = date.fromisoformat(expected_session)
    if expected_day.isoformat() != expected_session:
        raise ValueError("EXPECTED_SESSION_DATE_NOT_CANONICAL")
    reference_only = expected_day < china_day
    if expected_day > china_day or (reference_only and not allow_prior_session):
        raise ValueError("EXPECTED_SESSION_DIFFERS_FROM_EVALUATION_DAY")
    if quotes is None:
        fetcher = live_fetcher or fetch_watchlist
        watch = fetcher(positions, at, expected_session,
                        max_quote_age_hours=max_quote_age_hours)
        mode = "PUBLIC_UNOFFICIAL_QUOTE"
    else:
        # Filter wrong-session snapshots BEFORE evaluating stops or targets.
        # Otherwise an old quote could masquerade as a current exit event.
        checked = unique(quotes, "QUOTES", QUOTE_KEYS)
        accepted = []
        rejected = []
        for item in checked.values():
            if timestamp(item["as_of"]).astimezone(
                ZoneInfo("Asia/Shanghai")
            ).date().isoformat() != expected_session:
                rejected.append(item["security_id"])
            else:
                accepted.append(item)
        watch = evaluate_watchlist(positions, accepted, at, max_quote_age_hours)
        mode = "USER_SUPPLIED_QUOTE_SNAPSHOT"
        watch["wrong_session_securities"] = sorted(rejected)
    readiness = apply_execution_constraints(watch, broker_status if broker_status is not None else [], at)
    lookup = {x["security_id"]: x for x in readiness["positions"]}
    rows = []
    for p in watch["positions"]:
        execution = lookup[p["security_id"]]
        required = execution["exit_required"]
        qstate = p["quote_status"]
        if required:
            priority = 0
            label = ("EXIT_REQUIRED_REFERENCE_SESSION_EXECUTION_UNCONFIRMED"
                     if reference_only and qstate == "USABLE_USER_SUPPLIED"
                     else "EXIT_REQUIRED_EXECUTION_UNCONFIRMED")
        elif qstate not in {"USABLE_USER_SUPPLIED"}:
            priority = 1
            label = "UNASSESSABLE_QUOTE"
        else:
            priority = 2
            label = ("REFERENCE_SESSION_NO_EXIT_TRIGGER_NOT_CURRENT_CLEARANCE"
                     if reference_only else "NO_EXIT_TRIGGER_IN_SNAPSHOT")
        rows.append({
            "security_id": p["security_id"],
            "priority": priority, "decision": label,
            "quote_status": qstate, "quote_timestamp": p["quote_timestamp"],
            "unrealized_return_fraction": p["unrealized_return_fraction"],
            "exit_reasons": execution["exit_reason"],
            "sellable_quantity": execution["sellable_quantity"],
            "execution_status": execution["execution_reason"],
            "execution_confirmed": False,
        })
    rows.sort(key=lambda r: (r["priority"], r["security_id"]))
    return {
        "schema": "AI_CORE_EVID_DAILY_WATCHLIST_V1",
        "evaluated_at": at,
        "expected_session": expected_session,
        "reference_session_only": reference_only,
        "current_day_price_or_exit_clearance_established": False if reference_only else None,
        "data_mode": mode,
        "positions_count": len(rows),
        "exit_required_count": readiness["required_exit_count"],
        "unassessable_quote_count": sum(r["decision"] == "UNASSESSABLE_QUOTE" for r in rows),
        "execution_unverified": True,
        "market_feed": watch.get("market_feed"),
        "rows": rows,
        "full_watchlist_input_sha256": watch["input_sha256"],
    }


def render_text(report):
    lines = [
        "A股持仓每日检查（只读，不执行交易）",
        f"评估时间：{report['evaluated_at']} ｜ 预期交易日：{report['expected_session']}",
        f"持仓：{report['positions_count']} ｜ 要求退出：{report['exit_required_count']} ｜ 行情无法判定：{report['unassessable_quote_count']}",
    ]
    for row in report["rows"]:
        title = {
            "EXIT_REQUIRED_EXECUTION_UNCONFIRMED": "必须退出｜尚未确认成交",
            "EXIT_REQUIRED_REFERENCE_SESSION_EXECUTION_UNCONFIRMED": "参考交易日已触发退出｜今天行情与成交未确认",
            "UNASSESSABLE_QUOTE": "行情不可判断｜不得视为安全",
            "NO_EXIT_TRIGGER_IN_SNAPSHOT": "快照未触发退出｜不代表建议持有",
            "REFERENCE_SESSION_NO_EXIT_TRIGGER_NOT_CURRENT_CLEARANCE": "上一交易日未触发退出｜不得视为今天安全",
        }[row["decision"]]
        ret = ("未知" if row["unrealized_return_fraction"] is None
               else f"{row['unrealized_return_fraction']:+.2%}")
        lines.append(f"{row['security_id']} ｜ {title} ｜ 未实现收益：{ret}")
        lines.append(f"  行情：{row['quote_status']} ｜ 可卖数量：{row['sellable_quantity'] if row['sellable_quantity'] is not None else '未知'} ｜ 执行：{row['execution_status']}")
        if row["exit_reasons"]:
            lines.append("  退出触发：" + ", ".join(row["exit_reasons"]))
    if report["reference_session_only"]:
        lines.append("参考复核：只反映指定的历史交易日；不代表今天行情、可交易性或持仓安全。")
    lines.append("注：第三方行情、停牌/T+1 可卖余额及实际成交均未得到独立核验。")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Run one private A-share portfolio review.")
    parser.add_argument("--positions", type=Path, required=True)
    parser.add_argument("--at", required=True, help="Offset-aware ISO8601 evaluation timestamp")
    parser.add_argument("--expected-session", required=True, help="Explicit A-share trading session YYYY-MM-DD")
    parser.add_argument("--quotes", type=Path, help="Optional offline quote snapshot; omit to fetch public data")
    parser.add_argument("--broker-status", type=Path, help="Optional private broker sellability snapshot")
    parser.add_argument("--max-quote-age-hours", type=float, default=1.0)
    parser.add_argument("--allow-prior-session", action="store_true",
                        help="Explicit reference-only review of an older trading session; not today's clearance")
    parser.add_argument("--json-out", type=Path, help="Optional local JSON report, never GitHub")
    args = parser.parse_args()
    positions = json.loads(args.positions.read_text(encoding="utf-8"))
    quotes = json.loads(args.quotes.read_text(encoding="utf-8")) if args.quotes else None
    broker = json.loads(args.broker_status.read_text(encoding="utf-8")) if args.broker_status else None
    report = run_daily(positions, args.at, args.expected_session, quotes,
                       broker, args.max_quote_age_hours,
                       allow_prior_session=args.allow_prior_session)
    if args.json_out:
        args.json_out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(render_text(report))


if __name__ == "__main__":
    main()
