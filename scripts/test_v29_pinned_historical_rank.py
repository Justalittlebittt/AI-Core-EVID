"""Offline checks for full-PIT descriptive ranking, with synthetic local parquet.

The tests never reach a provider or inspect any prospective/OOS outcomes.
"""
import csv
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parent))
import v29_pinned_historical_rank as pinned


class FullPitTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.pit = Path(self.tmp.name) / "pit.csv"
        self.parquet = Path(self.tmp.name) / "price.parquet"
        self.as_of = date(2026, 9, 9)
        self.make_pit()
        self.make_prices()

    def make_pit(self, duplicate=False):
        rows = [
            ["SSE:600000", "SSE", "600000", "2020-01-01", ""],
            ["SZSE:000001", "SZSE", "000001", "2020-01-01", ""],
            ["SSE:600002", "SSE", "600002", "2020-01-01", ""],  # No bars
            ["SSE:600001", "SSE", "600001", "2026-09-10", ""],  # Future listing
        ]
        if duplicate:
            rows.append(rows[0])
        with self.pit.open("w", newline="", encoding="utf-8") as stream:
            w = csv.writer(stream)
            w.writerow(["canonical_security_id", "exchange", "security_code",
                        "official_list_date", "official_delist_date"])
            w.writerows(rows)

    def make_prices(self):
        con = duckdb.connect()
        try:
            con.execute("CREATE TABLE bars(symbol VARCHAR, kline_t VARCHAR, bar_time DATE, close DOUBLE)")
            rows = []
            for symbol, daily_step in [("600000.SS", 1.0), ("000001.SZ", 0.5)]:
                for i in range(21):
                    rows.append((symbol, "1D", self.as_of - timedelta(days=20-i),
                                 100.0 + i * daily_step))
                # Future information may be present in the file but cannot enter
                # the query result or influence the ranking.
                rows.append((symbol, "1D", self.as_of + timedelta(days=1), 10000.0))
            con.executemany("INSERT INTO bars VALUES (?, ?, ?, ?)", rows)
            con.execute("COPY bars TO ? (FORMAT PARQUET)", [str(self.parquet)])
        finally:
            con.close()

    def sources(self):
        return (
            patch.object(pinned, "PIT", self.pit),
            patch.object(pinned, "PIT_SHA", pinned.file_sha(self.pit)),
            patch.object(pinned, "PARQUET_SHA", pinned.file_sha(self.parquet)),
            patch.object(pinned, "hf_hub_download", return_value=str(self.parquet)),
        )

    def test_full_pit_universe_ranks_all_active_without_future_data(self):
        a, b, c, d = self.sources()
        with a, b, c, d:
            report = pinned.build(self.as_of)
        self.assertEqual(report["active_universe_size"], 3)
        self.assertEqual(report["ranked_count"], 2)
        self.assertEqual(report["ranking"][0]["canonical_security_id"], "SSE:600000")
        self.assertAlmostEqual(report["ranking"][0]["ret_20"], 0.2)
        self.assertEqual(report["excluded"], [
            {"canonical_security_id": "SSE:600002", "reason": "NO_AS_OF_BAR"},
        ])
        self.assertEqual(report["real_historical_source"]["selection_mode"], "FULL_PIT_ASOF")
        self.assertEqual(report["live_buy_eligibility"], "NOT_AUTHORIZED")
        self.assertEqual(report["decision_case_admission"], "BLOCKED_UNVALIDATED_FACTOR")

    def test_original_bounded_mode_preserved(self):
        a, b, c, d = self.sources()
        with a, b, c, d:
            report = pinned.build(self.as_of, ["SZSE:000001"])
        self.assertEqual(report["active_universe_size"], 1)
        self.assertEqual(report["ranked_count"], 1)
        self.assertEqual(report["real_historical_source"]["selection_mode"],
                         "BOUNDED_EXPLICIT_SECURITIES")

    def test_duplicate_pit_identity_fails_closed(self):
        self.make_pit(duplicate=True)
        with patch.object(pinned, "PIT", self.pit), patch.object(
            pinned, "PIT_SHA", pinned.file_sha(self.pit)
        ):
            with self.assertRaisesRegex(ValueError, "SECURITY_PIT_IDENTITY_NOT_UNIQUE"):
                pinned.membership(None, self.as_of)

    def test_explicit_future_listing_fails(self):
        with patch.object(pinned, "PIT", self.pit), patch.object(
            pinned, "PIT_SHA", pinned.file_sha(self.pit)
        ):
            with self.assertRaisesRegex(ValueError, "SECURITY_NOT_IN_PIT_UNIVERSE"):
                pinned.membership(["SSE:600001"], self.as_of)

    def test_cutoff_enforced_before_download(self):
        with self.assertRaisesRegex(ValueError, "AS_OF_EXCEEDS_FROZEN_HISTORICAL_RESEARCH_WINDOW"):
            pinned.build(date(2026, 9, 10))


if __name__ == "__main__":
    unittest.main()
