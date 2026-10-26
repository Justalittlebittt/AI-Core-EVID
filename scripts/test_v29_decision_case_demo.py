"""Regression checks for the isolated Decision Case wiring; no market data required."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from v29_decision_case_demo import build_case
from v29_decision_packet_adapter import adapt_and_evaluate, DecisionPacketError


class DecisionCaseIntegrationTests(unittest.TestCase):
    def test_no_unsupported_buy(self):
        case = build_case()
        self.assertEqual(case["evaluation"]["discipline_decision"]["decision"], "NO_ACTION_INSUFFICIENT_EVIDENCE")
        self.assertEqual(case["source"]["kind"], "SYNTHETIC_TEST_FIXTURE")

    def test_override_cannot_make_unvalidated_buy_eligible(self):
        p = build_case()["packet"]
        p["override_context"] = {"override_requested": True, "override_reason": "test"}
        result = adapt_and_evaluate(p)
        self.assertEqual(result["discipline_decision"]["decision"], "NO_ACTION_INSUFFICIENT_EVIDENCE")

    def test_invalid_input_fails_closed(self):
        p = build_case()["packet"]
        del p["risk_context"]["position_limit"]
        with self.assertRaises(DecisionPacketError):
            adapt_and_evaluate(p)

    def test_missing_validity_downgrades_even_strong_claim(self):
        p = build_case()["packet"]
        p["validity"]["evidence_strength"] = "STRONG"
        result = adapt_and_evaluate(p)
        self.assertEqual(result["adapter_metadata"]["effective_evidence_strength"], "INSUFFICIENT")
        self.assertEqual(result["discipline_decision"]["decision"], "NO_ACTION_INSUFFICIENT_EVIDENCE")

    def test_no_research_data_access(self):
        case = build_case()
        self.assertFalse(case["source"]["validated_candidate_signal"])
        self.assertEqual(case["source"]["market_data"], "NONE")


if __name__ == "__main__":
    unittest.main()
