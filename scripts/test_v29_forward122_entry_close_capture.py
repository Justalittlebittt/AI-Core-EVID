"""Pure synthetic tests for the unobserved November 2026 entry-close snapshot.

All date/price fixtures are invented and MUST NEVER be represented as real
future quote evidence. Check 122/122 cardinality and strict time/source gates.
"""
import copy
import gzip
import hashlib
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0,str(Path(__file__).resolve().parent))
from v29_forward122_entry_close_capture import (
    ENTRY_DAY, INDEX, SCHEMA, baostock_code, capture, fixed_sources,
    parse_index, ready_to_query, validate_bars, verify_calendar, write,
)

CHINA=ZoneInfo("Asia/Shanghai")
BEFORE=datetime(2026,11,2,14,30,tzinfo=CHINA)
AFTER=datetime(2026,11,2,20,0,tzinfo=CHINA)

def index_bytes():
    return json.dumps({"code":"200","msg":"Success","data":[
        {"indexCode":"H00300","tradeDate":"20261030","close":"6001.14"},
        {"indexCode":"H00300","tradeDate":"20261102","close":"6010.30"},
    ]},ensure_ascii=False).encode()

def calendar():
    return [
        {"calendar_date":"2026-10-31","is_trading_day":"0"},
        {"calendar_date":"2026-11-01","is_trading_day":"0"},
        {"calendar_date":"2026-11-02","is_trading_day":"1"},
    ]

class FakeResult:
    error_code="0"
    error_msg=""
    def __init__(self,fields,rows):
        self.fields=fields.split(",")
        self.rows=rows
        self.i=0
    def next(self):
        self.i+=1
        return self.i<=len(self.rows)
    def get_row_data(self):
        return [str(self.rows[self.i-1].get(f,"")) for f in self.fields]

class FakeBaoStock:
    def __init__(self,missing=None,st=None):
        self.calls=[]
        self.missing=missing
        self.st=st
    def login(self):
        self.calls.append(("login",))
        return FakeResult("date",[])
    def logout(self):
        self.calls.append(("logout",))
    def query_trade_dates(self,**kwargs):
        self.calls.append(("calendar",kwargs))
        self.testcase.assertEqual(kwargs,{"start_date":"2026-10-31","end_date":"2026-11-02"})
        return FakeResult("calendar_date,is_trading_day",calendar())
    def query_history_k_data_plus(self,code,fields,**kwargs):
        self.calls.append(("quote",code,kwargs))
        self.testcase.assertEqual(kwargs["start_date"],"2026-11-02")
        self.testcase.assertEqual(kwargs["end_date"],"2026-11-02")
        self.testcase.assertEqual(kwargs["frequency"],"d")
        if code==self.missing and kwargs["adjustflag"]=="3":
            return FakeResult(fields,[])
        row={"date":"2026-11-02","code":code,"close":"30.24",
             "adjustflag":kwargs["adjustflag"],"tradestatus":"1",
             "isST":"1" if code==self.st else "0",
             "volume":"123456","amount":"246000","open":"30.10",
             "high":"30.5","low":"29.9","preclose":"30.00","pctChg":"0.8"}
        return FakeResult(fields,[row])

