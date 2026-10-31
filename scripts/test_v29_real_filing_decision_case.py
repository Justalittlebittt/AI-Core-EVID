"""Real filing -> V2.9 decision, without contamination by known 2025 returns."""
import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from v29_2025_filing_to_return_case import load_inputs
from v29_real_filing_decision_case import build_as_disclosed_cases

SESSIONS = ["2025-04-14", "2025-04-25", "2025-04-28"]


class TestRealFilingDecision(unittest.TestCase):
    def setUp(self):
        self.filings, self.sha = load_inputs()

    def cases(self, filings=None, sessions=None):
        return build_as_disclosed_cases(
            self.filings if filings is None else filings,
            SESSIONS if sessions is None else sessions, self.sha)

    def test_two_real_issuer_cases_are_fail_closed(self):
        result = self.cases()
        self.assertEqual(result["live_buy_eligibility"], "NOT_AUTHORIZED")
        cases = {r["canonical_security_id"]: r for r in result["decision_cases"]}
        self.assertEqual(cases["SZSE:300408"]["as_of"], "2025-04-25")
        self.assertEqual(cases["SSE:688002"]["as_of"], "2025-04-14")
        for case in cases.values():
            self.assertEqual(case["evaluation"]["discipline_decision"]["decision"],
                             "NO_ACTION_INSUFFICIENT_EVIDENCE")
            self.assertFalse(case["future_price_outcome_in_packet"])
            self.assertFalse(case["original_pdf_bytes_sealed"])
            self.assertEqual(case["risk_fields"],
                             "SYNTHETIC_INTEGRATION_FIXTURE_NOT_USER_INPUT")
            self.assertEqual(case["packet"]["research_context"]["evaluation_timestamp"][:10],
                             case["as_of"])
            self.assertGreater(case["financial_features_as_disclosed"]["revenue_yoy"], 0)

    def test_future_outcome_cannot_change_prior_decision(self):
        original = self.cases()["decision_cases"]
        changed = copy.deepcopy(self.filings)
        # Any added ex-post outcomes must be ignored, never enter packet hashes.
        for row in changed["issuers"]:
            row["future_2025_return"] = 999.0
            row["next_year_quote"] = 999999
        altered = self.cases(filings=changed)["decision_cases"]
        self.assertEqual(original, altered)

    def test_date_and_calendar_fail_closed(self):
        wrong = copy.deepcopy(self.filings)
        wrong["issuers"][0]["published_on"] = "2024-12-30"
        with self.assertRaisesRegex(ValueError, "DISCLOSURE_BEFORE_PERIOD_END"):
            self.cases(filings=wrong)
        with self.assertRaisesRegex(ValueError, "INVALID_OR_DUPLICATE_TRADING_CALENDAR"):
            self.cases(sessions=["2025-04-25", "2025-04-14"])
        with self.assertRaisesRegex(ValueError, "NO_VERIFIED_POST_DISCLOSURE_SESSION"):
            self.cases(sessions=["2025-04-01"])

    def test_issuer_identity_and_bad_filing_source_rejected(self):
        wrong = copy.deepcopy(self.filings)
        wrong["issuers"][0]["canonical_id"] = "SZSE:000001"
        with self.assertRaisesRegex(ValueError, "WRONG_FILING_COHORT"):
            self.cases(filings=wrong)
        with self.assertRaisesRegex(ValueError, "INVALID_FILING_SOURCE_HASH"):
            build_as_disclosed_cases(self.filings, SESSIONS, "not-a-sha")


if __name__ == "__main__":
    unittest.main()
