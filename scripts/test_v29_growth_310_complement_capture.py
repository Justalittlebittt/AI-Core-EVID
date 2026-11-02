"""Synthetic-only 310 complement source tests; no real future prices."""
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from v29_growth_310_complement_capture import (
    one_complement, capture, save, read_parent, canonical_bytes, sha,
)

SAME_DAY = datetime(2026, 11, 27, 14, 0, tzinfo=timezone.utc)
SESSIONS = ["2026-11-02", "2026-11-27"]


def bar(day, flag, close=100, vol=2000):
    return {"date": day, "code": "sh.600001", "adjustflag": flag,
            "close": str(close), "volume": str(vol),
            "tradestatus": "1", "isST": "0"}


class ComplementCaptureTests(unittest.TestCase):
    def test_one_complement_complete_reference_only(self):
        raw = [bar(SESSIONS[0], "3"), bar(SESSIONS[-1], "3", 110)]
        adjusted = [bar(SESSIONS[0], "2"), bar(SESSIONS[-1], "2", 110)]
        row, source = one_complement("SSE:600001", SESSIONS, raw, adjusted)
        self.assertTrue(row["entry_tradeable"])
        self.assertTrue(row["exit_tradeable"])
        self.assertTrue(row["adjusted_for_corporate_actions"])
        self.assertFalse(row["actual_entry_fill_proven"])
        self.assertEqual(row["adjusted_exit_close"], 110)
        self.assertEqual(row["raw_quote_sha256"], sha(canonical_bytes(source)))

    def test_missing_price_never_imputed(self):
        row, _ = one_complement("SSE:600001", SESSIONS,
                                [bar(SESSIONS[0], "3")],
                                [bar(SESSIONS[0], "2")])
        self.assertEqual(row["source_status"], "MISSING_FIXED_ENDPOINT")
        self.assertIsNone(row["adjusted_exit_close"])

    def test_st_entry_does_not_count_as_tradeable(self):
        raw = [bar(SESSIONS[0], "3"), bar(SESSIONS[-1], "3")]
        raw[0]["isST"] = "1"
        row, _ = one_complement("SSE:600001", SESSIONS, raw,
                                [bar(SESSIONS[0], "2"), bar(SESSIONS[-1], "2")])
        self.assertFalse(row["entry_tradeable"])
        self.assertFalse(row["adjusted_for_corporate_actions"])

    def test_maturity_guard_before_opening_parent_file(self):
        with tempfile.TemporaryDirectory() as t:
            with self.assertRaisesRegex(ValueError, "FUTURE_OUTCOME_EMBARGO"):
                read_parent(Path(t), datetime(2026, 11, 2, 9, tzinfo=timezone.utc))

    def test_later_vintage_fails_before_vendor_login(self):
        parent = {"capture_timestamp": "2026-11-27T21:25:00+08:00"}
        with patch("v29_growth_310_complement_capture.read_parent",
                   return_value=(parent, SESSIONS, b"raw")), \
             patch("v29_growth_310_complement_capture.load_fixed",
                   return_value=({}, [], set(), [])):
            with self.assertRaisesRegex(ValueError, "SAME_EXIT_CAPTURE_DAY"):
                capture(object(), root="/tmp",
                        now=datetime(2026, 11, 30, 14, tzinfo=timezone.utc))

    def test_only_188_quotes_requested_and_122_reused(self):
        ids = [f"SSE:{600001+i:06}" for i in range(310)]
        selected = set(ids[:122])
        complement = ids[122:]
        parent = {
            "capture_timestamp": "2026-11-27T21:25:00+08:00",
            "protocol_sha256": "a" * 64,
            "securities": [
                {"canonical_security_id": sid,
                 "entry_tradeable_at_reference_close": True,
                 "exit_tradeable_at_reference_close": True,
                 "corporate_actions_and_dividends_adjusted": True,
                 "adjusted_entry_close": 100,
                 "adjusted_exit_close": 110,
                 "raw_quote_sha256": "b" * 64}
                for sid in ids[:122]]
        }

        class FakeVendor:
            def __init__(self):
                self.calls = 0

            def login(self):
                return type("Login", (), {"error_code": "0"})()

            def logout(self):
                return None

            def query_history_k_data_plus(self, *args, **kwargs):
                self.calls += 1
                return []

        def fake_one(sid, sessions, raw, adj):
            return (
                {"security_id": sid, "entry_tradeable": False, "exit_tradeable": False,
                 "adjusted_for_corporate_actions": False, "adjusted_entry_close": None,
                 "adjusted_exit_close": None, "raw_quote_sha256": "c" * 64},
                {"security_id": sid, "raw_unadjusted": [], "forward_adjusted": []},
            )

        def fake_evaluate(*args, **kwargs):
            return {"status": "INSUFFICIENT_NEVER_DROP_NAMES",
                    "selected_computable": 122, "comparator_computable": 0,
                    "strategy_validated": False, "live_buy_eligibility": "NOT_AUTHORIZED"}

        vendor = FakeVendor()
        with patch("v29_growth_310_complement_capture.read_parent",
                   return_value=(parent, SESSIONS, b"original")), \
             patch("v29_growth_310_complement_capture.load_fixed",
                   return_value=({}, ids, selected, complement)), \
             patch("v29_growth_310_complement_capture.records", side_effect=lambda x: x), \
             patch("v29_growth_310_complement_capture.one_complement",
                   side_effect=fake_one), \
             patch("v29_growth_310_complement_capture.evaluate",
                   side_effect=fake_evaluate):
            observation, result, raw = capture(vendor, root="/tmp", now=SAME_DAY)

        self.assertEqual(vendor.calls, 376)
        self.assertEqual(len(observation["securities"]), 310)
        self.assertEqual(sum(r["entry_tradeable"] for r in observation["securities"]), 122)
        self.assertEqual(sha(raw), observation["raw_sources_sha256"])
        self.assertEqual(result["status"], "INSUFFICIENT_NEVER_DROP_NAMES")

    def test_save_does_not_overwrite_existing_result(self):
        with tempfile.TemporaryDirectory() as t:
            with self.assertRaisesRegex(ValueError, "DO_NOT_OVERWRITE"):
                save(Path(t), {}, {}, b"")


if __name__ == "__main__":
    unittest.main()
