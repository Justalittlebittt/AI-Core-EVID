"""Synthetic-only safety and determinism tests for Nov-2026 122-name maturity.

Fake 2026-11-27 returns below are PROGRAM TEST VALUES, not real market data.
"""
import copy
import gzip
import hashlib
import json
import sys
import tempfile
import unittest
from datetime import date,datetime,timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0,str(Path(__file__).resolve().parent))
from v29_growth_forward_cohort import load_registered
from v29_forward122_preentry_source_check import FIELDS,baostock_code
from v29_forward122_20th_session_exit_capture import (
    ENTRY_DAY,EARLIEST_PLAUSIBLE_EXIT,LOCAL,SCHEMA,
    after_maturity_gate,trading_sessions,require_20th_close,
    index_result,one_issuer,capture,save,
)

AFTER=datetime(2026,11,27,20,0,tzinfo=LOCAL)
BEFORE=datetime(2026,11,27,14,0,tzinfo=LOCAL)

def days():
    d=ENTRY_DAY
    a=[]
    while len(a)<20:
        if d.weekday()<5:
            a.append(d)
        d+=timedelta(days=1)
    return [d.isoformat() for d in a]

def trading_calendar():
    start=ENTRY_DAY
    end=date.fromisoformat(days()[-1])
    arr=[]
    while start<=end:
        arr.append({"calendar_date":start.isoformat(),
                    "is_trading_day":"1" if start.weekday()<5 else "0"})
        start+=timedelta(days=1)
    return arr

def fake_index():
    return json.dumps({"data":[
        {"indexCode":"H00300","tradeDate":"20261102","close":"6010.30"},
        {"indexCode":"H00300","tradeDate":"20261127","close":"6110.30"},
    ]},ensure_ascii=False).encode()

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

class FakeBS:
    def __init__(self,missing=None, changed=None):
        self.calls=[]
        self.missing=missing
        self.changed=changed
    def login(self):
        self.calls.append(("login",))
        return FakeResult("date",[])
    def logout(self):
        self.calls.append(("logout",))
    def query_trade_dates(self,**kw):
        self.calls.append(("calendar",kw))
        if kw["end_date"]!="2026-11-27":
            raise AssertionError("must fetch only as-of 20th completed session")
        return FakeResult("calendar_date,is_trading_day",trading_calendar())
    def query_history_k_data_plus(self,code,fields,**kw):
        self.calls.append(("bar",code,kw))
        if kw["start_date"]!="2026-11-02" or kw["end_date"]!="2026-11-27":
            raise AssertionError("must query same fixed entry and 20th exit")
        points=[]
        for day in days():
            if (day==days()[-1] and kw["adjustflag"]=="2"
                    and code==self.missing):
                continue
            value=("100.01" if code==self.changed else "100.00") if day==days()[0] else (
                "120.0" if kw["adjustflag"]=="2" else "110.00")
            points.append({
                "date":day,"code":code,"adjustflag":kw["adjustflag"],"close":value,
                "volume":"1000","amount":"100000","tradestatus":"1",
                "isST":"0","open":"101","high":"120","low":"99",
                "preclose":"100","pctChg":"1",
            })
        return FakeResult(fields,points)

def synthetic_entry():
    spec,ids,p=load_registered()
    archive={"entry_date":"2026-11-02","quotes":[{
        "security_id":sid,
        "raw_unadjusted":[{"date":"2026-11-02","code":baostock_code(sid),
                           "adjustflag":"3","close":"100"}],
        "forward_adjusted":[],
    } for sid in ids]}
    entry={
        "entry_session":"2026-11-02",
        "benchmark":{
            "security_id":"H00300.CSI",
            "status":"OFFICIAL_H00300_ENTRY_BAR_VERIFIED",
            "entry_total_return_index_close":6010.30,
        },
    }
    return spec,ids,p,"f"*64,entry,archive

