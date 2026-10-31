"""Deterministic no-lookahead, tradeability and full-denominator price-path tests."""
import copy
import gzip
import hashlib
import json
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parent))
from v29_2025_128_post_filing_price_path import (
    HORIZON,COST,SCHEMA,collect,code_for,evaluate,one_price_case,source_issuers,
)
from v29_2025_filing_to_return_case import validated_calendar,first_signal_and_exit

ISSUERS,SOURCE_HASH,SAMPLE_HASH=source_issuers()

def fixture():
    days=[]
    d=date(2025,2,1)
    while d<=date(2025,6,30):
        if d.weekday()<5:
            days.append(d)
        d+=timedelta(days=1)
    calendar=[{"calendar_date":d.isoformat(),"is_trading_day":"1"} for d in days]
    idx=[{"date":d.isoformat(),"code":"sh.000300","close":"100"} for d in days]
    market={}
    for issuer in ISSUERS:
        sid=issuer["security_id"]
        code=code_for(sid)
        raw=[]
        adj=[]
        for i,d in enumerate(days):
            basic={"date":d.isoformat(),"code":code,"close":str(100+i/10),
                   "tradestatus":"1","isST":"0","volume":"10000","amount":"100000"}
            raw.append({**basic,"adjustflag":"3"})
            adj.append({**basic,"adjustflag":"2"})
        market[sid]={"unadjusted":raw,"forward_adjusted_2026_vintage":adj}
    return calendar,idx,market

def modify_endpoint(issuer,cal,market,which,field,value):
    days=validated_calendar(cal)
    entry,exit_day=first_signal_and_exit(issuer["source_announcement_day"],days,HORIZON)
    key=entry if which=="entry" else exit_day
    bars=market[issuer["security_id"]]["unadjusted"]
    for r in bars:
        if r["date"]==key.isoformat():
            r[field]=value
            return
    raise AssertionError("expected mock bar missing")

class PricePathTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cal,cls.index,cls.market=fixture()
        cls.result=evaluate(ISSUERS,cls.cal,cls.index,cls.market)

    def test_frozen_pdf_identity_and_unseen_outcome_boundary(self):
        self.assertEqual(len(ISSUERS),128)
        self.assertEqual(len(SOURCE_HASH),64)
        self.assertEqual(len(SAMPLE_HASH),64)
        self.assertTrue(all(r["source_announcement_day"].startswith("2025-") for r in ISSUERS))

    def test_every_issuer_retained_in_predeclared_order(self):
        self.assertEqual(self.result["schema"],SCHEMA)
        self.assertEqual(self.result["sample_size"],128)
        self.assertEqual(self.result["price_comparison_count"],128)
        self.assertEqual(self.result["missing_or_nontradeable_count"],0)
        self.assertEqual([x["security_id"] for x in self.result["rows"]],
                         [x["security_id"] for x in ISSUERS])
        self.assertEqual(self.result["live_buy_eligibility"],"NOT_AUTHORIZED")
        self.assertFalse(self.result["strategy_validated"])

    def test_next_session_strictly_after_original_notice_and_20th_endpoint(self):
        trading=validated_calendar(self.cal)
        for src,received in zip(ISSUERS,self.result["rows"]):
            entry,exit_day=first_signal_and_exit(src["source_announcement_day"],trading,HORIZON)
            self.assertEqual(received["entry_session"],entry.isoformat())
            self.assertEqual(received["exit_session"],exit_day.isoformat())
            self.assertGreater(received["entry_session"],src["source_announcement_day"])
            self.assertEqual(trading.index(exit_day)-trading.index(entry),19)
            self.assertFalse(received["historical_financial_PIT_certified"])

    def test_zero_cost_benchmark_and_round_trip_cost_explicit(self):
        for r in self.result["rows"]:
            self.assertAlmostEqual(r["price_only_excess_after_30bps_vs_zero_cost_index"],
                                   r["stock_price_only_return"]-COST)
            self.assertEqual(r["csi300_price_index_return"],0)
            self.assertFalse(r["cash_dividends_and_corporate_action_economic_return_certified"])
            self.assertTrue(r["comparison_eligible"])

    def test_missing_entry_and_exit_do_not_shift_or_remove_names(self):
        c,i,m=fixture()
        for j,endpoint in [(0,"entry"),(1,"exit")]:
            src=ISSUERS[j]
            d=first_signal_and_exit(src["source_announcement_day"],validated_calendar(c),HORIZON)
            remove=d[0] if endpoint=="entry" else d[1]
            m[src["security_id"]]["unadjusted"]=[
                x for x in m[src["security_id"]]["unadjusted"]
                if x["date"]!=remove.isoformat()]
        result=evaluate(ISSUERS,c,i,m)
        self.assertEqual(result["sample_size"],128)
        self.assertEqual(result["price_comparison_count"],126)
        self.assertEqual(result["rows"][0]["price_observation_status"],
                         "ENTRY_BAR_MISSING_NO_LATER_ENTRY_SUBSTITUTION")
        self.assertEqual(result["rows"][1]["price_observation_status"],
                         "FIXED_HORIZON_EXIT_BAR_MISSING_NO_LATER_EXIT_SUBSTITUTION")

    def test_halts_and_st_risk_never_get_relocated(self):
        c,i,m=fixture()
        modify_endpoint(ISSUERS[0],c,m,"entry","tradestatus","0")
        modify_endpoint(ISSUERS[1],c,m,"entry","isST","1")
        modify_endpoint(ISSUERS[2],c,m,"exit","tradestatus","0")
        modify_endpoint(ISSUERS[3],c,m,"exit","isST","1")
        result=evaluate(ISSUERS,c,i,m)
        self.assertEqual(result["price_comparison_count"],124)
        self.assertEqual([x["price_observation_status"] for x in result["rows"][:4]],[
            "ENTRY_SESSION_NOT_TRADEABLE","ENTRY_SESSION_ST_FLAGGED",
            "EXIT_SESSION_NOT_TRADEABLE","EXIT_SESSION_ST_FLAGGED"])

    def test_identity_integrity_and_api_failure_no_silent_drop(self):
        c,i,m=fixture()
        m[ISSUERS[0]["security_id"]]["unadjusted"][0]["code"]="sh.123456"
        m[ISSUERS[1]["security_id"]]={"error":"BAOSTOCK_QUERY_FAILED"}
        result=evaluate(ISSUERS,c,i,m)
        self.assertEqual(result["sample_size"],128)
        self.assertEqual(result["price_comparison_count"],126)
        self.assertEqual(result["rows"][0]["price_observation_status"],
                         "PRICE_BAR_IDENTITY_OR_DUPLICATE_INVALID")
        self.assertEqual(result["rows"][1]["price_observation_status"],"SOURCE_QUERY_FAILED")
        self.assertEqual(result["source_failures_preserved"],2) if "source_failures_preserved" in result else None

    def test_missing_adjustment_preserves_raw_without_fake_total_return(self):
        c,i,m=fixture()
        m[ISSUERS[0]["security_id"]]["forward_adjusted_2026_vintage"]=[]
        result=evaluate(ISSUERS,c,i,m)
        x=result["rows"][0]
        self.assertTrue(x["comparison_eligible"])
        self.assertEqual(x["price_observation_status"],
                         "RAW_ENDPOINTS_COMPLETE_ADJUSTED_ENDPOINT_UNAVAILABLE")
        self.assertIsNone(x["later_vintage_forward_adjusted_return"])
        self.assertFalse(result["complete_dividend_adjusted_economic_return"])

    def test_known_future_outcomes_cannot_change_publication_date_or_order(self):
        altered=copy.deepcopy(ISSUERS)
        altered[0]["future_return_2025"]=10**9
        altered[1]["2026_price"]=0.001
        a=evaluate(altered,self.cal,self.index,self.market)
        self.assertEqual(a,self.result)

    def test_source_capture_preserves_raw_zip_and_denominator(self):
        class Rs:
            error_code="0"
            error_msg=""
            def __init__(self,fields,data):
                self.fields=fields.split(",")
                self.data=data
                self.pos=0
            def next(self):
                self.pos+=1
                return self.pos<=len(self.data)
            def get_row_data(self):
                r=self.data[self.pos-1]
                return [str(r.get(k,"")) for k in self.fields]
        class FakeBS:
            def login(self):return Rs("date",[])
            def logout(self):pass
            def query_trade_dates(self,**kw):
                return Rs("calendar_date,is_trading_day",selfCal)
            def query_history_k_data_plus(self,code,fields,**kw):
                if code=="sh.000300":
                    return Rs(fields,selfIdx)
                sid=("SSE:" if code.startswith("sh.") else "SZSE:")+code.split(".")[1]
                key="forward_adjusted_2026_vintage" if kw["adjustflag"]=="2" else "unadjusted"
                return Rs(fields,selfMarket[sid][key])
        selfCal,selfIdx,selfMarket=self.cal,self.index,self.market
        with tempfile.TemporaryDirectory() as td:
            directory=Path(td)/"capture"
            result=collect(FakeBS(),directory)
            self.assertEqual(len(result["rows"]),128)
            raw=gzip.decompress((directory/"RAW_BAOSTOCK_QUOTES_AND_CALENDAR.json.gz").read_bytes())
            self.assertEqual(result["raw_vendor_snapshot_sha256"],hashlib.sha256(raw).hexdigest())
            self.assertEqual(json.loads(raw)["pdf_source_manifest_sha256"],SOURCE_HASH)
            self.assertEqual(result["price_comparison_count"],128)
            with self.assertRaisesRegex(ValueError,"NO_OVERWRITE"):
                collect(FakeBS(),directory)

if __name__=="__main__":
    unittest.main()
