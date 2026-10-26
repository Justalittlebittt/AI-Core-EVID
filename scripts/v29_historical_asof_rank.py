#!/usr/bin/env python3
"""As-of historical cross-sectional factor exploration (NOT a validated strategy).

Read standalone historical close CSV and an independently supplied as-of universe.
Never accesses V2.8.12 prospective evidence, Fold3/Fold4 or future outcomes.
`ret_20` is explicitly NOT PROMOTED in frozen V2.8.1 research.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
import math
from collections import defaultdict
from datetime import date
from pathlib import Path


def sha256_file(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def load_universe(path, as_of):
    with Path(path).open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if not {"canonical_security_id", "valid_from", "valid_until"}.issubset(reader.fieldnames or []):
            raise ValueError("UNIVERSE_SCHEMA_MISSING")
        ids = set()
        for row in reader:
            cid = row["canonical_security_id"].strip()
            start = date.fromisoformat(row["valid_from"])
            end = date.fromisoformat(row["valid_until"]) if row["valid_until"].strip() else None
            if not cid or end is not None and end < start:
                raise ValueError("INVALID_UNIVERSE_INTERVAL")
            if start <= as_of and (end is None or as_of <= end):
                if cid in ids:
                    raise ValueError("DUPLICATE_ACTIVE_UNIVERSE_ID")
                ids.add(cid)
        if not ids:
            raise ValueError("EMPTY_ACTIVE_UNIVERSE")
    return ids


def rank_historical_closes(prices_path, universe_path, as_of):
    if not isinstance(as_of, date):
        as_of = date.fromisoformat(as_of)
    universe = load_universe(universe_path, as_of)
    data = defaultdict(list)
    seen = set()
    with Path(prices_path).open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if not {"canonical_security_id", "bar_date", "close"}.issubset(reader.fieldnames or []):
            raise ValueError("PRICE_SCHEMA_MISSING")
        for row in reader:
            cid = row["canonical_security_id"].strip()
            bar = date.fromisoformat(row["bar_date"])
            if bar > as_of:
                raise ValueError("FUTURE_BAR_IN_SOURCE")
            if cid not in universe:
                continue
            pair = (cid, bar)
            if pair in seen:
                raise ValueError("DUPLICATE_SECURITY_DATE")
            seen.add(pair)
            close = float(row["close"])
            if not math.isfinite(close) or close <= 0:
                raise ValueError("INVALID_CLOSE")
            data[cid].append((bar, close))
    eligible = []
    excluded = []
    for cid in sorted(universe):
        bars = sorted(data[cid])
        if len(bars) < 21:
            excluded.append({"canonical_security_id": cid, "reason": "INSUFFICIENT_21_BARS"})
            continue
        if bars[-1][0] != as_of:
            excluded.append({"canonical_security_id": cid, "reason": "NO_AS_OF_BAR"})
            continue
        factor = bars[-1][1] / bars[-21][1] - 1.0
        eligible.append({"canonical_security_id": cid, "signal_date": as_of.isoformat(),
                         "ret_20": factor})
    eligible.sort(key=lambda x: (-x["ret_20"], x["canonical_security_id"]))
    for i, row in enumerate(eligible, 1):
        row["descriptive_rank"] = i
    return {
        "schema": "AI_CORE_EVID_HISTORICAL_DESCRIPTIVE_RANK_V1",
        "as_of": as_of.isoformat(),
        "source_provenance": {
            "prices_sha256": sha256_file(prices_path),
            "universe_sha256": sha256_file(universe_path),
            "source_vintage_verified_point_in_time": False,
        },
        "active_universe_size": len(universe),
        "ranked_count": len(eligible),
        "excluded": excluded,
        "ranking": eligible,
        "factor": "ret_20",
        "historical_research_result": "V2.8.1: 0 OF 9 FACTORS PROMOTED",
        "decision_case_admission": "BLOCKED_UNVALIDATED_FACTOR",
        "live_buy_eligibility": "NOT_AUTHORIZED",
        "interpretation": "Descriptive cross section only; not PIT-certified, OOS-validated or a BUY recommendation.",
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--prices", type=Path, required=True)
    p.add_argument("--universe", type=Path, required=True)
    p.add_argument("--as-of", type=date.fromisoformat, required=True)
    args = p.parse_args()
    print(json.dumps(rank_historical_closes(args.prices, args.universe, args.as_of), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
