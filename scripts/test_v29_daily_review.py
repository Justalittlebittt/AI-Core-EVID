"""Single-command daily product integration, no network and no real holdings."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from v29_daily_review import run_daily, render_text

AT="2026-10-26T15:30:00+08:00"
def pos(sid="SSE:600000", **kw):
    r=dict(security_id=sid,quantity=100,entry_price=10.0,stop_price=9.0,
           take_profit_price=12.0,position_fraction=.05,position_limit=.1,
           risk_budget_used=.01,risk_budget_limit=.02,invalidation_triggered=False)
    r.update(kw)
    return r
def quote(sid="SSE:600000",**kw):
    r=dict(security_id=sid,as_of="2026-10-26T15:00:00+08:00",
           close=8.5,source="USER_SUPPLIED")
    r.update(kw)
    return r
def broker(sid="SSE:600000",**kw):
    r=dict(security_id=sid,as_of="2026-10-26T15:00:00+08:00",
           sellable_quantity=0,trading_status="TRADING")
    r.update(kw)
    return r

class DailyReviewTests(unittest.TestCase):
    def test_required_exit_and_tplus1_block(self):
        x=run_daily([pos()],AT,"2026-10-26",[quote()],[broker()])
        self.assertEqual(x["exit_required_count"],1)
        self.assertEqual(x["rows"][0]["decision"],"EXIT_REQUIRED_EXECUTION_UNCONFIRMED")
        self.assertEqual(x["rows"][0]["execution_status"],"NO_TPLUS1_SELLABLE_SHARES")
        self.assertIn("必须退出",render_text(x))

    def test_multiple_positions_sorted_by_priority(self):
        x=run_daily([pos("SZSE:000001"),pos("SSE:600000")],AT,"2026-10-26",
                    [quote("SSE:600000",close=9.5)],[])
        self.assertEqual([r["security_id"] for r in x["rows"]],["SZSE:000001","SSE:600000"])
        self.assertEqual(x["rows"][0]["decision"],"UNASSESSABLE_QUOTE")

    def test_previous_session_stop_cannot_trigger(self):
        x=run_daily([pos()],AT,"2026-10-26",[quote(as_of="2026-10-23T15:00:00+08:00")])
        self.assertEqual(x["exit_required_count"],0)
        self.assertEqual(x["unassessable_quote_count"],1)

    def test_invalidation_survives_wrong_session_quote(self):
        x=run_daily([pos(invalidation_triggered=True)],AT,"2026-10-26",
                    [quote(as_of="2026-10-23T15:00:00+08:00")])
        self.assertEqual(x["exit_required_count"],1)
        self.assertEqual(x["rows"][0]["exit_reasons"],["INVALIDATION_TRIGGERED"])

    def test_provider_failure_does_not_become_safe_hold(self):
        from v29_position_watchlist import evaluate_watchlist
        def failure(positions, at, expected_session, max_quote_age_hours):
            x=evaluate_watchlist(positions,[],at,max_quote_age_hours)
            x["market_feed"]={"unavailable_or_rejected":{"__provider__":"UNAVAILABLE"}}
            return x
        x=run_daily([pos()],AT,"2026-10-26",live_fetcher=failure)
        self.assertEqual(x["rows"][0]["decision"],"UNASSESSABLE_QUOTE")
        self.assertEqual(x["data_mode"],"PUBLIC_UNOFFICIAL_QUOTE")

    def test_no_broker_snapshot_is_unknown(self):
        x=run_daily([pos()],AT,"2026-10-26",[quote()])
        self.assertEqual(x["rows"][0]["execution_status"],"BROKER_SELLABLE_QUANTITY_MISSING")

    def test_conflicting_session_rejected(self):
        with self.assertRaisesRegex(ValueError,"EXPECTED_SESSION_DIFFERS"):
            run_daily([pos()],AT,"2026-10-23",[quote()])

    def test_timezone_must_be_explicit(self):
        with self.assertRaisesRegex(ValueError,"EVALUATION_REQUIRES_TIMEZONE"):
            run_daily([pos()],"2026-10-26T15:30:00","2026-10-26",[quote()])

    def test_same_input_deterministic(self):
        a=run_daily([pos()],AT,"2026-10-26",[quote()])
        b=run_daily([pos()],AT,"2026-10-26",[quote()])
        self.assertEqual(a,b)

    def test_fully_sellable_still_unconfirmed(self):
        x=run_daily([pos()],AT,"2026-10-26",[quote()],[broker(sellable_quantity=100)])
        self.assertEqual(x["rows"][0]["execution_status"],"FULL_SELL_ORDER_POSSIBLE_NOT_CONFIRMED")
        self.assertFalse(x["rows"][0]["execution_confirmed"])

if __name__=="__main__":
    unittest.main()
