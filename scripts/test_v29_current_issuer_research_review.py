"""Tests real preserved issuer identities without inventing trade plans."""
import copy
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from v29_current_issuer_research_review import SOURCE, build_reviews


class CurrentIssuerResearchReviewTests(unittest.TestCase):
    def setUp(self):
        self.source_bytes = SOURCE.read_bytes()
        self.source = json.loads(self.source_bytes)

    def test_real_research_review_has_no_synthetic_risk_and_no_buy(self):
        result = build_reviews(self.source_bytes)
        self.assertEqual(result["schema"], "V29_REAL_ISSUER_RESEARCH_REVIEW_V1")
        self.assertEqual(result["research_as_of"], "2026-10-30")
        self.assertFalse(result["trade_authorized"])
        self.assertFalse(result["synthetic_risk_fields_used"])
        self.assertEqual(result["live_buy_eligibility"], "NOT_AUTHORIZED")
        cases = {item["security_id"]: item for item in result["cases"]}
        self.assertEqual(set(cases), {"SZSE:300408", "SSE:688002"})
        self.assertEqual(cases["SZSE:300408"]["observed_reference_price_cny"], 84.54)
        self.assertEqual(cases["SSE:688002"]["observed_reference_price_cny"], 139.03)
        for case in cases.values():
            self.assertEqual(case["quote_session"], "2026-10-29")
            self.assertIsNone(case["human_stop_take_profit_position_size"])
            self.assertIsNone(case["decision_packet"])
            self.assertIsNone(case["contemplated_action"])
            self.assertFalse(case["buy_add_authorized"])
            self.assertFalse(case["strategy_alpha_and_untouched_oos_verified"])
            self.assertTrue(case["source_urls"]["report"].startswith("https://"))

    def test_research_only_source_cannot_be_promoted_by_editing_status(self):
        altered = copy.deepcopy(self.source)
        altered["buy_eligibility"] = "AUTHORIZED"
        with self.assertRaisesRegex(ValueError, "SOURCE_RESEARCH_ONLY"):
            build_reviews(json.dumps(altered).encode())
        altered = copy.deepcopy(self.source)
        altered["independent_alpha_evidence"] = True
        with self.assertRaisesRegex(ValueError, "SOURCE_RESEARCH_ONLY"):
            build_reviews(json.dumps(altered).encode())

    def test_quote_date_and_duplicate_identity_rejected(self):
        altered = copy.deepcopy(self.source)
        altered["cases"][0]["quote_asof_beijing"] = "2026-11-02 15:00"
        with self.assertRaisesRegex(ValueError, "QUOTE_DATE_SOURCE"):
            build_reviews(json.dumps(altered).encode())
        altered = copy.deepcopy(self.source)
        altered["cases"][1]["security_id"] = "SZSE:300408"
        with self.assertRaisesRegex(ValueError, "UNEXPECTED_OR_DUPLICATED"):
            build_reviews(json.dumps(altered).encode())

    def test_hash_binds_original_bytes_and_is_deterministic(self):
        a = build_reviews(self.source_bytes)
        b = build_reviews(self.source_bytes)
        self.assertEqual(a, b)
        import hashlib
        self.assertEqual(a["financial_research_source_sha256"],
                         hashlib.sha256(self.source_bytes).hexdigest())


if __name__ == "__main__":
    unittest.main()
