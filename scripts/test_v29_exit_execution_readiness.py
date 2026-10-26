"""Execution-readiness tests use existing watchlist and V2.9 discipline logic."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from v29_position_watchlist import evaluate_watchlist
from v29_exit_execution_readiness import apply_execution_constraints

NOW="2026-10-26T15:30:00+08:00"
def base():
    p=[dict(security_id="SSE:600000",quantity=100,entry_price=10.0,stop_price=9.0,take_profit_price=12.0,position_fraction=.05,position_limit=.1,risk_budget_used=.01,risk_budget_limit=.02,invalidation_triggered=False)]
    q=[dict(security_id="SSE:600000",as_of="2026-10-26T15:00:00+08:00",close=8.5,source="USER_SUPPLIED")]
    return evaluate_watchlist(p,q,NOW)
def context(**override):
    c=dict(security_id="SSE:600000",as_of="2026-10-26T15:00:00+08:00",sellable_quantity=100,trading_status="TRADING")
    c.update(override)
    return [c]

class Tests(unittest.TestCase):
    def test_required_exit_not_cleared_by_suspension(self):
        x=apply_execution_constraints(base(),context(trading_status="SUSPENDED"),NOW)
        self.assertTrue(x["positions"][0]["exit_required"])
        self.assertFalse(x["positions"][0]["can_submit_full_sell_order"])

    def test_tplus1_unsellable_retains_exit(self):
        x=apply_execution_constraints(base(),context(sellable_quantity=0),NOW)
        self.assertEqual(x["required_exit_with_unconfirmed_full_execution_count"],1)
        self.assertEqual(x["positions"][0]["execution_reason"],"NO_TPLUS1_SELLABLE_SHARES")

    def test_partial_sellable_is_not_full_execution(self):
        x=apply_execution_constraints(base(),context(sellable_quantity=50),NOW)
        self.assertFalse(x["positions"][0]["can_submit_full_sell_order"])

    def test_full_sellable_only_means_possible(self):
        x=apply_execution_constraints(base(),context(),NOW)
        self.assertTrue(x["positions"][0]["can_submit_full_sell_order"])
        self.assertFalse(x["positions"][0]["execution_confirmed"])

    def test_missing_broker_context_unknown(self):
        x=apply_execution_constraints(base(),[],NOW)
        self.assertIsNone(x["positions"][0]["can_submit_full_sell_order"])
        self.assertTrue(x["positions"][0]["exit_required"])

    def test_previous_day_context_rejected_as_stale(self):
        x=apply_execution_constraints(base(),context(as_of="2026-10-23T15:00:00+08:00"),NOW)
        self.assertEqual(x["positions"][0]["execution_reason"],"BROKER_STATUS_PREVIOUS_DAY")

    def test_future_context_rejected(self):
        with self.assertRaisesRegex(ValueError,"FUTURE_EXECUTION_STATUS"):
            apply_execution_constraints(base(),context(as_of="2026-10-27T15:00:00+08:00"),NOW)

    def test_inconsistent_quantity_rejected(self):
        with self.assertRaisesRegex(ValueError,"SELLABLE_EXCEEDS_POSITION"):
            apply_execution_constraints(base(),context(sellable_quantity=200),NOW)

    def test_timestamp_mismatch_rejected(self):
        with self.assertRaisesRegex(ValueError,"WATCHLIST_EVALUATION_TIMESTAMP_MISMATCH"):
            apply_execution_constraints(base(),context(),"2026-10-26T15:31:00+08:00")

    def test_unknown_trading_status(self):
        x=apply_execution_constraints(base(),context(trading_status="UNKNOWN"),NOW)
        self.assertIsNone(x["positions"][0]["can_submit_full_sell_order"])

if __name__=="__main__":
    unittest.main()
