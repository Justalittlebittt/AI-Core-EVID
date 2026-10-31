#!/usr/bin/env python3
"""Outcome-blind historical universe sampling for SOURCE COVERAGE, not alpha.

Freeze an issuer sample before looking up its 2025 filings/returns, using the
already reconstructed V2.8.1 listing intervals (including delisted companies).
The intervals were reconstructed later; this is not a pristine PIT/OOS dataset.
Sampling cannot condition on future delisting, 2025 results, earnings or prices.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INTERVALS = ROOT / "evidence/V2.8.1_PIT_MEMBERSHIP_INTERVALS.csv"
INTERVALS_SHA256 = "52087fa1e68577fae214f8fa18f1b20a0b30f41b6b6bf5592327c25c2800cfc1"
FRAME_DATE = date(2025, 1, 2)
SEED = "V29_HISTORICAL_SOURCE_COVERAGE_SAMPLE_20261031_V1"
SAMPLE_SIZE = 128
EXPECTED_FRAME_SIZE = 5121


def select_membership_frame(rows, frame_date=FRAME_DATE, sample_size=SAMPLE_SIZE, seed=SEED):
    """Only identity and membership AT the frame date can affect sampling."""
    members = set()
    seen = set()
    for row in rows:
        sid = row["canonical_security_id"]
        if sid in seen:
            raise ValueError("DUPLICATE_MEMBERSHIP_ID")
        seen.add(sid)
        if not (sid.startswith("SSE:") or sid.startswith("SZSE:")):
            raise ValueError("INVALID_EXCHANGE_ID")
        listed = date.fromisoformat(row["official_list_date"])
        delisted = (date.fromisoformat(row["official_delist_date"])
                    if row["official_delist_date"] else None)
        if delisted is not None and delisted <= listed:
            raise ValueError("INVALID_LISTING_INTERVAL")
        if listed <= frame_date and (delisted is None or frame_date < delisted):
            members.add(sid)
    if len(members) < sample_size or sample_size < 1:
        raise ValueError("INSUFFICIENT_FRAME_MEMBERS")
    # The sorting uses NO future delist information and NO financial/return values.
    ordered = sorted(members, key=lambda sid: (
        hashlib.sha256((seed + "|" + sid).encode()).hexdigest(), sid
    ))
    selected = ordered[:sample_size]
    return {
        "frame_date": frame_date.isoformat(),
        "population_count": len(members),
        "population_ids_sha256": hashlib.sha256(
            ("\n".join(sorted(members)) + "\n").encode()).hexdigest(),
        "selected_ids": selected,
        "selected_ids_sha256": hashlib.sha256(
            ("\n".join(selected) + "\n").encode()).hexdigest(),
        "sample_count": len(selected),
    }


def build_frame(path=INTERVALS):
    raw = Path(path).read_bytes()
    source_hash = hashlib.sha256(raw).hexdigest()
    if source_hash != INTERVALS_SHA256:
        raise ValueError("FROZEN_MEMBERSHIP_SOURCE_HASH_CHANGED")
    rows = list(csv.DictReader(raw.decode("utf-8-sig").splitlines()))
    frame = select_membership_frame(rows)
    if frame["population_count"] != EXPECTED_FRAME_SIZE:
        raise ValueError("FROZEN_2025_MEMBERSHIP_FRAME_COUNT_CHANGED")
    return {
        "schema": "V29_2025_HISTORICAL_SOURCE_COVERAGE_SAMPLE_V1",
        "purpose": "BOUNDED_2025_SOURCE_ACQUISITION_FEASIBILITY_NOT_STRATEGY_BACKTEST",
        "source_interval_sha256": source_hash,
        "source_interval_authority": "V2.8.1_RECONSTRUCTED_AFTER_2025_NOT_ORIGINAL_2025_VINTAGE",
        "selection_seed": SEED,
        "selection_rule": "SHA256(seed|canonical_security_id), first 128 of entire asof population",
        **frame,
        "historical_sample_selected_after_2025_outcomes_exist": True,
        "future_delisting_or_outcome_used_for_selection": False,
        "source_coverage_confirmed": False,
        "financial_as_disclosed_pit_certified": False,
        "outcomes_accessed_by_generator": False,
        "independent_oos_validated": False,
        "trade_authorized": False,
        "live_buy_eligibility": "NOT_AUTHORIZED",
        "research_limitations": [
            "Later reconstructed membership intervals are not a contemporaneously archived 2025 universe",
            "Fixed 2025-01-02 frame omits stocks listed subsequently; separate vintage frames required",
            "Small random feasibility sample must not substitute for full-universe effectiveness analysis",
            "Source/filing absence, suspension, later delisting and failed returns must remain observable, never silently dropped",
            "The already inspected 2025 history cannot be relabeled pristine unseen OOS",
        ],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = build_frame()
    if args.out.exists():
        raise ValueError("NO_OVERWRITE_OF_SAMPLE_FRAME")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    # Console records count/hash, not thousands of source rows or outcome prices.
    print(json.dumps({
        "frame_date": result["frame_date"],
        "population_count": result["population_count"],
        "sample_count": result["sample_count"],
        "selected_ids_sha256": result["selected_ids_sha256"],
        "source_interval_sha256": result["source_interval_sha256"],
        "trade_authorized": False,
        "outcomes_accessed": False,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
