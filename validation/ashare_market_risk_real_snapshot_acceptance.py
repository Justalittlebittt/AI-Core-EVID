"""Independent public-close acceptance gate for an already acquired immutable index snapshot.

This is a DATA QUALITY gate only. It does not certify historical point-in-time
availability, imply predictive efficacy, or authorize a trading action.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from ashare_market_risk_descriptive import evaluate, load_rows, parse_timestamp

ALLOWED_PROVIDER = "AKSHARE_INDEX_ZH_A_HIST_EASTMONEY"
MIN_CLOSES_FOR_RV20_252 = 1 + 20 + 252 - 1  # 272 consecutive log returns + first close = 273
REQUIRED_INDEXES = {"000300.SH", "000688.SH"}


def accept(snapshot: Path, reference: Path, as_of: date) -> dict:
    authority = json.loads(reference.read_text(encoding="utf-8"))
    if authority.get("schema") != "AI_CORE_EVID_ASHARE_INDEX_CLOSE_REFERENCE_V1":
        raise ValueError("REFERENCE_SCHEMA_BLOCK")
    reference_date = date.fromisoformat(authority["reference_date"])
    if as_of != reference_date:
        raise ValueError("REFERENCE_DATE_ONLY: obtain a new independent close anchor for another session")
    expected = authority["close_points"]
    if set(expected) != REQUIRED_INDEXES:
        raise ValueError("REFERENCE_INDEX_SET_BLOCK")
    tolerance = float(authority["allowed_absolute_difference_points"])
    if not math.isfinite(tolerance) or not (0 <= tolerance <= 0.02):
        raise ValueError("REFERENCE_TOLERANCE_BLOCK")

    groups, input_hash = load_rows(snapshot)
    if set(groups) != REQUIRED_INDEXES:
        raise ValueError("INCOMPLETE_INDEX_SET")
    calendars = []
    checks = {}
    for idx in sorted(REQUIRED_INDEXES):
        records = sorted(groups[idx], key=lambda row: row[0])
        dates = [x[0] for x in records]
        if dates[-1] != reference_date:
            raise ValueError(f"LAST_SESSION_MISMATCH:{idx}:{dates[-1]}")
        if len(records) < MIN_CLOSES_FOR_RV20_252:
            raise ValueError(f"INSUFFICIENT_RV_HISTORY:{idx}:{len(records)}")
        if any(d > as_of for d in dates):
            raise ValueError(f"FUTURE_DATE_IN_SNAPSHOT:{idx}")
        if {r[2] for r in records} != {ALLOWED_PROVIDER}:
            raise ValueError(f"UNAPPROVED_SNAPSHOT_PROVIDER:{idx}")
        # The reference was published at 15:00 Shanghai time (UTC+08).
        # Reject an index snapshot captured before that settlement timestamp.
        close_after_utc = datetime.combine(reference_date, datetime.min.time(), timezone.utc) + timedelta(hours=7)
        if any(parse_timestamp(r[3]) < close_after_utc for r in records):
            raise ValueError(f"CAPTURE_PRECEDES_OFFICIAL_CLOSE:{idx}")
        actual = records[-1][1]
        delta = abs(actual - float(expected[idx]))
        if delta > tolerance + 1e-10:
            raise ValueError(f"INDEPENDENT_CLOSE_MISMATCH:{idx}:{actual}:{expected[idx]}")
        checks[idx] = {
            "sessions": len(records),
            "reference_close": expected[idx],
            "snapshot_close": actual,
            "absolute_close_difference": delta,
            "reference_date": reference_date.isoformat(),
            "reference_crosscheck": "PASS",
        }
        calendars.append(dates)
    if calendars[0] != calendars[1]:
        raise ValueError("INDEX_TRADING_DATES_DISAGREE")
    report = evaluate(snapshot, as_of)
    for idx in sorted(REQUIRED_INDEXES):
        status = report["indices"][idx]
        if status["status"] != "DESCRIPTIVE_ONLY":
            raise ValueError(f"UNEXPECTED_INDEX_STATUS:{idx}")
        if status["rv20_annualized"] is None or status["rv60_annualized"] is None:
            raise ValueError(f"VOLATILITY_HISTORY_BLOCK:{idx}")
        if status["rv20_percentile_252"] is None:
            raise ValueError(f"PERCENTILE_HISTORY_BLOCK:{idx}")
    return {
        "schema": "AI_CORE_EVID_ASHARE_REAL_DATA_ACCEPTANCE_V1",
        "status": "PASS_INDEPENDENT_CLOSE_AND_WINDOW_ONLY",
        "snapshot_sha256": input_hash,
        "reference_sha256": hashlib.sha256(reference.read_bytes()).hexdigest(),
        "reference_url": authority["source_url"],
        "reference_date": reference_date.isoformat(),
        "index_checks": checks,
        "risk_descriptive_report": report,
        "historical_point_in_time_verified": False,
        "independent_trading_calendar_completeness_verified": False,
        "forecasting_skill_or_alpha_verified": False,
        "investment_action_authorized": False,
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input-csv", type=Path, required=True)
    p.add_argument("--reference-json", type=Path, required=True)
    p.add_argument("--as-of", required=True)
    p.add_argument("--output-json", type=Path)
    args = p.parse_args()
    result = accept(args.input_csv, args.reference_json, date.fromisoformat(args.as_of))
    out = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if args.output_json:
        if args.output_json.exists():
            raise FileExistsError("IMMUTABLE_ACCEPTANCE_OUTPUT_ALREADY_EXISTS")
        args.output_json.write_text(out, encoding="utf-8")
    print(out, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
