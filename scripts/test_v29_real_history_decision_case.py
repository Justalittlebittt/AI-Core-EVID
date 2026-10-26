"""Test real-history report -> decision packet integration without network."""
import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from v29_real_history_decision_case import build_historical_case


def report():
    return {
        "schema": "AI_CORE_EVID_HISTORICAL_DESCRIPTIVE_RANK_V1",
        "as_of": "2026-09-09",
        "decision_case_admission": "BLOCKED_UNVALIDATED_FACTOR",
        "live_buy_eligibility": "NOT_AUTHORIZED",
        "historical_research_result": "V2.8.1: 0 OF 9 FACTORS PROMOTED",
        "real_historical_source": {
            "candidate_strategy_validated": False,
            "frozen_research_asof_eligibility_verified": True,
        },
        "ranking": [{
            "canonical_security_id": "SZSE:000001", "signal_date": "2026-09-09",
            "ret_20": 0.03, "descriptive_rank": 1,
        }],
    }


class Tests(unittest.TestCase):
    def test_fail_closed_real_history(self):
        case = build_historical_case(report(), "SZSE:000001")
        self.assertEqual(case["decision"]["discipline_decision"]["decision"], "NO_ACTION_INSUFFICIENT_EVIDENCE")
        self.assertEqual(case["risk_input_status"], "SYNTHETIC_DEMO_ONLY")
        self.assertEqual(len(case["source_report_sha256"]), 64)

    def test_unknown_security_rejected(self):
        with self.assertRaisesRegex(ValueError, "SECURITY_NOT_UNIQUE"):
            build_historical_case(report(), "SSE:600000")

    def test_false_authorization_rejected(self):
        r = report()
        r["live_buy_eligibility"] = "ACTION_ELIGIBLE"
        with self.assertRaisesRegex(ValueError, "UNEXPECTED_LIVE"):
            build_historical_case(r, "SZSE:000001")

    def test_unverified_source_rejected(self):
        r = report()
        r["real_historical_source"]["frozen_research_asof_eligibility_verified"] = False
        with self.assertRaisesRegex(ValueError, "HISTORICAL_SOURCE_IDENTITY"):
            build_historical_case(r, "SZSE:000001")

    def test_signal_date_mismatch_rejected(self):
        r = report()
        r["ranking"][0]["signal_date"] = "2026-09-08"
        with self.assertRaisesRegex(ValueError, "SIGNAL_DATE_MISMATCH"):
            build_historical_case(r, "SZSE:000001")


if __name__ == "__main__":
    unittest.main()
