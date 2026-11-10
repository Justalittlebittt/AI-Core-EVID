"""Real archived 8-stock candidate-to-evidence report; no synthetic prices or future outcomes."""
import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from v31_research_candidate_decision import build, render, SCHEMA


class RealCandidateReportTests(unittest.TestCase):
    def test_eight_real_issuers_selection_and_paper_entry_separate(self):
        report = build()
        self.assertEqual(report["schema"], SCHEMA)
        self.assertEqual(report["candidate_research_asof"], "2026-10-30")
        self.assertEqual(report["quote_reference_session_not_current"], "2026-11-02")
        self.assertEqual(report["candidate_count"], 8)
        self.assertEqual(report["eight_minimum_lot_paper_entry_notional_cny"], 54558.0)
        self.assertEqual([x["security_id"] for x in report["candidates"]],
                         ["SZSE:300199", "SZSE:002636", "SZSE:301536",
                          "SZSE:000408", "SZSE:002463", "SSE:603256",
                          "SZSE:002552", "SZSE:300223"])
        self.assertEqual([x["rank_in_predeclared_2026_research"] for x in report["candidates"]],
                         list(range(1, 9)))
        self.assertFalse(report["selection_uses_nov02_entry_quotes"])
        self.assertFalse(report["future_outcomes_read"])
        self.assertFalse(report["trade_authorized"])
        self.assertEqual(report["live_buy_eligibility"], "NOT_AUTHORIZED")
        self.assertTrue(all(x["risk_and_account_inputs"] is None for x in report["candidates"]))

    def test_prior_historical_study_is_context_only_not_eight_validation(self):
        report = build()
        context = report["separate_2025_historical_screen_not_equivalent_to_2026_eight"]
        self.assertEqual(context["historical_admission"], "DO_NOT_PROMOTE")
        self.assertEqual(context["historical_selected_count"], 29)
        self.assertAlmostEqual(context["historical_selected_minus_same_entry_day_random_net"],
                               -0.0010464552757054081)
        self.assertFalse(report["candidate_strategy_independently_validated"])
        self.assertEqual(len(report["source_sha256"]["frozen_preentry_eight"]), 64)
        self.assertEqual(len(report["source_sha256"]["sealed_122_nov02_entry"]), 64)

    def test_human_readable_real_candidates_never_implicate_buy(self):
        report = build()
        text = render(report)
        self.assertIn("SZSE:300199", text)
        self.assertIn("SSE:603256", text)
        self.assertIn("54,558", text)
        self.assertIn("非最新行情", text)
        self.assertIn("不授权买入", text)
        self.assertIn("NO_ACTION_INSUFFICIENT_PREDICTIVE_EVIDENCE", text)
        self.assertEqual(text, render(build()))

    def test_render_fails_closed_if_promoted_or_candidate_changed(self):
        original = build()
        for field, value in (
            ("trade_authorized", True),
            ("live_buy_eligibility", "AUTHORIZED"),
            ("candidate_strategy_independently_validated", True),
            ("candidate_count", 7),
        ):
            altered = copy.deepcopy(original)
            altered[field] = value
            with self.assertRaisesRegex(ValueError, "UNSAFE_CANDIDATE_BRIEF"):
                render(altered)
        altered = copy.deepcopy(original)
        altered["candidates"][0]["action"] = "BUY"
        with self.assertRaisesRegex(ValueError, "UNSAFE_CANDIDATE_BRIEF"):
            render(altered)


if __name__ == "__main__":
    unittest.main()
