#!/usr/bin/env python3
"""One-command private daily A-share watchlist review; no orders or automation.

Composes the existing quote adapter, watchlist, and execution readiness evaluator.
A source failure, missing quote or missing broker status never means 'safe to hold'.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

from v29_public_quote_watchlist import fetch_watchlist
from v29_position_watchlist import evaluate_watchlist
from v29_exit_execution_readiness import apply_execution_constraints


def run_daily(positions, at, expected_session, quotes=None, broker_status=None,
              max_quote_age_hours=1.0, live_fetcher=None):
    # Both timestamps are explicit: never silently assume a trading session.
    evaluated = datetime.fromisoformat(at)
    if evaluated.tzinfo is None or evaluated.utcoffset() is None:
        raise ValueError("EVALUATION_REQUIRES_TIMEZONE")
    if evaluated.astimezone(ZoneInfo("Asia/Shanghai")).date().isoformat() != expected_session:
        raise ValueError("EXPECTED_SESSION_DIFFERS_FROM_EVALUATION_DAY")
    if quotes is None:
        fetcher = live_fetcher or fetch_watchlist
        watch = fetcher(positions, at, expected_session,
                        max_quote_age_hours=max_quote_age_hours)
        mode = "PUBLIC_UNOFFICIAL_QUOTE"
    else:
        watch = evaluate_watchlist(positions, quotes, at, max_quote_age_hours)
        mode = "USER_SUPPLIED_QUOTE_SNAPSHOT"
        for p in watch["positions"]:
            ts = p["quote_timestamp"]
            if ts is not None and datetime.fromisoformat(ts).astimezone(
                ZoneInfo("Asia/Shanghai")
            ).date().isoformat() != expected_session:
                # Never treat a previous day's price as usable even if hours are few.
                p["quote_status"] = "WRONG_SESSION"
                if not p["invalidation_triggered"]:
                    # Re-evaluate without that quote to remove any false price trigger.
                    filtered = [q for q in quotes if q["security_id"] != p["security_id"]]
                    return run_daily(positions, at, expected_session, filtered,
                                     broker_status, max_quote_age_hours, live_fetcher)
                # Invalidation is independent and must still force exit.
        watch["unassessable_quote_count"] = sum(
            p["quote_status"] in {"MISSING", "STALE", "WRONG_SESSION"}
            for p in watch["positions"])
    readiness = apply_execution_constraints(watch, broker_status if broker_status is not None else [], at)
    lookup = {x["security_id"]: x for x in readiness["positions"]}
    rows = []
    for p in watch["positions"]:
        execution = lookup[p["security_id"]]
        required = execution["exit_required"]
        qstate = p["quote_status"]
        if required:
            priority = 0
            label = "EXIT_REQUIRED_EXECUTION_UNCONFIRMED"
        elif qstate not in {"USABLE_USER_SUPPLIED"}:
            priority = 1
            label = "UNASSESSABLE_QUOTE"
        else:
            priority = 2
            label = "NO_EXIT_TRIGGER_IN_SNAPSHOT"
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
            "UNASSESSABLE_QUOTE": "行情不可判断｜不得视为安全",
            "NO_EXIT_TRIGGER_IN_SNAPSHOT": "快照未触发退出｜不代表建议持有",
        }[row["decision"]]
        ret = ("未知" if row["unrealized_return_fraction"] is None
               else f"{row['unrealized_return_fraction']:+.2%}")
        lines.append(f"{row['security_id']} ｜ {title} ｜ 未实现收益：{ret}")
        lines.append(f"  行情：{row['quote_status']} ｜ 可卖数量：{row['sellable_quantity'] if row['sellable_quantity'] is not None else '未知'} ｜ 执行：{row['execution_status']}")
        if row["exit_reasons"]:
            lines.append("  退出触发：" + ", ".join(row["exit_reasons"]))
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
    parser.add_argument("--json-out", type=Path, help="Optional local JSON report, never GitHub")
    args = parser.parse_args()
    positions = json.loads(args.positions.read_text(encoding="utf-8"))
    quotes = json.loads(args.quotes.read_text(encoding="utf-8")) if args.quotes else None
    broker = json.loads(args.broker_status.read_text(encoding="utf-8")) if args.broker_status else None
    report = run_daily(positions, args.at, args.expected_session, quotes,
                       broker, args.max_quote_age_hours)
    if args.json_out:
        args.json_out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(render_text(report))


if __name__ == "__main__":
    main()
