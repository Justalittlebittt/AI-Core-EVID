"""Synthetic price alignment and frozen original-table membership tests."""
from datetime import date, timedelta
import unittest

from v29_historical_original15_price_pair import EXPECTED, compute, fixed_records

def sample():
    original = [{"security_id": "SSE:600088", "fiscal_year": 2022,
                 "official_announcement_day": "2023-03-01"}]
    dates = [(date(2023, 3, 2) + timedelta(days=i)).isoformat() for i in range(45)]
    calendar = {"2023": [{"calendar_date": d, "is_trading_day": "1"} for d in dates]}
    base = [{"date": d, "code": "sh.600088", "close": str(10 + i / 10),
             "adjustflag": "3", "tradestatus": "1", "isST": "0"}
            for i, d in enumerate(dates)]
    adjusted = [dict(r, adjustflag="2") for r in base]
    quotes = {"2022|SSE:600088": {"unadjusted": base, "forward_adjusted": adjusted}}
    return original, calendar, quotes

class PricePairTests(unittest.TestCase):
    def test_real_original_membership_fixed_before_market_queries(self):
        rows = fixed_records()
        self.assertEqual(len(rows), 15)
        self.assertEqual({(x["fiscal_year"], x["security_id"]) for x in rows}, EXPECTED)

    def test_twentieth_session_and_retro_return(self):
        x, cal, quotes = sample()
        r = compute(x, cal, quotes)[0]
        self.assertEqual(r["entry_session"], "2023-03-02")
        self.assertEqual(r["twentieth_session"], "2023-03-21")
        self.assertEqual(r["status"], "RETROSPECTIVE_PRICE_PAIR_AVAILABLE")
        self.assertAlmostEqual(r["unadjusted_price_return"], 11.9 / 10 - 1)
        self.assertFalse(r["historical_dividend_total_return_certified"])
        self.assertFalse(r["strategy_alpha_validated"])

    def test_missing_endpoint_kept_with_identity(self):
        x, cal, quotes = sample()
        quotes["2022|SSE:600088"]["unadjusted"].pop(19)
        r = compute(x, cal, quotes)[0]
        self.assertEqual(r["security_id"], "SSE:600088")
        self.assertEqual(r["status"], "INCOMPLETE_NEVER_DROP")
        self.assertIn("MISSING_PRICE_ENDPOINT", r["failure_reasons"])

    def test_suspended_and_st_do_not_become_returns(self):
        x, cal, quotes = sample()
        quotes["2022|SSE:600088"]["unadjusted"][0]["tradestatus"] = "0"
        r = compute(x, cal, quotes)[0]
        self.assertIsNone(r["unadjusted_price_return"])
        self.assertIn("ENTRY_OR_EXIT_NOT_TRADEABLE_OR_ST", r["failure_reasons"])

    def test_no_same_day_signal_leakage(self):
        x, cal, quotes = sample()
        x[0]["official_announcement_day"] = "2023-03-02"
        r = compute(x, cal, quotes)[0]
        self.assertEqual(r["entry_session"], "2023-03-03")

    def test_adjustment_flag_mismatch_rejected(self):
        x, cal, quotes = sample()
        quotes["2022|SSE:600088"]["forward_adjusted"][0]["adjustflag"] = "3"
        with self.assertRaisesRegex(ValueError, "QUOTE_IDENTITY_OR_ADJUSTMENT_CHANGED"):
            compute(x, cal, quotes)

if __name__ == "__main__":
    unittest.main()
