"""All test inputs are frozen pre-outcome research fields, never a trade."""
from __future__ import annotations
import copy
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from v29_original_24_source_frame import ORIGINAL, PRECISION, reconstruct


class SourceOnly24FrameTests(unittest.TestCase):
    def setUp(self):
        self.raw = ORIGINAL.read_bytes()
        self.precision = PRECISION.read_bytes()

    def build(self):
        return reconstruct(self.raw, self.precision)

    def test_real_source_only_24_preserved_and_true_gaps_counted(self):
        r = self.build()
        self.assertEqual(len(r["rows"]), 24)
        self.assertEqual(r["complete_four_field_count"], 15)
        self.assertEqual(r["incomplete_four_field_count"], 9)
        self.assertEqual(r["source_vs_later_vendor_material_difference_field_count"], 3)
        self.assertEqual(r["all_four_positive_descriptive_count"], 3)
        self.assertEqual(set(r["all_four_positive_security_ids_not_alpha"]),
                         {"SSE:603233", "SZSE:000501", "SSE:603333"})
        self.assertEqual(r["live_buy_eligibility"], "NOT_AUTHORIZED")
        self.assertFalse(r["historical_pit_reconstruction_complete"])
        self.assertFalse(r["vendor_2026_numeric_values_used_as_features"])
        self.assertFalse(r["independent_oos_or_future_outcomes_used"])
        self.assertTrue(all(not x["strict_historical_pit_certified"]
                            and x["buy_add_eligibility"] == "NOT_AUTHORIZED"
                            for x in r["rows"]))

    def test_original_values_used_not_retrospective_restated_vendor(self):
        rows = {r["security_id"]: r for r in self.build()["rows"]}
        orig = rows["SSE:600088"]
        self.assertEqual(orig["original_published_table_values"]["parent_net_profit_yuan"], "-65289963.12")
        self.assertEqual(orig["original_published_table_values"]["weighted_roe_pct"], "-6.32")
        self.assertEqual(orig["original_vs_2026_vendor_material_difference_fields"],
                         ["parent_net_profit_yuan", "weighted_roe_pct"])
        self.assertEqual(rows["SZSE:001896"]["original_published_table_values"]["parent_net_profit_yuan"],
                         "-2140481533.99")
        self.assertEqual(rows["SZSE:001896"]["original_vs_2026_vendor_material_difference_fields"],
                         ["parent_net_profit_yuan"])

    def test_missing_source_never_filled_from_vendor(self):
        rows = {r["security_id"]: r for r in self.build()["rows"]}
        missing = rows["SSE:603717"]
        self.assertFalse(missing["four_original_fields_complete"])
        self.assertEqual(len(missing["missing_fields"]), 4)
        self.assertEqual(missing["original_published_table_values"], {})
        partial = rows["SSE:601878"]
        self.assertEqual(partial["missing_fields"], ["parent_net_profit_yuan"])
        self.assertIsNone(partial["all_four_values_positive_descriptive_only"])

    def test_conflicting_or_altered_source_fails_instead_of_backfilling(self):
        changed = copy.deepcopy(json.loads(self.raw))
        changed["rows"][1]["field_sources"]["parent_net_profit_yuan"]["vendor_2026_source_value"] = "999999"
        with self.assertRaisesRegex(ValueError, "FROZEN_ORIGINAL_SOURCE"):
            reconstruct(json.dumps(changed).encode(), self.precision)
        changed_precision = copy.deepcopy(json.loads(self.precision))
        changed_precision["confirmed_after_source_unit_rounding_review"] = 0
        with self.assertRaisesRegex(ValueError, "FROZEN_ORIGINAL_SOURCE"):
            reconstruct(self.raw, json.dumps(changed_precision).encode())
        self.assertEqual(self.build(), self.build())


if __name__ == "__main__":
    unittest.main()
