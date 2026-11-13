"""Single-command daily product integration, no network and no real holdings."""
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch
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

    def test_public_provider_provenance_survives_daily_report(self):
        from v29_position_watchlist import evaluate_watchlist
        def public(positions, at, expected_session, max_quote_age_hours):
            result=evaluate_watchlist(positions,[quote(source="VERIFIED_IMPORT")],
                                      at,max_quote_age_hours)
            result["market_feed"]={"provider":"TENCENT_FINANCE_UNOFFICIAL_TILDE_ENDPOINT"}
            return result
        report=run_daily([pos()],AT,"2026-10-26",live_fetcher=public)
        row=report["rows"][0]
        self.assertEqual(row["quote_source"],"VERIFIED_IMPORT")
        self.assertEqual(row["market_data_origin"],
                         "UNOFFICIAL_PUBLIC_PROVIDER_NOT_INDEPENDENTLY_VERIFIED")
        self.assertIn("UNOFFICIAL_PUBLIC_PROVIDER",render_text(report))

    def test_supplied_quote_provenance_is_not_relabelled_public(self):
        report=run_daily([pos()],AT,"2026-10-26",[quote(source="USER_SUPPLIED")])
        row=report["rows"][0]
        self.assertEqual(row["quote_source"],"USER_SUPPLIED")
        self.assertEqual(row["market_data_origin"],
                         "SUPPLIED_SNAPSHOT_NOT_INDEPENDENTLY_VERIFIED")

    def test_no_broker_snapshot_is_unknown(self):
        x=run_daily([pos()],AT,"2026-10-26",[quote()])
        self.assertEqual(x["rows"][0]["execution_status"],"BROKER_SELLABLE_QUANTITY_MISSING")

    def test_conflicting_session_rejected(self):
        with self.assertRaisesRegex(ValueError,"EXPECTED_SESSION_DIFFERS"):
            run_daily([pos()],AT,"2026-10-23",[quote()])

    def test_previous_completed_session_reference_alert_without_current_clearance(self):
        x=run_daily([pos()], "2026-10-26T09:30:00+08:00", "2026-10-23",
                    [quote(as_of="2026-10-23T15:00:00+08:00",close=8.5)],
                    max_quote_age_hours=72,allow_prior_session=True)
        self.assertTrue(x["reference_session_only"])
        self.assertIs(x["current_day_price_or_exit_clearance_established"],False)
        self.assertEqual(x["exit_required_count"],1)
        self.assertEqual(x["rows"][0]["decision"],
                         "EXIT_REQUIRED_REFERENCE_SESSION_EXECUTION_UNCONFIRMED")
        self.assertIn("今天行情与成交未确认",render_text(x))

    def test_previous_session_non_trigger_is_not_today_safe(self):
        x=run_daily([pos()], "2026-10-26T09:30:00+08:00", "2026-10-23",
                    [quote(as_of="2026-10-23T15:00:00+08:00",close=9.5)],
                    max_quote_age_hours=72,allow_prior_session=True)
        self.assertEqual(x["rows"][0]["decision"],
                         "REFERENCE_SESSION_NO_EXIT_TRIGGER_NOT_CURRENT_CLEARANCE")
        self.assertIn("不得视为今天安全",render_text(x))

    def test_previous_session_reference_keeps_staleness_and_session_guards(self):
        x=run_daily([pos()], "2026-10-26T09:30:00+08:00", "2026-10-23",
                    [quote(as_of="2026-10-23T15:00:00+08:00")],
                    allow_prior_session=True)
        self.assertEqual(x["rows"][0]["decision"],"UNASSESSABLE_QUOTE")
        self.assertEqual(x["unassessable_quote_count"],1)
        y=run_daily([pos()], "2026-10-26T09:30:00+08:00", "2026-10-23",
                    [quote(as_of="2026-10-26T09:00:00+08:00")],
                    max_quote_age_hours=72,allow_prior_session=True)
        self.assertEqual(y["rows"][0]["decision"],"UNASSESSABLE_QUOTE")
        with self.assertRaisesRegex(ValueError,"EXPECTED_SESSION_DIFFERS"):
            run_daily([pos()],AT,"2026-10-27",[quote()],allow_prior_session=True)

    def test_timezone_must_be_explicit(self):
        with self.assertRaisesRegex(ValueError,"EVALUATION_REQUIRES_TIMEZONE"):
            run_daily([pos()],"2026-10-26T15:30:00","2026-10-26",[quote()])

    def test_wrong_session_duplicate_quote_rejected(self):
        with self.assertRaisesRegex(ValueError,"QUOTES_DUPLICATE"):
            run_daily([pos()],AT,"2026-10-26",
                      [quote(as_of="2026-10-23T15:00:00+08:00"),
                       quote(as_of="2026-10-23T15:00:00+08:00")])

    def test_wrong_session_quote_missing_timezone_rejected(self):
        with self.assertRaisesRegex(ValueError,"TIMESTAMP_REQUIRES_UTC_OFFSET"):
            run_daily([pos()],AT,"2026-10-26",
                      [quote(as_of="2026-10-23T15:00:00")])

    def test_same_input_deterministic(self):
        a=run_daily([pos()],AT,"2026-10-26",[quote()])
        b=run_daily([pos()],AT,"2026-10-26",[quote()])
        self.assertEqual(a,b)

    def test_fully_sellable_still_unconfirmed(self):
        x=run_daily([pos()],AT,"2026-10-26",[quote()],[broker(sellable_quantity=100)])
        self.assertEqual(x["rows"][0]["execution_status"],"FULL_SELL_ORDER_POSSIBLE_NOT_CONFIRMED")
        self.assertFalse(x["rows"][0]["execution_confirmed"])

    def test_exit_persists_after_rebound_without_broker_fill(self):
        first=run_daily([pos()],AT,"2026-10-26",[quote(close=8.5)])
        self.assertEqual(first["exit_required_count"],1)
        self.assertEqual(first["pending_exit_count"],1)
        second=run_daily([pos()],"2026-10-27T15:30:00+08:00","2026-10-27",
                         [quote(as_of="2026-10-27T15:00:00+08:00",close=10.5)],
                         prior_exit_state=first["pending_exit_state"])
        self.assertEqual(second["exit_required_count"],1)
        self.assertEqual(second["rows"][0]["decision"],"EXIT_REQUIRED_EXECUTION_UNCONFIRMED")
        self.assertTrue(second["rows"][0]["pending_exit_from_prior"])
        self.assertIn("STOP_LOSS_BREACHED",second["rows"][0]["exit_reasons"])
        self.assertEqual(second["pending_exit_state"]["pending"][0]["triggered_at"],AT)
        self.assertFalse(second["rows"][0]["execution_confirmed"])
        self.assertIn("既往退出未核销",render_text(second))

    def test_exit_survives_missing_or_stale_quote_and_fully_sellable_status(self):
        first=run_daily([pos()],AT,"2026-10-26",[quote(close=8.5)])
        second=run_daily([pos()],"2026-10-27T15:30:00+08:00","2026-10-27",
                         [],[broker(as_of="2026-10-27T15:00:00+08:00",
                                    sellable_quantity=100)],
                         prior_exit_state=first["pending_exit_state"])
        self.assertEqual(second["rows"][0]["quote_status"],"MISSING")
        self.assertEqual(second["exit_required_count"],1)
        self.assertEqual(second["unassessable_quote_count"],0)
        self.assertEqual(second["rows"][0]["execution_status"],
                         "FULL_SELL_ORDER_POSSIBLE_NOT_CONFIRMED")
        self.assertFalse(second["rows"][0]["execution_confirmed"])

    def test_no_prior_trigger_does_not_invent_exit(self):
        day="2026-10-27T15:30:00+08:00"
        result=run_daily([pos()],day,"2026-10-27",[])
        self.assertEqual(result["exit_required_count"],0)
        self.assertEqual(result["pending_exit_count"],0)
        self.assertEqual(result["rows"][0]["decision"],"UNASSESSABLE_QUOTE")

    def test_absent_holding_does_not_silently_clear_unconfirmed_prior_exit(self):
        first=run_daily([pos()],AT,"2026-10-26",[quote(close=8.5)])
        second=run_daily([pos("SZSE:000001")],"2026-10-27T15:30:00+08:00",
                         "2026-10-27",[],
                         prior_exit_state=first["pending_exit_state"])
        self.assertEqual(second["exit_required_count"],0)
        self.assertEqual(second["pending_exit_count"],1)
        self.assertEqual(second["unreconciled_missing_position_exit_ids"],["SSE:600000"])
        self.assertIn("SSE:600000",render_text(second))
        self.assertFalse(second["rows"][0]["pending_exit_from_prior"])

    def test_invalid_checkpoint_or_future_time_rejected(self):
        first=run_daily([pos()],AT,"2026-10-26",[quote()])
        bad={**first["pending_exit_state"],"updated_at":"2026-10-28T15:30:00+08:00"}
        with self.assertRaisesRegex(ValueError,"FUTURE_PENDING_EXIT_CHECKPOINT"):
            run_daily([pos()],"2026-10-27T15:30:00+08:00","2026-10-27",[],
                      prior_exit_state=bad)
        bad={"schema":"AI_CORE_EVID_PENDING_EXIT_STATE_V1","updated_at":AT,
             "pending":[{"security_id":"SSE:600000","triggered_at":AT,
                         "reasons":["STOP_LOSS_BREACHED"]}]*2}
        with self.assertRaisesRegex(ValueError,"INVALID_PENDING_EXIT_ENTRY"):
            run_daily([pos()],"2026-10-27T15:30:00+08:00","2026-10-27",[],
                      prior_exit_state=bad)

    def test_cli_automatically_restores_local_pending_exit_checkpoint(self):
        from v29_daily_review import main
        with tempfile.TemporaryDirectory() as root:
            directory=Path(root)
            holdings=directory/"holdings.json"
            quotes=directory/"quotes.json"
            report_path=directory/"latest_report.json"
            holdings.write_text(json.dumps([pos()]),encoding="utf-8")
            quotes.write_text(json.dumps([quote(close=8.5)]),encoding="utf-8")
            with patch("sys.argv",["daily","--positions",str(holdings),
                      "--quotes",str(quotes),"--at",AT,
                      "--expected-session","2026-10-26"]),redirect_stdout(StringIO()):
                main()
            checkpoint=directory/"holdings.pending_exits.json"
            self.assertTrue(checkpoint.exists())
            self.assertEqual(json.loads(checkpoint.read_text())["pending"][0]["security_id"],
                             "SSE:600000")
            quotes.write_text(json.dumps([quote(as_of="2026-10-27T15:00:00+08:00",
                                                 close=10.5)]),encoding="utf-8")
            with patch("sys.argv",["daily","--positions",str(holdings),
                      "--quotes",str(quotes),"--at","2026-10-27T15:30:00+08:00",
                      "--expected-session","2026-10-27",
                      "--json-out",str(report_path)]),redirect_stdout(StringIO()):
                main()
            output=json.loads(report_path.read_text())
            self.assertTrue(output["rows"][0]["pending_exit_from_prior"])
            self.assertEqual(output["exit_required_count"],1)
            self.assertEqual(output["pending_exit_state"]["pending"][0]["triggered_at"],AT)
            self.assertFalse(output["rows"][0]["execution_confirmed"])

if __name__=="__main__":
    unittest.main()