class EntryCloseCaptureTests(unittest.TestCase):
    def provider(self,**kwargs):
        bs=FakeBaoStock(**kwargs)
        bs.testcase=self
        return bs

    def test_frozen_reference_identities_and_declared_entry(self):
        spec,ids,p,priorhash,prior=fixed_sources()
        self.assertEqual(len(ids),122)
        self.assertEqual(prior["stock_reference_bar_both_versions_ok"],122)
        self.assertEqual(prior["benchmark"]["reference_close"],6001.14)
        self.assertEqual(spec["baseline"]["id"],INDEX)
        self.assertEqual(str(ENTRY_DAY),"2026-11-02")

    def test_time_lock_rejects_weekend_or_open_session_before_vendor_calls(self):
        for instant in (datetime(2026,10,31,10,tzinfo=CHINA),
                        BEFORE,
                        datetime(2026,11,2,16,29,tzinfo=CHINA)):
            with self.assertRaisesRegex(ValueError,"ENTRY_CLOSE_NOT_YET_OBSERVABLE"):
                capture(self.provider(),lambda:index_bytes(),now=instant)
        with self.assertRaisesRegex(ValueError,"AWARE_CAPTURE_CLOCK_REQUIRED"):
            ready_to_query(datetime(2026,11,2,18,0))
        self.assertEqual(ready_to_query(AFTER).date(),ENTRY_DAY)

    def test_late_manual_run_after_registered_entry_window_rejected_before_vendor_login(self):
        bs=self.provider()
        with self.assertRaisesRegex(ValueError,"ENTRY_CAPTURE_WINDOW_EXPIRED"):
            capture(bs,lambda:index_bytes(),now=datetime(2026,11,5,0,0,tzinfo=CHINA))
        self.assertEqual(bs.calls,[])

    def test_official_exchange_date_cannot_be_shifted_to_november_three(self):
        self.assertEqual(verify_calendar(calendar()),"2026-11-02")
        bad=calendar()
        bad[-1]["is_trading_day"]="0"
        with self.assertRaisesRegex(ValueError,"FIRST_TRADING_DAY_NOT_OFFICIALLY_CONFIRMED"):
            verify_calendar(bad)
        nextday=calendar()+[{"calendar_date":"2026-11-03","is_trading_day":"1"}]
        with self.assertRaisesRegex(ValueError,"UNEXPECTED_CALENDAR"):
            verify_calendar(nextday)

    def test_index_requires_actual_official_H00300_both_dates_and_same_prior(self):
        v=parse_index(index_bytes(),6001.14)
        self.assertEqual(v["entry_total_return_index_close"],6010.30)
        self.assertEqual(v["source_sha256"],hashlib.sha256(index_bytes()).hexdigest())
        wrong=json.loads(index_bytes())
        wrong["data"][1]["indexCode"]="000300"
        with self.assertRaisesRegex(ValueError,"CSI300_PRICE_INDEX_SUBSTITUTION_REJECTED"):
            parse_index(json.dumps(wrong).encode(),6001.14)
        with self.assertRaisesRegex(ValueError,"PRIOR_FROZEN_INDEX_CLOSE_REVISED_OR_WRONG_SOURCE"):
            parse_index(index_bytes(),6001.13)
        wrong=json.loads(index_bytes())
        wrong["data"][1]["tradeDate"]="20261103"
        with self.assertRaisesRegex(ValueError,"BENCHMARK_DATE_OUTSIDE_ALLOWED_WINDOW"):
            parse_index(json.dumps(wrong).encode(),6001.14)

    def test_st_suspension_and_missing_are_all_fail_closed_without_filling_prices(self):
        code="sz.300519"
        rec={"code":code,"date":"2026-11-02","adjustflag":"3",
             "close":"9.5","tradestatus":"1","isST":"0","volume":"100"}
        adj={**rec,"adjustflag":"2"}
        good=validate_bars("SZSE:300519",[rec],[adj])
        self.assertTrue(good["source_bar_pair_complete"])
        self.assertFalse(good["paper_entry_executability_verified"])
        self.assertFalse(good["limit_up_down_trade_fill_verified"])
        for key,val in [("isST","1"),("isST",""),("tradestatus","0"),
                        ("volume","0"),("close","")]:
            bad={**rec,key:val}
            out=validate_bars("SZSE:300519",[bad],[adj])
            self.assertFalse(out["source_bar_pair_complete"])
        self.assertFalse(validate_bars("SZSE:300519",[],[adj])["source_bar_pair_complete"])
        self.assertFalse(validate_bars("SZSE:300519",[{**rec,"date":"2026-11-03"}],[adj])["source_bar_pair_complete"])

    def test_complete_122_deterministic_raw_and_index_not_an_outcome(self):
        bs=self.provider()
        report,raw=capture(bs,lambda:index_bytes(),now=AFTER)
        self.assertEqual(report["schema"],SCHEMA)
        self.assertEqual(report["actual_rows_count"],122)
        self.assertEqual(report["source_quote_complete_count"],122)
        self.assertEqual(report["source_quote_incomplete_count"],0)
        self.assertEqual(report["benchmark"]["status"],"OFFICIAL_H00300_ENTRY_BAR_VERIFIED")
        self.assertEqual(len([x for x in bs.calls if x[0]=="quote"]),244)
        self.assertTrue(all(x[2]["start_date"]=="2026-11-02" and x[2]["end_date"]=="2026-11-02"
                            for x in bs.calls if x[0]=="quote"))
        self.assertFalse(report["future_return_or_twentieth_session_exit_read"])
        self.assertFalse(report["future_outcome_strategy_performance_computed"])
        self.assertFalse(report["all_122_actual_buy_fills_certified"])
        self.assertEqual(report["live_buy_eligibility"],"NOT_AUTHORIZED")
        self.assertEqual(hashlib.sha256(raw).hexdigest(),report["raw_source_bytes_sha256"])
        self.assertEqual(len(json.loads(raw)["quotes"]),122)
        with tempfile.TemporaryDirectory() as tmp:
            location=Path(tmp)/"snapshot"
            write(location,report,raw)
            restored=gzip.decompress((location/"RAW_ENTRY_QUOTE_CALENDAR_AND_INDEX.json.gz").read_bytes())
            self.assertEqual(restored,raw)
            self.assertEqual(json.loads((location/"ENTRY_SNAPSHOT_122.json").read_text())["actual_rows_count"],122)
            with self.assertRaisesRegex(ValueError,"DO_NOT_OVERWRITE"):
                write(location,report,raw)

    def test_missing_bar_retains_all_122_names_and_incomplete_status(self):
        spec,ids,_,_,_=fixed_sources()
        bs=self.provider(missing=baostock_code(ids[4]),st=baostock_code(ids[5]))
        report,raw=capture(bs,lambda:index_bytes(),now=AFTER)
        self.assertEqual(len(report["rows"]),122)
        self.assertEqual([r["security_id"] for r in report["rows"]],ids)
        self.assertEqual(report["source_quote_complete_count"],120)
        self.assertEqual(report["source_quote_incomplete_count"],2)
        self.assertEqual(report["rows"][4]["entry_unadjusted"]["status"],"ENTRY_BAR_MISSING")
        self.assertEqual(report["rows"][5]["entry_unadjusted"]["status"],"ENTRY_DAY_ST_FLAG")
        self.assertEqual(report["market_source_information_status"],
                         "INCOMPLETE_NO_SUBSTITUTION_OR_ENTRY_SHIFT")

    def test_official_source_failure_preserves_all_quote_records_but_blocks_result(self):
        report,raw=capture(self.provider(),lambda:b"<html>provider offline</html>",now=AFTER)
        self.assertEqual(report["source_quote_complete_count"],122)
        self.assertEqual(report["benchmark"]["status"],"OFFICIAL_H00300_ENTRY_SOURCE_UNVERIFIED")
        self.assertIsNone(report["benchmark"]["entry_total_return_index_close"])
        self.assertEqual(report["market_source_information_status"],
                         "INCOMPLETE_NO_SUBSTITUTION_OR_ENTRY_SHIFT")
        self.assertFalse(report["future_outcome_strategy_performance_computed"])

if __name__=="__main__":
    unittest.main()
