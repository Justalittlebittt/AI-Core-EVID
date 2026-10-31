"""Full prospective 122-name entry -> sealed bytes -> exit -> evaluator integration.

EVERY future quote and return here is SYNTHETIC. No future live queries.
Tests the actual handoff boundary across the two separate scheduled workflows.
"""
import gzip
import hashlib
import json
import sys
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import v29_forward122_entry_close_capture as entry
import v29_forward122_20th_session_exit_capture as exit_
from test_v29_forward122_entry_close_capture import (
    FakeBaoStock, AFTER as ENTRY_AFTER, index_bytes,
)
from test_v29_forward122_20th_session_exit_capture import (
    FakeBS, FakeResult, AFTER as EXIT_AFTER, fake_index, trading_calendar,
)


class ContinuityExitBaoStock(FakeBS):
    """Produce future-vintage prices compatible with sealed Nov 2 original."""
    def query_history_k_data_plus(self, code, fields, **kw):
        result = super().query_history_k_data_plus(code, fields, **kw)
        for row in result.rows:
            row["close"] = ("30.24" if row["date"] == "2026-11-02"
                            else "36.288")
        return result


class StaleCalendarExitBaoStock(ContinuityExitBaoStock):
    def query_trade_dates(self, **kw):
        rows = [x for x in trading_calendar()
                if x["calendar_date"] != "2026-11-16"]
        rows += [
            {"calendar_date": "2026-11-28", "is_trading_day": "0"},
            {"calendar_date": "2026-11-29", "is_trading_day": "0"},
            {"calendar_date": "2026-11-30", "is_trading_day": "1"},
        ]
        return FakeResult("calendar_date,is_trading_day", rows)


class SealedFuturePipelineE2ETests(unittest.TestCase):
    def entry_snapshot(self, root):
        mock = FakeBaoStock()
        mock.testcase = self
        report, raw = entry.capture(mock, lambda: index_bytes(), now=ENTRY_AFTER)
        self.assertEqual(report["source_quote_complete_count"], 122)
        self.assertEqual(report["benchmark"]["status"],
                         "OFFICIAL_H00300_ENTRY_BAR_VERIFIED")
        folder = root / "entry"
        entry.write(folder, report, raw)
        self.assertEqual(
            gzip.decompress((folder/"RAW_ENTRY_QUOTE_CALENDAR_AND_INDEX.json.gz").read_bytes()),
            raw)
        self.assertEqual(hashlib.sha256(raw).hexdigest(), report["raw_source_bytes_sha256"])
        return folder, report

    def test_real_handoff_from_sealed_entry_to_20th_exit_122_rows(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            folder, first = self.entry_snapshot(root)
            with patch.object(exit_, "ENTRY", folder/"ENTRY_SNAPSHOT_122.json"), \
                 patch.object(exit_, "ENTRY_RAW", folder/"RAW_ENTRY_QUOTE_CALENDAR_AND_INDEX.json.gz"):
                _, ids, _, entry_sha, frozen, archive = exit_.load_entry()
                self.assertEqual(len(ids), 122)
                self.assertEqual([x["security_id"] for x in archive["quotes"]], ids)
                self.assertEqual(entry_sha, hashlib.sha256(
                    (folder/"ENTRY_SNAPSHOT_122.json").read_bytes()).hexdigest())
                source = ContinuityExitBaoStock()
                report, outcome, raw = exit_.capture(
                    source, now=EXIT_AFTER,
                    official_fetch=lambda date_of_exit: fake_index())
                self.assertEqual(report["fixed_entry_session"], "2026-11-02")
                self.assertEqual(report["fixed_exit_session"], "2026-11-27")
                self.assertEqual(report["quote_source_eligible_count"], 122)
                self.assertEqual(report["benchmark_source_status"],
                                 "OFFICIAL_H00300_ENTRY_AND_EXIT_VERIFIED")
                self.assertEqual(report["outcome_evaluation"]["status"],
                                 "ONE_EPISODE_DESCRIPTIVE_NOT_BUY_EVIDENCE")
                self.assertAlmostEqual(
                    report["outcome_evaluation"]["mean_net_excess"],
                    36.288/30.24 - 1 - .003 - (6110.30/6010.30 - 1),
                    places=12)
                self.assertEqual(len(outcome["verified_exchange_sessions"]), 20)
                self.assertEqual(len(outcome["securities"]), 122)
                self.assertFalse(report["trade_authorized"])
                self.assertEqual(report["live_buy_eligibility"], "NOT_AUTHORIZED")
                destination = root/"exit"
                exit_.save(destination, report, outcome, raw)
                self.assertEqual(
                    gzip.decompress(
                        (destination/"RAW_VENDOR_STOCK_AND_H00300_INDEX.json.gz").read_bytes()),
                    raw)
                self.assertEqual(hashlib.sha256(raw).hexdigest(), report["source_bytes_sha256"])

    def test_tampered_sealed_entry_prevents_any_exit_quote_query(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            folder,_=self.entry_snapshot(root)
            raw_path=folder/"RAW_ENTRY_QUOTE_CALENDAR_AND_INDEX.json.gz"
            prior=gzip.decompress(raw_path.read_bytes())
            altered=prior.replace(b"30.24",b"30.25",1)
            self.assertNotEqual(altered,prior)
            raw_path.write_bytes(gzip.compress(altered,mtime=0))
            with patch.object(exit_, "ENTRY", folder/"ENTRY_SNAPSHOT_122.json"), \
                 patch.object(exit_, "ENTRY_RAW", raw_path):
                bs=ContinuityExitBaoStock()
                with self.assertRaisesRegex(ValueError,"SEALED_ENTRY_DATA_OR_IDENTITY_CHANGED"):
                    exit_.capture(bs,now=EXIT_AFTER,
                                  official_fetch=lambda d:fake_index())
                self.assertEqual(bs.calls, [])

    def test_missing_one_november_trading_calendar_day_never_shifts_exit(self):
        with tempfile.TemporaryDirectory() as td:
            folder,_=self.entry_snapshot(Path(td))
            with patch.object(exit_, "ENTRY", folder/"ENTRY_SNAPSHOT_122.json"), \
                 patch.object(exit_, "ENTRY_RAW", folder/"RAW_ENTRY_QUOTE_CALENDAR_AND_INDEX.json.gz"):
                bs=StaleCalendarExitBaoStock()
                with self.assertRaisesRegex(
                    ValueError, "NOVEMBER_EXCHANGE_CALENDAR_HAS_MISSING_DATES"
                ):
                    exit_.capture(
                        bs,now=datetime(2026,11,30,20,0,tzinfo=entry.LOCAL),
                        official_fetch=lambda d:fake_index())
                self.assertFalse(any(c[0]=="bar" for c in bs.calls))

if __name__=="__main__":
    unittest.main()
