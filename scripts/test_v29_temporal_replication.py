"""No live price data: synthetic-only second temporal period end-to-end tests."""
import gzip
import hashlib
import json
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import v29_temporal_replication as t

ENTRY_NOW=datetime(2026,11,30,20,0,tzinfo=t.TZ)
EXIT_NOW=datetime(2026,12,25,20,0,tzinfo=t.TZ)

def fake_index(start,end):
    data=[{"indexCode":"H00300","tradeDate":"20261130","close":"6000"}]
    if end=="2026-12-25":
        data.append({"indexCode":"H00300","tradeDate":"20261225","close":"6300"})
    return json.dumps({"data":data}).encode()

class Result:
    error_code="0"
    error_msg=""
    def __init__(self,fields,rows):
        self.fields=fields.split(",")
        self.rows=rows
        self.position=0
    def next(self):
        self.position+=1
        return self.position<=len(self.rows)
    def get_row_data(self):
        return [str(self.rows[self.position-1].get(field,"")) for field in self.fields]

class Source:
    def __init__(self,missing=None,st_exit=None):
        self.calls=[]
        self.missing=missing
        self.st_exit=st_exit
    def login(self):
        self.calls.append("login")
        return Result("date",[])
    def logout(self):
        self.calls.append("logout")
    def query_trade_dates(self,start_date,end_date):
        self.calls.append(("calendar",start_date,end_date))
        d=date.fromisoformat(start_date)
        last=date.fromisoformat(end_date)
        rows=[]
        while d<=last:
            rows.append({"calendar_date":d.isoformat(),"is_trading_day":"1" if d.weekday()<5 else "0"})
            d+=timedelta(days=1)
        return Result("calendar_date,is_trading_day",rows)
    def query_history_k_data_plus(self,code,fields,start_date,end_date,frequency,adjustflag):
        self.calls.append(("quote",code,start_date,end_date,adjustflag))
        if (code==self.missing and adjustflag=="2"):
            return Result(fields,[])
        if start_date!="2026-11-30" or end_date not in ("2026-11-30","2026-12-25"):
            raise AssertionError("CHANGED_SECOND_SESSION")
        points=[]
        d=date.fromisoformat(start_date)
        end=date.fromisoformat(end_date)
        while d<=end:
            if d.weekday()<5:
                last=d==date(2026,12,25)
                px=("120" if adjustflag=="2" else "110") if last else "100"
                points.append({"date":d.isoformat(),"code":code,"adjustflag":adjustflag,
                    "close":px,"volume":"1000","amount":"100000","tradestatus":"1",
                    "isST":"1" if last and code==self.st_exit else "0",
                    "open":"100","high":"120","low":"90","preclose":"100","pctChg":"0"})
            d+=timedelta(days=1)
        return Result(fields,points)

