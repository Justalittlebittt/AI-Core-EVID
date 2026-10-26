"""Offline regression tests for as-of descriptive historical ranking."""
import csv
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from v29_historical_asof_rank import rank_historical_closes


class AsOfRankTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.prices = Path(self.tmp.name) / "prices.csv"
        self.universe = Path(self.tmp.name) / "universe.csv"
        self.asof = date(2020, 2, 3)
        with self.universe.open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["canonical_security_id", "valid_from", "valid_until"])
            w.writerows([["SZSE:000001", "2019-01-01", ""], ["SSE:600000", "2019-01-01", ""]])
        self.write_prices()

    def write_prices(self, future=False, missing=False, duplicate=False):
        with self.prices.open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["canonical_security_id", "bar_date", "close"])
            from datetime import timedelta
            for i in range(21):
                d = self.asof - timedelta(days=20-i)
                if missing and i == 20:
                    continue
                w.writerow(["SZSE:000001", d.isoformat(), 100 + i])
                w.writerow(["SSE:600000", d.isoformat(), 100 + i/2])
            if future:
                w.writerow(["SZSE:000001", "2020-02-04", "150"])
            if duplicate:
                w.writerow(["SZSE:000001", self.asof.isoformat(), "120"])

    def test_rank_and_research_block(self):
        x = rank_historical_closes(self.prices, self.universe, self.asof)
        self.assertEqual(x["ranked_count"], 2)
        self.assertEqual(x["ranking"][0]["canonical_security_id"], "SZSE:000001")
        self.assertEqual(x["decision_case_admission"], "BLOCKED_UNVALIDATED_FACTOR")
        self.assertEqual(x["live_buy_eligibility"], "NOT_AUTHORIZED")
        self.assertFalse(x["source_provenance"]["source_vintage_verified_point_in_time"])

    def test_future_bar_rejected(self):
        self.write_prices(future=True)
        with self.assertRaisesRegex(ValueError, "FUTURE_BAR"):
            rank_historical_closes(self.prices, self.universe, self.asof)

    def test_missing_d_bar_excluded(self):
        self.write_prices(missing=True)
        x = rank_historical_closes(self.prices, self.universe, self.asof)
        self.assertEqual(x["ranked_count"], 1)
        self.assertEqual(x["excluded"][0]["reason"], "NO_AS_OF_BAR")

    def test_duplicate_bar_rejected(self):
        self.write_prices(duplicate=True)
        with self.assertRaisesRegex(ValueError, "DUPLICATE_SECURITY_DATE"):
            rank_historical_closes(self.prices, self.universe, self.asof)

    def test_empty_asof_universe_rejected(self):
        with self.assertRaisesRegex(ValueError, "EMPTY_ACTIVE_UNIVERSE"):
            rank_historical_closes(self.prices, self.universe, "2018-01-01")

    def test_idempotent_and_hash_bound(self):
        a = rank_historical_closes(self.prices, self.universe, self.asof)
        b = rank_historical_closes(self.prices, self.universe, self.asof)
        self.assertEqual(a, b)
        self.assertEqual(len(a["source_provenance"]["prices_sha256"]), 64)


if __name__ == "__main__":
    unittest.main()
