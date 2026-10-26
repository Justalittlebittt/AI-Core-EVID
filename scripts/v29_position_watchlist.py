#!/usr/bin/env python3
"""Read-only reusable watchlist: private position file + dated quote snapshot.

Never commits accounts/positions, fetches prices, rewrites stops, or places orders.
Stale/absent quotes cannot clear price-based exits. Independent invalidation can.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path

from v29_position_exit_review import review

POSITION_KEYS = {"security_id", "quantity", "entry_price", "stop_price", "take_profit_price",
                 "position_fraction", "position_limit", "risk_budget_used", "risk_budget_limit",
                 "invalidation_triggered"}
QUOTE_KEYS = {"security_id", "as_of", "close", "source"}
SOURCE_VALUES = {"USER_SUPPLIED", "VERIFIED_IMPORT"}


def timestamp(value):
    if not isinstance(value, str):
        raise ValueError("INVALID_TIMESTAMP")
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError("TIMESTAMP_REQUIRES_UTC_OFFSET")
    return dt.astimezone(timezone.utc)


def unique(rows, kind, fields):
    if not isinstance(rows, list):
        raise ValueError(kind + "_MUST_BE_LIST")
    index = {}
    for row in rows:
        if not isinstance(row, dict) or set(row) != fields:
            raise ValueError(kind + "_SCHEMA_INVALID")
        key = row["security_id"]
        if not isinstance(key, str) or not key.strip() or key in index:
            raise ValueError(kind + "_DUPLICATE_OR_INVALID_SECURITY")
        index[key] = row
    return index


def evaluate_watchlist(positions, quotes, evaluation_at, max_quote_age_hours=72):
    now = timestamp(evaluation_at)
    if isinstance(max_quote_age_hours, bool) or not isinstance(max_quote_age_hours, (int, float)) or not math.isfinite(max_quote_age_hours) or max_quote_age_hours <= 0:
        raise ValueError("INVALID_MAX_QUOTE_AGE")
    held = unique(positions, "POSITIONS", POSITION_KEYS)
    prices = unique(quotes, "QUOTES", QUOTE_KEYS)
    if not held:
        raise ValueError("NO_POSITIONS")
    if set(prices) - set(held):
        raise ValueError("UNMATCHED_QUOTE_SECURITY")
    outputs = []
    for sid, pos in sorted(held.items()):
        raw_quote = prices.get(sid)
        state, price, quote_time, origin = "MISSING", None, None, None
        if raw_quote is not None:
            quote_time = timestamp(raw_quote["as_of"])
            origin = raw_quote["source"]
            if origin not in SOURCE_VALUES:
                raise ValueError("UNRECOGNIZED_QUOTE_SOURCE")
            value = raw_quote["close"]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise ValueError("INVALID_QUOTE_PRICE")
            if quote_time > now:
                raise ValueError("QUOTE_FROM_FUTURE")
            if (now - quote_time).total_seconds() > max_quote_age_hours * 3600:
                state = "STALE"
            else:
                state, price = "USABLE_USER_SUPPLIED", float(value)
        payload = {**pos, "as_of": evaluation_at, "current_price": price}
        outcome = review(payload)
        # For an independent invalidation, EXIT_REQUIRED is preserved even if
        # market quotes are absent or stale; price-trigger state stays unknown.
        if state in {"MISSING", "STALE"} and not pos["invalidation_triggered"]:
            assert outcome["discipline_decision"] is None
        outcome["quote_status"] = state
        outcome["quote_timestamp"] = raw_quote["as_of"] if raw_quote else None
        outcome["quote_source"] = origin
        outcome["market_data_origin"] = "SUPPLIED_SNAPSHOT_NOT_INDEPENDENTLY_VERIFIED"
        outputs.append(outcome)
    payload_hash = hashlib.sha256(json.dumps({"positions": positions, "quotes": quotes, "at": evaluation_at, "max_hours": max_quote_age_hours}, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
    return {
        "schema": "AI_CORE_EVID_WATCHLIST_REVIEW_V1",
        "evaluated_at": evaluation_at,
        "input_sha256": payload_hash,
        "positions_count": len(outputs),
        "exit_required_count": sum(x["status"] == "EXIT_TRIGGERED" for x in outputs),
        "unassessable_quote_count": sum(x["quote_status"] in {"MISSING", "STALE"} for x in outputs),
        "positions": outputs,
        "not_a_broker_or_live_price_feed": True,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--positions", type=Path, required=True)
    parser.add_argument("--quotes", type=Path, required=True)
    parser.add_argument("--at", required=True, help="Offset-aware ISO8601 evaluation timestamp")
    parser.add_argument("--max-quote-age-hours", type=float, default=72)
    args = parser.parse_args()
    positions = json.loads(args.positions.read_text(encoding="utf-8"))
    quotes = json.loads(args.quotes.read_text(encoding="utf-8"))
    print(json.dumps(evaluate_watchlist(positions, quotes, args.at, args.max_quote_age_hours), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
