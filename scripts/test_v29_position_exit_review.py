"""Offline tests: existing V2.9 exit discipline is the only authority."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from v29_position_exit_review import review


def position(**changes):
    d = {
        "security_id": "SSE:600000", "as_of": "2026-09-09T15:00:00+08:00",
        "quantity": 100, "entry_price": 10.0, "current_price": 9.5,
        "stop_price": 9.0, "take_profit_price": 12.0,
        "position_fraction": 0.05, "position_limit": 0.10,
        "risk_budget_used": 0.01, "risk_budget_limit": 0.02,
        "invalidation_triggered": False,
    }
    d.update(changes)
    return d


class ExitReviewTests(unittest.TestCase):
    def test_no_trigger_is_not_buy_or_hold_recommendation(self):
        x = review(position())
        self.assertEqual(x["status"], "NO_PRECOMMITTED_EXIT_TRIGGER")
        self.assertEqual(x["discipline_decision"]["decision"], "ACTION_ELIGIBLE")
        self.assertEqual(x["execution_status"], "NO_BROKERAGE_EXECUTION")

    def test_stop_loss_forces_exit(self):
        x = review(position(current_price=8.9, override_requested=True, override_reason="want to wait"))
        self.assertEqual(x["discipline_decision"]["decision"], "EXIT_REQUIRED")
        self.assertIn("STOP_LOSS_BREACHED", x["discipline_decision"]["reasons"])

    def test_take_profit_forces_exit(self):
        x = review(position(current_price=12.0))
        self.assertEqual(x["discipline_decision"]["decision"], "EXIT_REQUIRED")
        self.assertIn("EXIT_RULE_TRIGGERED", x["discipline_decision"]["reasons"])

    def test_invalidation_forces_exit(self):
        x = review(position(invalidation_triggered=True))
        self.assertEqual(x["discipline_decision"]["decision"], "EXIT_REQUIRED")

    def test_missing_price_fails_safe(self):
        x = review(position(current_price=None))
        self.assertEqual(x["status"], "PRICE_MISSING")
        self.assertIsNone(x["discipline_decision"])

    def test_missing_price_with_independent_invalidation_exits(self):
        x = review(position(current_price=None, invalidation_triggered=True))
        self.assertEqual(x["discipline_decision"]["decision"], "EXIT_REQUIRED")
        self.assertIsNone(x["stop_breached"])

    def test_malformed_price_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "INVALID_NUMERIC"):
            review(position(current_price=float("nan")))

    def test_timestamp_requires_timezone(self):
        with self.assertRaisesRegex(ValueError, "AS_OF_MUST_BE_OFFSET_AWARE"):
            review(position(as_of="2026-09-09T15:00:00"))

    def test_missing_rule_is_not_inferred(self):
        x = position()
        del x["stop_price"]
        with self.assertRaisesRegex(ValueError, "MISSING_REQUIRED"):
            review(x)

    def test_no_silent_exit_rule_revisions(self):
        with self.assertRaisesRegex(ValueError, "UNRECOGNIZED"):
            review(position(stop_price_revised=8.0))


if __name__ == "__main__":
    unittest.main()
