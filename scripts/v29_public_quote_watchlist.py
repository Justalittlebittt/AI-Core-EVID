#!/usr/bin/env python3
"""Public Tencent A-share quote adapter for the *existing* private watchlist.

Not an official/exchange-certified feed. A failed or ambiguous response MUST NOT
produce a current quote. Neither connectivity nor a recent timestamp proves
tradability, continuous trading, or authenticity of a third-party quote.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

from v29_position_watchlist import evaluate_watchlist, POSITION_KEYS, unique, timestamp

SHAPE = re.compile(r'^v_(sh|sz)([0-9]{6})="([^"]*)";?$', re.ASCII)
SID = re.compile(r"^(SSE|SZSE):([0-9]{6})$", re.ASCII)
DATE_STAMP = re.compile(r"^[0-9]{14}$", re.ASCII)
MAX_SECURITIES = 30


def to_vendor_id(security):
    m = SID.fullmatch(security)
    if not m:
        raise ValueError("UNSUPPORTED_EXCHANGE_OR_SECURITY:" + str(security))
    return ("sh" if m.group(1) == "SSE" else "sz") + m.group(2)


def decode_quote(body, expected):
    """Strict per-symbol integrity for Tencent's currently documented tilde payload."""
    if not isinstance(body, str):
        raise ValueError("QUOTE_BODY_NOT_TEXT")
    parsed = {}
    for raw_line in body.strip().splitlines():
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        m = SHAPE.fullmatch(raw_line)
        if not m:
            raise ValueError("UNRECOGNIZED_QUOTE_FORMAT")
        vendor_id = m.group(1) + m.group(2)
        if vendor_id not in expected or vendor_id in parsed:
            raise ValueError("UNEXPECTED_OR_DUPLICATE_QUOTE")
        fields = m.group(3).split("~")
        if len(fields) < 35 or fields[2] != m.group(2) or not DATE_STAMP.fullmatch(fields[30]):
            raise ValueError("QUOTE_SCHEMA_OR_SYMBOL_MISMATCH")
        quote_dt = datetime.strptime(fields[30], "%Y%m%d%H%M%S").replace(
            tzinfo=__import__("zoneinfo").ZoneInfo("Asia/Shanghai")
        )
        price = float(fields[3])
        if not math.isfinite(price) or price <= 0:
            raise ValueError("INVALID_QUOTE_PRICE")
        parsed[vendor_id] = {"price": price, "timestamp": quote_dt}
    if not parsed:
        raise ValueError("EMPTY_QUOTE_RESPONSE")
    return parsed


def fetch_watchlist(positions, evaluation_at, expected_session, max_quote_age_hours=36,
                    opener=urlopen):
    """Network errors yield unknown quote, not a false clear or an invented price."""
    evaluated = timestamp(evaluation_at)
    expected_day = date.fromisoformat(expected_session)
    held = unique(positions, "POSITIONS", POSITION_KEYS)
    if not held or len(held) > MAX_SECURITIES:
        raise ValueError("INVALID_WATCHLIST_SIZE")
    vendor_ids = {to_vendor_id(sid): sid for sid in held}
    requested = sorted(vendor_ids)
    url = "https://qt.gtimg.cn/q=" + ",".join(requested)
    errors = {}
    raw_quotes = []
    try:
        req = Request(url, headers={"User-Agent": "AI-Core-EVID-ReadOnly/1.0"})
        with opener(req, timeout=12) as response:
            raw = response.read(65536)
        parsed = decode_quote(raw.decode("gbk"), set(requested))
    except (OSError, UnicodeError, ValueError) as exc:
        parsed = {}
        errors["__provider__"] = type(exc).__name__ + ":" + str(exc)[:160]
    for vendor, sid in vendor_ids.items():
        q = parsed.get(vendor)
        if q is None:
            errors[sid] = "QUOTE_UNAVAILABLE"
            continue
        if q["timestamp"].date() != expected_day:
            errors[sid] = "WRONG_TRADING_SESSION"
            continue
        if q["timestamp"].astimezone(timezone.utc) > evaluated:
            errors[sid] = "FUTURE_QUOTE"
            continue
        raw_quotes.append({"security_id": sid, "as_of": q["timestamp"].isoformat(),
                           "close": q["price"], "source": "VERIFIED_IMPORT"})
    result = evaluate_watchlist(positions, raw_quotes, evaluation_at, max_quote_age_hours)
    result["market_feed"] = {
        "provider": "TENCENT_FINANCE_UNOFFICIAL_TILDE_ENDPOINT",
        "requested_session": expected_session,
        "requested_count": len(held),
        "accepted_quote_count": len(raw_quotes),
        "unavailable_or_rejected": errors,
        "provider_timestamp_not_independently_certified": True,
        "live_tradability_not_verified": True,
    }
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--positions", required=True, type=Path)
    parser.add_argument("--expected-session", required=True, help="Known trading session date, YYYY-MM-DD")
    parser.add_argument("--at", required=True, help="Offset-aware evaluation timestamp")
    parser.add_argument("--max-quote-age-hours", type=float, default=36)
    args = parser.parse_args()
    positions = json.loads(args.positions.read_text(encoding="utf-8"))
    result = fetch_watchlist(positions, args.at, args.expected_session, args.max_quote_age_hours)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
