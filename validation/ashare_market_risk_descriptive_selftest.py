"""Synthetic mechanics tests only: never evidence for market performance or a trading signal."""
from __future__ import annotations

import csv
import math
import sys
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.ashare_market_risk_descriptive import evaluate


def write(path, rows):
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["index_id","date","close","source_id","retrieved_at_utc"])
        writer.writeheader()
        writer.writerows(rows)


def generate(n=300, shift=0):
    base = date(2024, 1, 1)
    stamp = datetime(2026, 10, 10, tzinfo=timezone.utc).isoformat()
    return [
        {"index_id": idx, "date": (base + timedelta(days=i)).isoformat(),
         "close": f"{1000.0 * math.exp(i*0.001 + 0.02*math.sin(i/7 + offset + shift)):.8f}",
         "source_id": "SYNTHETIC_TEST_ONLY", "retrieved_at_utc": stamp}
        for idx, offset in (("000300.SH", 0.0), ("000688.SH", 1.0))
        for i in range(n)
    ]


def main():
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "prices.csv"
        rows = generate()
        write(path, rows)
        cutoff = date(2024, 10, 26)
        r = evaluate(path, cutoff)
        assert r["signal_strength"] == "UNSCORED"
        assert r["action_eligibility"] == "NOT_EVALUATED"
        for item in r["indices"].values():
            assert item["status"] == "DESCRIPTIVE_ONLY"
            assert item["sessions"] == 300
            assert item["rv20_annualized"] > 0
            assert item["rv60_annualized"] > 0
            assert item["rv20_history_count"] == 280
            assert 0 < item["rv20_percentile_252"] <= 1
            assert item["historical_point_in_time_provenance_verified"] is False
        # An as-of cutoff excludes later data before any metric calculation.
        early = evaluate(path, date(2024, 4, 10))
        for item in early["indices"].values():
            assert item["sessions"] == 101
            assert item["excluded_future_rows"] == 199
            assert item["rv20_percentile_252"] is None
        # As-of matches a directly truncated snapshot's values.
        limited = [x for x in rows if x["date"] <= "2024-04-10"]
        write(path, limited)
        check = evaluate(path, date(2024, 4, 10))
        for idx in ("000300.SH", "000688.SH"):
            assert check["indices"][idx]["rv20_annualized"] == early["indices"][idx]["rv20_annualized"]
            assert check["indices"][idx]["rv60_annualized"] == early["indices"][idx]["rv60_annualized"]
        # Identity duplicates cannot silently alter denominators.
        write(path, rows + [rows[0]])
        try:
            evaluate(path, cutoff)
            raise AssertionError("duplicate must fail")
        except ValueError as ex:
            assert "DUPLICATE_INDEX_DATE" in str(ex)
        # Mixed provider/vintage lineage cannot silently feed the risk output.
        mixed = generate()
        mixed[1]["source_id"] = "OTHER_SOURCE"
        write(path, mixed)
        try:
            evaluate(path, cutoff)
            raise AssertionError("mixed provider must fail")
        except ValueError as ex:
            assert "MIXED_SOURCE_SNAPSHOT_BLOCK" in str(ex)
        # Missing one index is explicit, never silently substituted.
        write(path, [x for x in generate() if x["index_id"] == "000300.SH"])
        one = evaluate(path, cutoff)
        assert one["indices"]["000688.SH"]["status"] == "MISSING_INDEX_INPUT"
        # A genuinely constant series has zero realized volatility, not NaN.
        constant = generate()
        for row in constant:
            row["close"] = "1000"
        write(path, constant)
        flat = evaluate(path, cutoff)
        assert all(v["rv20_annualized"] == 0 for v in flat["indices"].values())
        assert all(v["rv20_percentile_252"] == 1.0 for v in flat["indices"].values())
        # The timestamp contract must reject local time masquerading as UTC.
        bad_timestamp = generate()
        bad_timestamp[0]["retrieved_at_utc"] = "2026-10-10T08:00:00+08:00"
        write(path, bad_timestamp)
        try:
            evaluate(path, cutoff)
            raise AssertionError("non-UTC provenance must fail")
        except ValueError as ex:
            assert "retrieved_at_utc must have UTC offset" in str(ex)
    print("ASHARE_MARKET_RISK_SYNTHETIC_MECHANICS: PASS")


if __name__ == "__main__":
    main()
