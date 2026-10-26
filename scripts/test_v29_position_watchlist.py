"""Offline watchlist regression: no account data, network access or trading."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from v29_position_watchlist import evaluate_watchlist

AT = "2026-10-26T15:30:00+08:00"
def holding(sid="SSE:600000", **kw):
    row = dict(security_id=sid, quantity=100, entry_price=10.0, stop_price=9.0,
               take_profit_price=12.0, position_fraction=0.05, position_limit=0.1,
               risk_budget_used=0.01, risk_budget_limit=0.02, invalidation_triggered=False)
    row.update(kw)
    return row
def quote(sid="SSE:600000", **kw):
    row = dict(security_id=sid, as_of="2026-10-26T15:00:00+08:00", close=9.5, source="USER_SUPPLIED")
    row.update(kw)
    return row

class WatchlistTests(unittest.TestCase):
    def test_healthy_snapshot_does_not_imply_hold_recommendation(self):
        x = evaluate_watchlist([holding()], [quote()], AT)
        self.assertEqual(x["positions"][0]["status"], "NO_PRECOMMITTED_EXIT_TRIGGER")
        self.assertEqual(x["positions"][0]["quote_status"], "USABLE_USER_SUPPLIED")

    def test_known_stop_breach_required(self):
        x = evaluate_watchlist([holding()], [quote(close=8.8)], AT)
        self.assertEqual(x["positions"][0]["discipline_decision"]["decision"], "EXIT_REQUIRED")

    def test_profit_exit_required(self):
        x = evaluate_watchlist([holding()], [quote(close=12.2)], AT)
        self.assertEqual(x["exit_required_count"], 1)

    def test_stale_quote_cannot_clear_or_trigger_exit(self):
        x = evaluate_watchlist([holding()], [quote(close=8.0, as_of="2026-10-20T15:00:00+08:00")], AT)
        self.assertEqual(x["positions"][0]["quote_status"], "STALE")
        self.assertIsNone(x["positions"][0]["discipline_decision"])
        self.assertIsNone(x["positions"][0]["stop_breached"])

    def test_stale_quote_independent_invalidation_exits(self):
        x = evaluate_watchlist([holding(invalidation_triggered=True)], [quote(as_of="2026-10-20T15:00:00+08:00")], AT)
        self.assertEqual(x["positions"][0]["discipline_decision"]["decision"], "EXIT_REQUIRED")

    def test_missing_quote_explicit_unknown(self):
        x = evaluate_watchlist([holding()], [], AT)
        self.assertEqual(x["unassessable_quote_count"], 1)
        self.assertEqual(x["positions"][0]["quote_status"], "MISSING")

    def test_future_quote_rejected(self):
        with self.assertRaisesRegex(ValueError, "QUOTE_FROM_FUTURE"):
            evaluate_watchlist([holding()], [quote(as_of="2026-10-27T15:00:00+08:00")], AT)

    def test_duplicate_quotes_rejected(self):
        with self.assertRaisesRegex(ValueError, "QUOTES_DUPLICATE"):
            evaluate_watchlist([holding()], [quote(), quote()], AT)

    def test_missing_stop_rejected(self):
        p = holding()
        del p["stop_price"]
        with self.assertRaisesRegex(ValueError, "POSITIONS_SCHEMA_INVALID"):
            evaluate_watchlist([p], [], AT)

    def test_unrelated_quote_rejected(self):
        with self.assertRaisesRegex(ValueError, "UNMATCHED_QUOTE"):
            evaluate_watchlist([holding()], [quote(sid="SZSE:000001")], AT)

    def test_non_numeric_quote_rejected(self):
        with self.assertRaisesRegex(ValueError, "INVALID_QUOTE_PRICE"):
            evaluate_watchlist([holding()], [quote(close=True)], AT)

    def test_repeatable_hash_and_order(self):
        positions = [holding("SZSE:000001"), holding("SSE:600000")]
        quotes = [quote("SSE:600000"), quote("SZSE:000001")]
        a = evaluate_watchlist(positions, quotes, AT)
        b = evaluate_watchlist(positions, quotes, AT)
        self.assertEqual(a, b)
        self.assertEqual([p["security_id"] for p in a["positions"]], ["SSE:600000", "SZSE:000001"])

if __name__ == "__main__":
    unittest.main()
