"""Offline deterministic coverage/identity tests for the actual frozen 2x128 cohort."""
import copy
import hashlib
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from v29_original_full256_source_frame import (
    PILOT, capture_shard, load_population, merge_shards, original_values,
)

def no_network_source(target, _fetch):
    chosen = target["original_metadata"].get("chosen")
    return {
        "security_id": target["security_id"],
        "fiscal_year": target["fiscal_year"],
        "official_announcement_day": chosen["notice_day"] if chosen else None,
        "official_original_pdf_url": chosen["original_pdf_url"] if chosen else None,
        "pdf_original_current_year_field_source": False,
        "status": "NO_OFFLINE_SOURCE_PDF",
        "live_buy_eligibility": "NOT_AUTHORIZED",
        "field_sources": {},
        "retrospective_vendor_numbers_forbidden": 999999,
    }


class HistoricalFull256SourceTests(unittest.TestCase):
    def setUp(self):
        self.targets, self.first24, self.remaining, self.hashes = load_population()

    def fake_shards(self):
        with patch("v29_original_full256_source_frame.one", side_effect=no_network_source):
            return [capture_shard(i, fetch=lambda _: b"NO_NETWORK") for i in range(4)]

    def test_frozen_256_coverage_and_first24_not_refetched(self):
        self.assertEqual(len(self.targets), 256)
        self.assertEqual(len(self.first24), 24)
        self.assertEqual(len(self.remaining), 232)
        self.assertEqual([x["fiscal_year"] for x in self.remaining[:116]], [2022]*116)
        self.assertEqual([x["fiscal_year"] for x in self.remaining[116:]], [2023]*116)
        self.assertEqual(self.targets[12]["security_id"], self.remaining[0]["security_id"])
        self.assertEqual(self.targets[128+12]["security_id"], self.remaining[116]["security_id"])

    def test_four_shards_merge_preserves_every_identity_and_original_vintage(self):
        shards = self.fake_shards()
        frame, receipt = merge_shards(shards)
        self.assertEqual(frame["frozen_issuer_year_count"], 256)
        self.assertEqual(len(frame["rows"]), 256)
        self.assertEqual(len(receipt["rows"]), 256)
        self.assertEqual(frame["complete_four_field_count"], 15)
        self.assertEqual(frame["incomplete_four_field_count"], 241)
        self.assertEqual(frame["source_manifest_hashes"], self.hashes)
        self.assertTrue(frame["later_2026_vendor_values_never_used_as_financial_features"])
        self.assertFalse(frame["independent_untouched_oos_or_price_outcomes_used"])
        self.assertFalse(frame["strict_historical_pit_certified"])
        self.assertEqual(frame["live_buy_eligibility"], "NOT_AUTHORIZED")
        self.assertEqual([r["security_id"] for r in frame["rows"]],
                         [t["security_id"] for t in self.targets])
        indexed = {(r["security_id"], r["fiscal_year"]): r for r in frame["rows"]}
        self.assertEqual(indexed["SSE:600088", 2022]["original_year_table_values"]["parent_net_profit_yuan"], "-65289963.12")
        self.assertEqual(indexed["SZSE:001896", 2022]["original_year_table_values"]["parent_net_profit_yuan"], "-2140481533.99")
        self.assertEqual(indexed[self.remaining[0]["security_id"], 2022]["original_year_table_values"], {})
        self.assertEqual(indexed[self.remaining[0]["security_id"], 2022]["missing_original_year_fields"],
                         ["revenue_yuan", "parent_net_profit_yuan",
                          "revenue_growth_yoy_pct", "weighted_roe_pct"])
        # The source receipts may mention later vendor data, but feature rows never do.
        self.assertNotIn("vendor_2026_source_value", json.dumps(frame, ensure_ascii=False))

    def test_wrong_shard_identity_is_rejected_even_if_number_of_rows_unchanged(self):
        shards = self.fake_shards()
        shards[0]["rows"][0]["security_id"] = "SSE:999999"
        with self.assertRaisesRegex(ValueError, "SHARD_ROW_MISMATCH"):
            merge_shards(shards)
        shards = self.fake_shards()
        shards[2]["source_manifest_hashes"]["first_24_original_source_sha256"] = "0"*64
        with self.assertRaisesRegex(ValueError, "INCOMPLETE_OR_CHANGED_SOURCE_SHARD"):
            merge_shards(shards)
        with self.assertRaisesRegex(ValueError, "REQUIRE_ALL_FOUR"):
            merge_shards(shards[:3])

    def test_original_year_and_unit_controls_reject_later_numeric_substitution(self):
        record = copy.deepcopy(self.first24[1])
        values, _, _, complete = original_values(record)
        self.assertTrue(complete)
        self.assertEqual(values["parent_net_profit_yuan"], "-65289963.12")
        record["field_sources"]["parent_net_profit_yuan"]["original_current_year_table_value"] = "-64909557.15"
        with self.assertRaisesRegex(ValueError, "ORIGINAL_PDF_FIELD_YEAR_UNIT_OR_VALUE_CONFLICT"):
            original_values(record)
        with self.assertRaisesRegex(ValueError, "INVALID_FIXED_SOURCE_SHARD"):
            capture_shard(4, fetch=lambda _: b"NO_NETWORK")

    def test_previous_pilot_sha_and_provenance_not_renamed(self):
        raw = PILOT.read_bytes()
        self.assertEqual(self.hashes["first_24_original_source_sha256"],
                         hashlib.sha256(raw).hexdigest())
        self.assertEqual(merge_shards(self.fake_shards()),
                         merge_shards(self.fake_shards()))


if __name__ == "__main__":
    unittest.main()
