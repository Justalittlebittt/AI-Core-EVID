#!/usr/bin/env python3
"""Bounded, read-only REAL historical input for the existing descriptive as-of rank.

Uses the exact stock dataset revision/hash and official PIT ledger already frozen for
V2.8.1. Extracts only requested securities through a historical cutoff. No outcomes,
Fold3/4, prospective V2.8.12 input, threshold tuning or research promotion.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import tempfile
from datetime import date
from pathlib import Path

import duckdb
import pandas as pd
from huggingface_hub import hf_hub_download

from v29_historical_asof_rank import rank_historical_closes

ROOT = Path(__file__).resolve().parents[1]
PIT = ROOT / "evidence/V2.8.1_PIT_MEMBERSHIP_INTERVALS.csv"
PIT_SHA = "52087fa1e68577fae214f8fa18f1b20a0b30f41b6b6bf5592327c25c2800cfc1"
DATASET = "AlphaDojo/dojo_stock_kline"
REVISION = "c009ad58278161e7b6eb347b68f34f51166114f3"
PARQUET_SHA = "acb8ae5e31f58fe3972455b86614d668837f18afd59126c505faaae06920954b"


def file_sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def membership(selected, as_of):
    if file_sha(PIT) != PIT_SHA:
        raise ValueError("PIT_LEDGER_HASH_MISMATCH")
    source = pd.read_csv(PIT, dtype=str, keep_default_na=False)
    required = {"canonical_security_id", "exchange", "security_code", "official_list_date", "official_delist_date"}
    if not required.issubset(source.columns):
        raise ValueError("PIT_LEDGER_SCHEMA_INVALID")
    result = []
    for cid in selected:
        rows = source[source["canonical_security_id"] == cid]
        if len(rows) != 1:
            raise ValueError("SECURITY_PIT_IDENTITY_NOT_UNIQUE:" + cid)
        row = rows.iloc[0]
        since = date.fromisoformat(row["official_list_date"])
        until = date.fromisoformat(row["official_delist_date"]) if row["official_delist_date"] else None
        if as_of < since or (until and as_of > until):
            raise ValueError("SECURITY_NOT_IN_PIT_UNIVERSE:" + cid)
        suffix = {"SSE": "SS", "SZSE": "SZ"}.get(row["exchange"])
        if suffix is None:
            raise ValueError("UNSUPPORTED_EXCHANGE:" + cid)
        result.append((cid, row["security_code"] + "." + suffix, since, until))
    return result


def build(as_of, securities):
    if len(securities) != len(set(securities)) or not 1 <= len(securities) <= 10:
        raise ValueError("REQUIRE_1_TO_10_UNIQUE_SECURITIES")
    if as_of > date(2026, 9, 9):
        raise ValueError("AS_OF_EXCEEDS_FROZEN_HISTORICAL_RESEARCH_WINDOW")
    members = membership(securities, as_of)
    source = Path(hf_hub_download(repo_id=DATASET, repo_type="dataset", filename="data.parquet", revision=REVISION))
    if file_sha(source) != PARQUET_SHA:
        raise ValueError("FROZEN_STOCK_PARQUET_HASH_MISMATCH")
    con = duckdb.connect(database=":memory:")
    try:
        # Parameterized symbol/date filters prevent SQL injection and future bars.
        rows = []
        for cid, symbol, _, _ in members:
            df = con.execute("""
                SELECT CAST(bar_time AS DATE) AS bar_date, CAST(close AS DOUBLE) AS close
                FROM read_parquet(?) WHERE CAST(symbol AS VARCHAR) = ?
                  AND CAST(kline_t AS VARCHAR) = '1D'
                  AND CAST(bar_time AS DATE) <= ?
                ORDER BY bar_date DESC LIMIT 21
            """, [str(source), symbol, as_of]).fetchall()
            rows.extend((cid, d.isoformat(), value) for d, value in df)
    finally:
        con.close()
    with tempfile.TemporaryDirectory() as tmp:
        prices = Path(tmp) / "prices.csv"
        universe = Path(tmp) / "universe.csv"
        with prices.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(["canonical_security_id", "bar_date", "close"])
            writer.writerows(rows)
        with universe.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(["canonical_security_id", "valid_from", "valid_until"])
            for cid, _, since, until in members:
                writer.writerow([cid, since.isoformat(), until.isoformat() if until else ""])
        result = rank_historical_closes(prices, universe, as_of)
    result["real_historical_source"] = {
        "dataset": DATASET, "revision": REVISION,
        "parquet_sha256": PARQUET_SHA, "pit_sha256": PIT_SHA,
        "historical_window_max_date": "2026-09-09",
        "sampled_security_ids": list(securities),
        "frozen_research_asof_eligibility_verified": True,
        "candidate_strategy_validated": False,
        "data_adjustment_semantics_independently_certified": False,
    }
    return result


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--as-of", type=date.fromisoformat, required=True)
    p.add_argument("--security", action="append", required=True)
    p.add_argument("--output", type=Path, help="Optional JSON output destination")
    a = p.parse_args()
    result = build(a.as_of, a.security)
    output = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if a.output:
        a.output.parent.mkdir(parents=True, exist_ok=True)
        a.output.write_text(output, encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
