"""Offline tests of the recorded research verdict, not strategy validation."""
import copy
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parent))
from v29_growth_quality_nonpromotion import SOURCE,FEATURES,SPEC,audit,markdown,PRIMARY

DATA=json.loads(SOURCE.read_text(encoding="utf-8"))
FEATURE=json.loads(FEATURES.read_text(encoding="utf-8"))
SPEC_DATA=json.loads(SPEC.read_text(encoding="utf-8"))

class FrozenNonpromotionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result=audit(DATA,FEATURE,SPEC_DATA)

    def test_existing_128_universe_and_8_untradeable_retained(self):
        self.assertEqual(self.result["entire_frozen_sample_count"],128)
        self.assertEqual(self.result["market_comparison_eligible"],120)
        self.assertEqual(self.result["excluded_ST_or_untradeable"],8)
        self.assertEqual(self.result["primary_rule_admission"],"DO_NOT_PROMOTE")
        self.assertEqual(self.result["evidence_strength"],"INSUFFICIENT")
        self.assertFalse(self.result["independent_untouched_oos_validated"])
        self.assertEqual(self.result["live_buy_eligibility"],"NOT_AUTHORIZED")

    def test_mean_positive_but_median_and_leave_max_negative(self):
        p=self.result["screen_results"][PRIMARY]
        self.assertEqual(p["selected_count"],29)
        self.assertEqual(p["positive_excess_count"],14)
        self.assertEqual(p["same_entry_session_group_count"],7)
        self.assertEqual(p["negative_mean_excess_group_count"],5)
        self.assertGreater(p["mean_excess"],0)
        self.assertLess(p["median_excess"],0)
        self.assertLess(p["mean_excess_excluding_largest_issuer"],0)
        self.assertLess(p["selection_minus_same_day_random_mean_net_stock_return"],0)
        self.assertEqual(p["largest_excess_issuer"],"SSE:688313")

    def test_revenue_diagnostic_does_not_become_posthoc_trading_rule(self):
        d=self.result["screen_results"]["revenue_growth_yoy_pct_only"]
        self.assertGreater(d["mean_excess"],0)
        self.assertGreater(d["selection_minus_same_day_random_mean_net_stock_return"],0)
        self.assertEqual(self.result["revenue_only_diagnostic_admission"],
                         "NOT_PROMOTED_AFTER_OBSERVING_2025_OUTCOMES")
        self.assertIn("2025_OUTCOMES_ALREADY_OBSERVED_NO_UNTOUCHED_OOS",
                      self.result["reasons"])

    def test_evidence_hash_or_stored_return_tampering_rejected(self):
        fake=copy.deepcopy(DATA)
        fake["screens"][PRIMARY]["selected_count"]+=1
        with self.assertRaisesRegex(ValueError,"STORED_STOCK_SELECTION_MISMATCH"):
            audit(fake,FEATURE,SPEC_DATA)
        fake=copy.deepcopy(DATA)
        fake["rows"][0]["net_excess_price_return_vs_csi300"]+=0.05
        with self.assertRaisesRegex(ValueError,"STORED_EXCESS_MATH_MISMATCH"):
            audit(fake,FEATURE,SPEC_DATA)

    def test_missing_historical_feature_vintage_cannot_be_hidden(self):
        fake=copy.deepcopy(FEATURE)
        fake["original_2025_asof_feature_vintage_certified"]=True
        with self.assertRaisesRegex(ValueError,"FROZEN_128_INTEGRITY_OR_ADMISSION_BOUNDARY"):
            audit(DATA,fake,SPEC_DATA)
        fake=copy.deepcopy(DATA)
        fake["independent_untouched_oos_validated"]=True
        with self.assertRaisesRegex(ValueError,"FROZEN_128_INTEGRITY_OR_ADMISSION_BOUNDARY"):
            audit(fake,FEATURE,SPEC_DATA)

    def test_frozen_screen_hash_mismatch_blocks_future_report_rewrites(self):
        fake=copy.deepcopy(DATA)
        fake["fixed_exploratory_spec_sha256"]="0"*64
        with self.assertRaisesRegex(ValueError,"FROZEN_SELECTION_SPEC_HASH_CHANGED"):
            audit(fake,FEATURE,SPEC_DATA)

    def test_generated_report_is_readable_and_contains_no_buy_promotion(self):
        report=markdown(self.result)
        self.assertIn("DO NOT PROMOTE",report)
        self.assertIn("NOT AUTHORIZED",report)
        self.assertIn("SSE:688313",report)
        self.assertIn("Random tail percentages",report)

if __name__=="__main__":
    unittest.main()
