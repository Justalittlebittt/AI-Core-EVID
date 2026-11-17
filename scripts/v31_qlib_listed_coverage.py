#!/usr/bin/env python3
"""Classify earlier bounded financial PIT coverage by archived all-market listing intervals.

Supplier-relative listing eligibility, NOT independent historical roster attestation.
Never reads prices, price outcomes, prospective cohorts or strategy labels.
"""
import argparse
import hashlib
import json
import zipfile
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

from v31_qlib_pit_archive_probe import ARCHIVE_SHA256, _find_member


def parse_roster(content):
    ranges = defaultdict(list)
    for number, line in enumerate(content.decode("utf-8-sig").splitlines(), 1):
        parts = line.strip().split()
        if not parts:
            continue
        if len(parts) != 3:
            raise ValueError(f"BAD_ROSTER_LINE:{number}")
        symbol, start, end = parts
        if symbol.startswith(("SH", "SZ")) and len(symbol) == 8:
            symbol = symbol[2:] + "." + symbol[:2]
        if len(symbol) != 9 or symbol[6] != "." or symbol[-2:] not in ("SH", "SZ"):
            raise ValueError(f"BAD_ROSTER_SYMBOL:{number}")
        start_day, end_day = date.fromisoformat(start), date.fromisoformat(end)
        if start_day > end_day:
            raise ValueError(f"INVERTED_ROSTER_INTERVAL:{number}")
        ranges[symbol].append((start_day, end_day))
    return ranges


def classify(period, symbol, ranges):
    boundary = date(period // 100, 9, 30)
    windows = ranges.get(symbol)
    if not windows:
        return "UNKNOWN_LISTING_STATUS"
    if any(start <= boundary <= end for start, end in windows):
        return "LISTED_AT_QUARTER_END"
    if all(boundary < start for start, _ in windows):
        return "PRE_LISTING"
    return "NOT_LISTED_AT_QUARTER_END"


def run(archive, coverage):
    raw = archive.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != ARCHIVE_SHA256:
        raise ValueError("ARCHIVE_DIGEST_MISMATCH")
    if coverage["archive_sha256"] != digest or coverage["schema"] != "V31_ARCHIVED_FINANCIAL_SOURCE_COVERAGE_ONLY_V1":
        raise ValueError("COVERAGE_NOT_FROM_PINNED_SOURCE")
    with zipfile.ZipFile(archive) as z:
        roster_member = _find_member(z.namelist(), "/instruments/all.txt")
        roster_bytes = z.read(roster_member)
    roster = parse_roster(roster_bytes)
    rows = []
    by_year = {}
    for p in coverage["periods"]:
        summary = Counter()
        for old in coverage["rows"]:
            if old["period"] != p:
                continue
            symbol = old["symbol"]
            listing = classify(p, symbol, roster)
            present = sum(1 for v in old["fields"].values() if v["present"])
            total = len(old["fields"])
            summary["sample_symbols"] += 1
            summary["all_slots"] += total
            summary["all_present"] += present
            if listing == "LISTED_AT_QUARTER_END":
                summary["listed_symbols"] += 1
                summary["listed_field_slots"] += total
                summary["listed_present"] += present
                summary["listed_missing"] += total - present
            else:
                summary[listing] += 1
            rows.append({"symbol": symbol, "period": p, "listing_status": listing,
                         "fields_present": present, "fields_possible": total})
        by_year[str(p)] = dict(summary)
        by_year[str(p)]["listed_coverage_pct"] = (
            round(100 * summary["listed_present"] / summary["listed_field_slots"], 2)
            if summary["listed_field_slots"] else None
        )
    return {
        "schema": "V31_SUPPLIER_LISTING_ADJUSTED_PIT_COVERAGE_V1",
        "archive_sha256": digest,
        "roster_member": roster_member,
        "roster_sha256": hashlib.sha256(roster_bytes).hexdigest(),
        "roster_symbols": len(roster),
        "basis": "provider all.txt membership on Q3 report quarter-end, not independently authenticated",
        "selection_is_representative": False,
        "by_period": by_year,
        "rows": rows,
        "has_independent_listing_verification": False,
        "has_original_issuer_financial_crosscheck_for_these_periods": False,
        "outcome_or_price_data_read": False,
        "trade_authorized": False,
        "status": "SUPPLIER_LISTING_ADJUSTED_SOURCE_ONLY",
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--archive", type=Path, required=True)
    p.add_argument("--coverage", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    data = run(args.archive, json.loads(args.coverage.read_text(encoding="utf-8")))
    args.output.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": data["status"], "by_period": data["by_period"],
                      "roster_symbols": data["roster_symbols"],
                      "outcome_or_price_data_read": False, "trade_authorized": False}, ensure_ascii=False))


if __name__ == "__main__":
    main()
