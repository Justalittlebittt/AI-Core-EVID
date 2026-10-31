"""Tests for historical population sampling, not trading strategy validity."""
import copy
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from v29_historical_universe_sampling import (
    FRAME_DATE, EXPECTED_FRAME_SIZE, build_frame, select_membership_frame
)


def row(sid, listed="2024-01-01", delisted=""):
    return {"canonical_security_id": sid, "official_list_date": listed,
            "official_delist_date": delisted}


class HistoricalSourceFrameTests(unittest.TestCase):
    def test_frozen_real_source_has_reconstructed_2025_population(self):
        manifest = build_frame()
        self.assertEqual(manifest["population_count"], EXPECTED_FRAME_SIZE)
        self.assertEqual(manifest["frame_date"], FRAME_DATE.isoformat())
        self.assertEqual(len(manifest["selected_ids"]), 128)
        self.assertEqual(len(set(manifest["selected_ids"])), 128)
        self.assertFalse(manifest["independent_oos_validated"])
        self.assertEqual(manifest["live_buy_eligibility"], "NOT_AUTHORIZED")

    def test_future_delisting_and_financial_outcomes_do_not_change_selection(self):
        items = [row("SSE:600001"), row("SZSE:000001"),
                 row("SSE:600002"), row("SSE:600003")]
        a = select_membership_frame(items, sample_size=3)
        changed = copy.deepcopy(items)
        changed[0]["official_delist_date"] = "2025-10-20"
        changed[1]["future_return"] = -0.99
        changed[2]["future_accounting_growth"] = 999
        b = select_membership_frame(changed, sample_size=3)
        self.assertEqual(a, b)
        self.assertEqual(a["population_count"], 4)

    def test_sorted_input_and_shuffled_input_identical(self):
        rows = [row("SSE:600001"), row("SZSE:000001"), row("SSE:600002")]
        self.assertEqual(select_membership_frame(rows, sample_size=2),
                         select_membership_frame(list(reversed(rows)), sample_size=2))

    def test_delisted_before_frame_excluded_new_listings_not_backfilled(self):
        rows = [row("SSE:600001", delisted="2025-01-02"),
                row("SSE:600002", delisted="2025-02-01"),
                row("SZSE:300001", listed="2025-02-01")]
        v = select_membership_frame(rows, sample_size=1)
        self.assertEqual(v["population_count"], 1)
        self.assertEqual(v["selected_ids"], ["SSE:600002"])

    def test_duplicate_and_invalid_interval_rejected(self):
        with self.assertRaisesRegex(ValueError, "DUPLICATE_MEMBERSHIP_ID"):
            select_membership_frame([row("SSE:600001"), row("SSE:600001")], sample_size=1)
        with self.assertRaisesRegex(ValueError, "INVALID_LISTING_INTERVAL"):
            select_membership_frame([row("SSE:600001", delisted="2023-01-01")], sample_size=1)

    def test_frozen_source_identity_not_silently_changed(self):
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder) / "membership.csv"
            p.write_text("canonical_security_id,official_list_date,official_delist_date\n"
                         "SSE:600001,2024-01-01,\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "FROZEN_MEMBERSHIP_SOURCE_HASH_CHANGED"):
                build_frame(p)


if __name__ == "__main__":
    unittest.main()
