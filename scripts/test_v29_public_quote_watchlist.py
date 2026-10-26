"""Provider payload tests. No actual holdings or network dependency."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from v29_public_quote_watchlist import decode_quote, fetch_watchlist, to_vendor_id

AT = "2026-10-26T11:45:00+08:00"
def position(**kwargs):
    d = dict(security_id="SSE:600000", quantity=100, entry_price=10.0,
        stop_price=9.0, take_profit_price=12.0, position_fraction=0.05,
        position_limit=0.10, risk_budget_used=0.01, risk_budget_limit=0.02,
        invalidation_triggered=False)
    d.update(kwargs)
    return d

def line(vendor="sh", ticker="600000", price="8.80", time="20261026113000"):
    fields = [""] * 35
    fields[0] = "1"
    fields[1] = "Example"
    fields[2] = ticker
    fields[3] = price
    fields[4] = "10.00"
    fields[30] = time
    return 'v_' + vendor + ticker + '="' + "~".join(fields) + '";'

class MockResponse:
    def __init__(self, body):
        self.body = body.encode("gbk")
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def read(self, n):
        return self.body

def opener(body):
    def open_request(req, timeout):
        return MockResponse(body)
    return open_request

class ProviderTests(unittest.TestCase):
    def test_security_identity(self):
        self.assertEqual(to_vendor_id("SZSE:000001"), "sz000001")
        with self.assertRaises(ValueError):
            to_vendor_id("BJSE:830000")

    def test_valid_quote_to_required_exit(self):
        result = fetch_watchlist([position()], AT, "2026-10-26", opener=opener(line()))
        self.assertEqual(result["market_feed"]["accepted_quote_count"], 1)
        self.assertEqual(result["positions"][0]["discipline_decision"]["decision"], "EXIT_REQUIRED")
        self.assertEqual(result["positions"][0]["quote_status"], "USABLE_USER_SUPPLIED")

    def test_previous_session_rejected(self):
        result = fetch_watchlist([position()], AT, "2026-10-26", opener=opener(line(time="20261023150000")))
        self.assertEqual(result["positions"][0]["quote_status"], "MISSING")
        self.assertEqual(result["market_feed"]["unavailable_or_rejected"]["SSE:600000"], "WRONG_TRADING_SESSION")

    def test_future_timestamp_rejected(self):
        result = fetch_watchlist([position()], AT, "2026-10-26", opener=opener(line(time="20261026150000")))
        self.assertEqual(result["positions"][0]["quote_status"], "MISSING")

    def test_response_symbol_mismatch_rejected(self):
        result = fetch_watchlist([position()], AT, "2026-10-26", opener=opener(line(ticker="600001")))
        self.assertEqual(result["market_feed"]["accepted_quote_count"], 0)
        self.assertIsNone(result["positions"][0]["discipline_decision"])

    def test_network_failure_unknown(self):
        def broken(*args, **kwargs):
            raise OSError("network unavailable")
        result = fetch_watchlist([position()], AT, "2026-10-26", opener=broken)
        self.assertEqual(result["positions"][0]["quote_status"], "MISSING")
        self.assertIn("__provider__", result["market_feed"]["unavailable_or_rejected"])

    def test_invalidation_survives_network_failure(self):
        result = fetch_watchlist([position(invalidation_triggered=True)], AT, "2026-10-26",
                                 opener=opener("not a stock response"))
        self.assertEqual(result["positions"][0]["discipline_decision"]["decision"], "EXIT_REQUIRED")

    def test_duplicate_quote_is_invalid(self):
        with self.assertRaisesRegex(ValueError, "UNEXPECTED_OR_DUPLICATE"):
            decode_quote(line() + "\n" + line(), {"sh600000"})

    def test_unrecognized_response_format(self):
        with self.assertRaisesRegex(ValueError, "UNRECOGNIZED_QUOTE_FORMAT"):
            decode_quote("arbitrary html", {"sh600000"})

    def test_quote_age_expired(self):
        result = fetch_watchlist([position()], "2026-10-26T17:00:00+08:00",
                                 "2026-10-26", max_quote_age_hours=1,
                                 opener=opener(line()))
        self.assertEqual(result["positions"][0]["quote_status"], "STALE")
        self.assertIsNone(result["positions"][0]["discipline_decision"])

if __name__ == "__main__":
    unittest.main()