class Fixed20ExitTests(unittest.TestCase):
    def test_real_lock_20_weekday_sessions_ends_november27_but_needs_calendar(self):
        self.assertEqual(days()[0],"2026-11-02")
        self.assertEqual(days()[-1],"2026-11-27")
        self.assertEqual(trading_sessions(trading_calendar(),AFTER.date()),days())
        self.assertEqual(require_20th_close(days(),AFTER),date(2026,11,27))

    def test_pre_maturity_must_not_call_quotes(self):
        for x in (datetime(2026,10,31,12,tzinfo=LOCAL),BEFORE):
            with self.assertRaisesRegex(ValueError,"FROZEN_20TH_SESSION_MATURITY_NOT_YET_OBSERVABLE"):
                capture(FakeBS(),now=x,official_fetch=lambda _d:fake_index(),
                        entry_sources=synthetic_entry())
        with self.assertRaisesRegex(ValueError,"AWARE_MATURITY_CLOCK_REQUIRED"):
            after_maturity_gate(datetime(2026,11,27,20))

    def test_vendor_calendar_must_have_20_and_not_shift_entry_date(self):
        with self.assertRaisesRegex(ValueError,"FROZEN_20_SESSION_WINDOW_NOT_COMPLETE"):
            trading_sessions(trading_calendar()[:-1],AFTER.date())
        changed=trading_calendar()
        changed[0]["is_trading_day"]="0"
        with self.assertRaisesRegex(ValueError,"FROZEN_ENTRY_NOT_FIRST_OFFICIAL_SESSION"):
            trading_sessions(changed,AFTER.date())
        changed=trading_calendar()+[{"calendar_date":"2026-11-30","is_trading_day":"1"}]
        with self.assertRaisesRegex(ValueError,"OFFICIAL_SESSION_SOURCE_INVALID_OR_DUPLICATE"):
            trading_sessions(changed,AFTER.date())

    def test_actual_official_total_return_identity_and_prior_entry_level(self):
        out=index_result(fake_index(),"2026-11-27",6010.30)
        self.assertEqual(out["security_id"],"H00300.CSI")
        self.assertEqual(out["exit_total_return_index_close"],6110.30)
        wrong=json.loads(fake_index())
        wrong["data"][1]["indexCode"]="000300"
        with self.assertRaisesRegex(ValueError,"PRICE_INDEX_INSTEAD_OF_FROZEN_TOTAL_RETURN"):
            index_result(json.dumps(wrong).encode(),"2026-11-27",6010.30)
        with self.assertRaisesRegex(ValueError,"ORIGINAL_OFFICIAL_TOTAL_RETURN_ENTRY_PRICE_REVISED"):
            index_result(fake_index(),"2026-11-27",6001.14)

    def test_normalize_vendor_raw_close_string_without_allowing_actual_drift(self):
        sid="SSE:601965"
        source={"raw_unadjusted":[{"close":"100"}]}
        bars=[]
        for d in (days()[0],days()[-1]):
            bars.append({
                "date":d,"code":baostock_code(sid),"close":"100.00" if d==days()[0] else "110.0",
                "adjustflag":"3","tradestatus":"1","isST":"0","volume":"300"})
        adjusted=[{**r,"adjustflag":"2","close":"100" if i==0 else "120"}
                  for i,r in enumerate(bars)]
        outcome,_=one_issuer(sid,days(),source,bars,adjusted)
        self.assertTrue(outcome["price_comparison_eligible"])
        self.assertFalse(outcome["actual_entry_fill_proven"])
        self.assertEqual(outcome["adjusted_entry_close"],100)
        changed=copy.deepcopy(bars)
        changed[0]["close"]="100.01"
        outcome,_=one_issuer(sid,days(),source,changed,adjusted)
        self.assertEqual(outcome["observation_status"],
                         "FROZEN_UNADJUSTED_ENTRY_CLOSE_VINTAGE_DRIFT")
        self.assertFalse(outcome["price_comparison_eligible"])

    def test_fake_full_122_generates_research_only_evaluator_and_real_source_hashes(self):
        bs=FakeBS()
        report,outcome,raw=capture(bs,now=AFTER,official_fetch=lambda _d:fake_index(),
                                   entry_sources=synthetic_entry())
        self.assertEqual(report["schema"],SCHEMA)
        self.assertEqual(len(outcome["securities"]),122)
        self.assertEqual(report["fixed_exit_session"],"2026-11-27")
        self.assertEqual(report["quote_source_eligible_count"],122)
        self.assertEqual(report["benchmark_source_status"],
                         "OFFICIAL_H00300_ENTRY_AND_EXIT_VERIFIED")
        self.assertEqual(report["outcome_evaluation"]["status"],
                         "ONE_EPISODE_DESCRIPTIVE_NOT_BUY_EVIDENCE")
        self.assertFalse(report["outcome_evaluation"]["strategy_validated"])
        self.assertFalse(report["actual_entry_exit_fills_proven"])
        self.assertEqual(report["live_buy_eligibility"],"NOT_AUTHORIZED")
        self.assertEqual(len([x for x in bs.calls if x[0]=="bar"]),244)
        self.assertTrue(all(x[2]["end_date"]=="2026-11-27"
                            for x in bs.calls if x[0]=="bar"))
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/"outcomes"
            save(path,report,outcome,raw)
            recovered=gzip.decompress((path/"RAW_VENDOR_STOCK_AND_H00300_INDEX.json.gz").read_bytes())
            self.assertEqual(raw,recovered)
            self.assertEqual(hashlib.sha256(raw).hexdigest(),report["source_bytes_sha256"])
            with self.assertRaisesRegex(ValueError,"REFUSE_OVERWRITE_FUTURE_OUTCOME_CAPTURE"):
                save(path,report,outcome,raw)

    def test_missing_one_issuer_remains_122_and_no_primary_metric(self):
        _,ids,_,_,_,_=synthetic_entry()
        bs=FakeBS(missing=baostock_code(ids[10]))
        report,outcome,raw=capture(bs,now=AFTER,official_fetch=lambda _d:fake_index(),
                                   entry_sources=synthetic_entry())
        self.assertEqual(len(outcome["securities"]),122)
        self.assertEqual(report["quote_source_eligible_count"],121)
        self.assertEqual(report["quote_source_incomplete_count"],1)
        self.assertEqual(report["outcome_evaluation"]["status"],"INCOMPLETE_NEVER_DROP_NAMES")
        self.assertIsNone(report["outcome_evaluation"]["mean_net_excess"])
        self.assertFalse(report["trade_authorized"])

    def test_official_benchmark_failure_also_blocks_all_122_even_with_quotes(self):
        report,outcome,raw=capture(FakeBS(),now=AFTER,
                                   official_fetch=lambda _d:b"<html>blocked</html>",
                                   entry_sources=synthetic_entry())
        self.assertEqual(report["quote_source_eligible_count"],122)
        self.assertEqual(report["benchmark_source_status"],"OFFICIAL_H00300_EXIT_UNVERIFIED")
        self.assertEqual(report["outcome_evaluation"]["status"],
                         "INCOMPLETE_OFFICIAL_BENCHMARK_SOURCE_UNVERIFIED")
        self.assertFalse(report["trade_authorized"])

if __name__=="__main__":
    unittest.main()