class TestSecondEpisode(unittest.TestCase):
    def test_contract_is_frozen_and_distinct_from_new_issuer_cohort(self):
        plan,ids,protocol_sha,source_sha=t.sources()
        self.assertEqual(len(ids),122)
        self.assertEqual(plan["temporal_replication"]["planned_entry_session"],"2026-11-30")
        self.assertEqual(plan["temporal_replication"]["planned_twentieth_session"],"2026-12-25")
        self.assertFalse(plan["evidence_interpretation"]["independent_security_cohort"])
        self.assertEqual(len(protocol_sha),64)
        self.assertEqual(len(source_sha),64)

    def test_gate_rejects_early_or_later_reconstruction_before_vendor_calls(self):
        for phase,when in [
            ("entry",datetime(2026,11,30,15,tzinfo=t.TZ)),
            ("entry",datetime(2026,12,1,20,tzinfo=t.TZ)),
            ("outcome",datetime(2026,12,24,20,tzinfo=t.TZ)),
            ("outcome",datetime(2026,12,26,20,tzinfo=t.TZ)),
        ]:
            with self.assertRaisesRegex(ValueError,"ONLY_DECLARED_SAME_DAY_AFTER_CLOSE_CAPTURE"):
                t.gate(phase,when)

    def test_full_second_period_handoff_and_eight_comparison(self):
        entry,raw=t.capture_entry(Source(),ENTRY_NOW,fake_index)
        self.assertEqual(entry["source_complete"],122)
        self.assertEqual(entry["status"],"COMPLETE_122_AND_H00300")
        self.assertEqual(entry["benchmark"]["entry_close"],6000)
        self.assertFalse(entry["actual_fills_proven"])
        with tempfile.TemporaryDirectory() as root:
            out=Path(root)/"replicate-entry"
            t.write(out,"entry",entry,raw)
            with patch.object(t,"ENTRY",out/"ENTRY_SNAPSHOT_122.json"), \\
                 patch.object(t,"ENTRY_RAW",out/"RAW_ENTRY_122.json.gz"):
                report,exit_raw=t.capture_outcome(Source(),EXIT_NOW,fake_index)
            self.assertEqual(report["status"],"ONE_MORE_NONOVERLAPPING_EPISODE_DESCRIPTIVE_ONLY")
            self.assertEqual(report["price_eligible"],122)
            self.assertEqual(len(report["sessions"]),20)
            self.assertEqual(report["sessions"][0],"2026-11-30")
            self.assertEqual(report["sessions"][-1],"2026-12-25")
            self.assertAlmostEqual(report["metrics"]["equal_122_mean_net"],.197)
            self.assertAlmostEqual(report["metrics"]["benchmark_total_return"],.05)
            self.assertAlmostEqual(report["metrics"]["mean_net_excess_vs_H00300"],.147)
            self.assertAlmostEqual(report["metrics"]["eight_minus_122"],0)
            self.assertFalse(report["independent_company_cohort"])
            self.assertFalse(report["strategy_validated"])
            t.write(Path(root)/"replicate-exit","outcome",report,exit_raw)
            self.assertEqual(hashlib.sha256(gzip.decompress(
                (Path(root)/"replicate-exit/RAW_OUTCOME_122.json.gz").read_bytes())).hexdigest(),
                report["raw_sha256"])

    def test_one_missing_quote_remains_explicitly_incomplete(self):
        _,ids,_,_=t.sources()
        sid=ids[0]
        entry,raw=t.capture_entry(Source(missing=t.baostock_code(sid)),ENTRY_NOW,fake_index)
        self.assertEqual(entry["source_complete"],121)
        self.assertEqual(entry["status"],"INCOMPLETE_NO_SUBSTITUTION")
        self.assertEqual(len(entry["rows"]),122)
        self.assertFalse(entry["rows"][0]["source_complete"])

    def test_exit_st_with_trades_keeps_negative_or_positive_observation(self):
        entry,raw=t.capture_entry(Source(),ENTRY_NOW,fake_index)
        _,ids,_,_=t.sources()
        with tempfile.TemporaryDirectory() as root:
            out=Path(root)/"entry"
            t.write(out,"entry",entry,raw)
            with patch.object(t,"ENTRY",out/"ENTRY_SNAPSHOT_122.json"), \\
                 patch.object(t,"ENTRY_RAW",out/"RAW_ENTRY_122.json.gz"):
                report,_=t.capture_outcome(Source(st_exit=t.baostock_code(ids[0])),EXIT_NOW,fake_index)
        self.assertEqual(report["price_eligible"],122)
        self.assertTrue(report["rows"][0]["exit_ST_flag"])
        self.assertFalse(report["rows"][0]["actual_exit_fill_proven"])

    def test_official_price_index_substitution_rejected(self):
        bad=json.loads(fake_index("2026-11-30","2026-12-25"))
        bad["data"][-1]["indexCode"]="000300"
        with self.assertRaisesRegex(ValueError,"PRICE_INDEX_CANNOT_SUBSTITUTE_H00300"):
            t.read_index(json.dumps(bad).encode(),"2026-11-30","2026-12-25",6000)
        with self.assertRaisesRegex(ValueError,"H00300_FROZEN_SECOND_ENTRY_VINTAGE_DRIFT"):
            t.read_index(fake_index("2026-11-30","2026-12-25"),
                         "2026-11-30","2026-12-25",6001)

    def test_missing_calendar_session_does_not_slide_exit(self):
        plan,_,_,_=t.sources()
        src=Source()
        calendar=t.records(src.query_trade_dates(start_date="2026-11-30",end_date="2026-12-25"))
        calendar=[r for r in calendar if r["calendar_date"]!="2026-12-16"]
        with self.assertRaisesRegex(ValueError,"SECOND_EPISODE_EXCHANGE_CALENDAR_NOT_VERIFIED"):
            t.sessions_for("outcome",calendar,plan)

if __name__=="__main__":
    unittest.main()
