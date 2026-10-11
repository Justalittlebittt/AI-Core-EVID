"""A-share index risk metrics: descriptive, outcome-blind, and no trading authorization.

Input: index_id,date,close,source_id,retrieved_at_utc
Index IDs: CSI300 (000300.SH), STAR50 (000688.SH).
A single immutable input CSV snapshot is supplied by the caller; this module NEVER
downloads, backfills, infers trading sessions or asserts historical PIT provenance.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from statistics import stdev

INDEXES = {"000300.SH": "CSI300", "000688.SH": "STAR50"}
VOL_WINDOWS = (20, 60)
REFERENCE_SESSIONS = 252
ANNUALIZATION_SESSIONS = 252
FIELDS = {"index_id", "date", "close", "source_id", "retrieved_at_utc"}


def parse_timestamp(raw: str) -> datetime:
    value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("retrieved_at_utc must include timezone")
    if value.utcoffset() != timedelta(0):
        raise ValueError("retrieved_at_utc must have UTC offset")
    return value


def load_rows(path: Path) -> tuple[dict[str, list[tuple[date, float, str, str]]], str]:
    content = path.read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    text = content.decode("utf-8-sig")
    reader = csv.DictReader(text.splitlines())
    if not FIELDS.issubset(set(reader.fieldnames or [])):
        raise ValueError("MISSING_COLUMNS:" + ",".join(sorted(FIELDS - set(reader.fieldnames or []))))
    groups: dict[str, list[tuple[date, float, str, str]]] = defaultdict(list)
    keys = set()
    for line, row in enumerate(reader, 2):
        idx = str(row["index_id"] or "").strip()
        if idx not in INDEXES:
            raise ValueError(f"UNKNOWN_INDEX:{line}:{idx}")
        d = date.fromisoformat(str(row["date"] or "").strip())
        val = float(str(row["close"] or "").strip())
        if not math.isfinite(val) or val <= 0:
            raise ValueError(f"INVALID_CLOSE:{line}")
        source = str(row["source_id"] or "").strip()
        timestamp = str(row["retrieved_at_utc"] or "").strip()
        if not source or not timestamp:
            raise ValueError(f"MISSING_PROVENANCE:{line}")
        parse_timestamp(timestamp)
        key = (idx, d)
        if key in keys:
            raise ValueError(f"DUPLICATE_INDEX_DATE:{idx}:{d}")
        keys.add(key)
        groups[idx].append((d, val, source, timestamp))
    if not groups:
        raise ValueError("EMPTY_INPUT")
    return groups, digest


def volatility(returns: list[float], window: int) -> float | None:
    if len(returns) < window:
        return None
    return stdev(returns[-window:]) * math.sqrt(ANNUALIZATION_SESSIONS)


def risk_for_index(rows: list[tuple[date, float, str, str]], as_of: date) -> dict:
    rows.sort(key=lambda r: r[0])
    used = [r for r in rows if r[0] <= as_of]
    excluded_future = len(rows) - len(used)
    sources = sorted({r[2] for r in used})
    if len(sources) > 1:
        raise ValueError("MIXED_SOURCE_SNAPSHOT_BLOCK")
    if not used:
        return {"status": "NO_OBSERVATIONS_AS_OF", "sessions": 0,
                "excluded_future_rows": excluded_future}
    latest = used[-1]
    returns = [math.log(used[i][1] / used[i-1][1]) for i in range(1, len(used))]
    vol = {f"rv{w}_annualized": volatility(returns, w) for w in VOL_WINDOWS}
    w = VOL_WINDOWS[0]
    all_rv20 = [stdev(returns[i-w:i]) * math.sqrt(ANNUALIZATION_SESSIONS)
                for i in range(w, len(returns) + 1)]
    pct = None
    if len(all_rv20) >= REFERENCE_SESSIONS:
        trailing = all_rv20[-REFERENCE_SESSIONS:]
        # Nearest-rank empirical CDF, including current observation, no future.
        pct = sum(v <= trailing[-1] for v in trailing) / len(trailing)
    retrieved_timestamps = [parse_timestamp(r[3]) for r in used]
    is_asof_pit = all(t.date() <= as_of for t in retrieved_timestamps)
    return {
        "status": "DESCRIPTIVE_ONLY",
        "index_last_date": latest[0].isoformat(),
        "sessions": len(used),
        "excluded_future_rows": excluded_future,
        "last_close": latest[1],
        "source_id": sources[0],
        "retrieval_span_utc": [min(retrieved_timestamps).isoformat(),
                                max(retrieved_timestamps).isoformat()],
        "retrieved_no_later_than_as_of_date": is_asof_pit,
        "historical_point_in_time_provenance_verified": False,
        "rv20_history_count": len(all_rv20),
        "rv20_percentile_252": pct,
        "percentile_definition": "empirical_CDF_le_current_including_current_252_sessions",
        **vol,
        "limitations": [
            "No independent exchange-calendar or session-completeness check",
            "Snapshot acquisition timestamp alone does not prove historical PIT",
            "Realized, not implied, volatility; no predictive or trade eligibility claim"
        ]
    }


def evaluate(path: Path, as_of: date) -> dict:
    groups, digest = load_rows(path)
    reports = {idx: risk_for_index(groups[idx], as_of) for idx in INDEXES if idx in groups}
    for idx in INDEXES:
        if idx not in groups:
            reports[idx] = {"status": "MISSING_INDEX_INPUT", "sessions": 0}
    return {
        "schema": "AI_CORE_EVID_ASHARE_MARKET_RISK_DESCRIPTIVE_V1",
        "mode": "DESCRIPTIVE_RESEARCH_NOT_TRADING_AUTHORIZATION",
        "as_of": as_of.isoformat(),
        "input_sha256": digest,
        "research_parameters": {"vol_windows_sessions": list(VOL_WINDOWS),
                                "percentile_lookback_sessions": REFERENCE_SESSIONS,
                                "annualization_sessions": ANNUALIZATION_SESSIONS},
        "indices": reports,
        "signal_strength": "UNSCORED",
        "action_eligibility": "NOT_EVALUATED",
        "no_fold3_or_fold4_access": True
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input-csv", type=Path, required=True)
    p.add_argument("--as-of", required=True, help="YYYY-MM-DD")
    p.add_argument("--output-json", type=Path)
    args = p.parse_args()
    out = evaluate(args.input_csv, date.fromisoformat(args.as_of))
    content = json.dumps(out, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if args.output_json:
        args.output_json.write_text(content, encoding="utf-8")
    print(content, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
