#!/usr/bin/env python3
"""Source-only preflight for preregistered Q3 quality-growth study.

Uses historical financial PIT data only. No price, return, benchmark, future outcome.
Outputs *provisional* candidate ranking; historical independent roster/ST still unverified.
"""
import argparse
import hashlib
import json
import math
import zipfile
from collections import Counter
from datetime import date
from pathlib import Path
from v31_qlib_pit_archive_probe import ARCHIVE_SHA256, DATA, HEADER, _find_member
from v31_qlib_listed_coverage import parse_roster

SPEC = "research/V3.1_Q3_QUALITY_GROWTH_PREOUTCOME_SPEC_20261117.json"
FIELDS = ("or_yoy", "roe_waa", "profit_dedt")
YEARS = (2018, 2019, 2020, 2021, 2022)

def rank_percentile(rows, field):
    by_value = sorted(rows, key=lambda x: (-x["fields"][field], x["symbol"]))
    length = len(by_value)
    return {row["symbol"]: (length - index - 1) / max(length - 1, 1)
            for index, row in enumerate(by_value)}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    spec = json.loads(Path(SPEC).read_text(encoding="utf-8"))
    if spec["period"]["years"] != list(YEARS):
        raise ValueError("PREREGISTERED_YEARS_CHANGED")
    if spec["access_control"]["trade_authorized"] or spec["access_control"]["price_or_return_data_accessed_by_registration"]:
        raise ValueError("INVALID_PREREGISTRATION_STATE")
    digest = hashlib.sha256()
    with args.archive.open("rb") as stream:
        for part in iter(lambda: stream.read(1 << 20), b""):
            digest.update(part)
    if digest.hexdigest() != ARCHIVE_SHA256:
        raise ValueError("PINNED_ARCHIVE_MISMATCH")

    with zipfile.ZipFile(args.archive) as z:
        all_paths = z.namelist()
        roster = parse_roster(z.read(_find_member(all_paths, "/instruments/all.txt")))
        mapping = json.loads(z.read(_find_member(all_paths, "/financial/fields.json")))["fields"]
        ids = {int(k): info["name"] for k, info in mapping.items() if info.get("name") in FIELDS}
        if set(ids.values()) != set(FIELDS):
            raise ValueError("REQUIRED_FIELDS_MISSING")
        members = []
        for path in all_paths:
            if not path.endswith("/pit.data") or "/financial/" not in path:
                continue
            name = path.split("/")[-2]
            if len(name) != 9 or name[6] != "." or name[-2:] not in ("SH", "SZ"):
                continue
            symbol, exchange = name[:6], name[-2:]
            if (exchange == "SH" and symbol.startswith(("600", "601", "603", "605"))) or (
                    exchange == "SZ" and symbol.startswith(("000", "001", "002"))):
                members.append((name, path))
        members.sort()
        if not members:
            raise ValueError("NO_MAINBOARD_SOURCE_FILES")
        grouped = {year: [] for year in YEARS}
        excluded = {year: Counter() for year in YEARS}
        for symbol, member in members:
            windows = roster.get(symbol)
            raw = z.read(member)
            if len(raw) < HEADER.size:
                raise ValueError("BAD_PIT_HEADER:" + symbol)
            _, _, record_size, _, count, sha = HEADER.unpack_from(raw)
            if record_size != DATA.size or len(raw) != HEADER.size + record_size * count:
                raise ValueError("BAD_PIT_LENGTH:" + symbol)
            if hashlib.sha256(raw[HEADER.size:]).digest() != sha:
                raise ValueError("PIT_DIGEST_MISMATCH:" + symbol)
            by_year = {year: {} for year in YEARS}
            for off in range(HEADER.size, len(raw), record_size):
                fid, notice, period, value, _ = DATA.unpack_from(raw, off)
                year = period // 100
                if year not in by_year or period != year * 100 + 3 or fid not in ids:
                    continue
                if notice > year * 10000 + 1114 or not math.isfinite(value):
                    continue
                field = ids[fid]
                current = by_year[year].get(field)
                if current is None or notice < current[0]:
                    by_year[year][field] = (notice, value)

            for year in YEARS:
                asof = date(year, 11, 15)
                if not windows:
                    excluded[year]["unknown_roster"] += 1
                    continue
                starts = [start for start, end in windows if start <= asof <= end]
                if not starts:
                    excluded[year]["not_listed_on_asof"] += 1
                    continue
                if (asof - min(starts)).days < 365:
                    excluded[year]["less_than_365_days_since_roster_start"] += 1
                    continue
                record = by_year[year]
                if set(record) != set(FIELDS):
                    excluded[year]["missing_asof_financial"] += 1
                    continue
                metrics = {k: v[1] for k, v in record.items()}
                if min(metrics.values()) <= 0:
                    excluded[year]["nonpositive_financial_filter"] += 1
                    continue
                grouped[year].append({"symbol": symbol, "fields": metrics,
                                      "first_vendor_notice_days": {k: v[0] for k, v in record.items()}})
        results = {}
        for year, rows in grouped.items():
            if len(rows) < 30:
                results[str(year)] = {"provisional_eligible": len(rows),
                                      "status": "INSUFFICIENT_COUNT",
                                      "exclusions": dict(excluded[year]), "candidates": []}
                continue
            growth = rank_percentile(rows, "or_yoy")
            roe = rank_percentile(rows, "roe_waa")
            for row in rows:
                row["score"] = (growth[row["symbol"]] + roe[row["symbol"]]) / 2
            rows.sort(key=lambda r: (-r["score"], r["symbol"]))
            count = min(10, math.ceil(len(rows) * 0.05))
            results[str(year)] = {
                "provisional_eligible": len(rows),
                "provisional_selected_count": count,
                "status": "PROVISIONAL_PIT_ONLY_NOT_TRADEABLE",
                "exclusions": dict(excluded[year]),
                "candidates": rows[:count],
            }
    result = {
        "schema": "V31_Q3_GROWTH_SOURCE_ONLY_PREFLIGHT_V1",
        "preregistration": SPEC,
        "source_sha256": ARCHIVE_SHA256,
        "source_vendor_listing_only": True,
        "historical_st_liquidity_and_broker_fill_authenticated": False,
        "full_historical_financial_pit_certified": False,
        "prices_or_outcomes_read": False,
        "trade_authorized": False,
        "years": results,
    }
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": "SOURCE_ONLY_PROVISIONAL",
                      "year_counts": {y: {k: v[k] for k in ("provisional_eligible", "status")}
                                      for y, v in results.items()},
                      "prices_or_outcomes_read": False, "trade_authorized": False}, ensure_ascii=False))

if __name__ == "__main__":
    main()
