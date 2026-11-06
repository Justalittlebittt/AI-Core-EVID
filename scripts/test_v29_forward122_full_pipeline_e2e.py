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
    def test_actual_sealed_20261102_entry_is_accepted_by_future_exit_loader(self):
        # Use real PRE-OUTCOME archived 122-stock entry, not synthetic returns.
        _, ids, _, digest, actual, provenance = exit_.load_entry()
        self.assertEqual(len(ids), 122)
        self.assertEqual(len(provenance["quotes"]), 122)
        self.assertEqual(actual["entry_session"], "2026-11-02")
        self.assertEqual(actual["source_quote_complete_count"], 122)
        self.assertEqual(actual["benchmark"]["security_id"], "H00300.CSI")
        self.assertEqual(actual["benchmark"]["entry_total_return_index_close"], 6048.45)
        self.assertEqual(actual["market_source_information_status"],
                         "COMPLETE_QUOTES_AND_OFFICIAL_TR")
        self.assertEqual(actual["raw_source_bytes_sha256"], hashlib.sha256(
            gzip.decompress(exit_.ENTRY_RAW.read_bytes())).hexdigest())
        self.assertEqual(digest, hashlib.sha256(exit_.ENTRY.read_bytes()).hexdigest())
        self.assertEqual([r["security_id"] for r in actual["rows"]], ids)
        # Ensure the pre-close eight-name exploratory subset really maps onto
        # the same sealed 122 entry bars, without looking at future returns.
        from v29_eight_pilot_outcome import PILOT
        eight=json.loads(PILOT.read_text(encoding="utf-8"))
        chosen=eight["pre_outcome_rule"]["selected_ids_in_rank_order"]
        self.assertEqual(len(chosen),8)
        by_id={r["security_id"]:r for r in actual["rows"]}
        self.assertEqual(len(set(chosen)),8)
        self.assertTrue(set(chosen).issubset(set(ids)))
        self.assertTrue(all(by_id[sid]["source_bar_pair_complete"] for sid in chosen))
        self.assertAlmostEqual(sum(100*by_id[sid]["entry_unadjusted"]["close"]
                                   for sid in chosen),54558)

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

    def test_full_post_maturity_handoff_to_122_eight_and_310_readable_decision(self):
        """Full generated data packets through final reader brief: synthetic exits only."""
        from v29_forward_maturity_decision_brief import brief
        from v29_eight_pilot_outcome import evaluate as evaluate_eight
        from v29_growth_310_conditional_result import evaluate as evaluate_control, load_fixed
        with tempfile.TemporaryDirectory() as td:
            folder,_=self.entry_snapshot(Path(td))
            with (patch.object(exit_, "ENTRY", folder/"ENTRY_SNAPSHOT_122.json"),
                  patch.object(exit_, "ENTRY_RAW", folder/"RAW_ENTRY_QUOTE_CALENDAR_AND_INDEX.json.gz")):
                verdict,outcome,raw=exit_.capture(
                    ContinuityExitBaoStock(),now=EXIT_AFTER,
                    official_fetch=lambda d:fake_index())
            self.assertEqual(verdict["outcome_evaluation"]["status"],
                             "ONE_EPISODE_DESCRIPTIVE_NOT_BUY_EVIDENCE")
            eight=evaluate_eight(outcome,now=EXIT_AFTER)
            _,ids,selected,_=load_fixed()
            frozen={r["canonical_security_id"]:r for r in outcome["securities"]}
            prices=[]
            for sid in ids:
                if sid in selected:
                    p=frozen[sid]
                    prices.append({
                        "security_id":sid,"entry_tradeable":p["entry_tradeable_at_reference_close"],
                        "exit_tradeable":p["exit_tradeable_at_reference_close"],
                        "adjusted_for_corporate_actions":p["corporate_actions_and_dividends_adjusted"],
                        "adjusted_entry_close":p["adjusted_entry_close"],
                        "adjusted_exit_close":p["adjusted_exit_close"],
                        "raw_quote_sha256":p["raw_quote_sha256"],
                        "source_status":"SYNTHETIC_122_E2E_REUSED"})
                else:
                    prices.append({
                        "security_id":sid,"entry_tradeable":True,
                        "exit_tradeable":True,"adjusted_for_corporate_actions":True,
                        "adjusted_entry_close":100.0,"adjusted_exit_close":105.0,
                        "raw_quote_sha256":"a"*64,"source_status":"SYNTHETIC_188_E2E"})
            observation={
                "schema":"V29_310_SAME_VINTAGE_CLOSE_PROXIES_V1",
                "entry_session":"2026-11-02","exit_session":"2026-11-27",
                "vendor":"BAOSTOCK",
                "adjustment":"FORWARD_ADJUSTED_SAME_EXIT_CAPTURE_VINTAGE",
                "captured_at":EXIT_AFTER.isoformat(),
                "raw_sources_sha256":"a"*64,"securities":prices}
            control=evaluate_control(observation,outcome,now=EXIT_AFTER)
            self.assertEqual(control["status"],
                             "ONE_EPISODE_DESCRIPTIVE_NOT_BUY_EVIDENCE")
            rendered=brief(verdict,outcome,eight=eight,control=control,
                           control_prices=observation,now=EXIT_AFTER)
            self.assertIn("原始 122 股策略",rendered)
            self.assertIn("冻结 8 股精选",rendered)
            self.assertIn("310 股条件对照",rendered)
            self.assertIn("资金加权",rendered)
            self.assertIn("122 股减原始未入选 188 股",rendered)
            self.assertIn("NO ACTION",rendered)
            self.assertNotIn("尚未提供或尚未落盘",rendered)
            self.assertEqual(eight["live_buy_eligibility"],"NOT_AUTHORIZED")
            self.assertEqual(control["live_buy_eligibility"],"NOT_AUTHORIZED")

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
