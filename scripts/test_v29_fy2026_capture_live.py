"""Offline live-collector orchestration tests: no real provider or future quotes."""
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from test_v29_fy2026_full_source_frame import fixture, IDS, page
from v29_fy2026_capture_live import capture, store

CN=ZoneInfo("Asia/Shanghai")
NOW=datetime(2027,5,1,12,tzinfo=CN)

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
        return [str(self.rows[self.position-1].get(col,"")) for col in self.fields]

class FakeBao:
    def __init__(self,quote_missing=None):
        self.queries=[]
        self.quote_missing=quote_missing
    def login(self):
        return Result("code",[])
    def logout(self):
        pass
    def query_trade_dates(self,start_date,end_date):
        rows=fixture()[4]["calendar"]
        self.queries.append(("calendar",start_date,end_date))
        return Result("calendar_date,is_trading_day",rows)
    def query_all_stock(self,day):
        self.queries.append(("stock",day))
        return Result("code,tradeStatus,code_name",fixture()[4]["all_stock"])
    def query_history_k_data_plus(self,code,fields,start_date,end_date,frequency,adjustflag):
        self.queries.append(("quote",code,start_date,end_date,adjustflag))
        rows=[x for x in fixture()[4]["reference_bars"] if x["code"]==code]
        if code==self.quote_missing:
            rows=[]
        return Result(fields,rows)

def summary_collector(period,notice_before):
    assert notice_before==("2027-05-01" if period=="2026-12-31" else "2026-11-01")
    return None,fixture()[0 if period=="2026-12-31" else 1]

def core_collector(period,cutoff):
    assert cutoff==("2027-05-01" if period=="2026-12-31" else "2026-11-01")
    return fixture()[2 if period=="2026-12-31" else 3]

class LiveCaptureTests(unittest.TestCase):
    def test_financial_gate_queries_only_eligible_names_and_preserves_all_ten(self):
        b=FakeBao()
        frame,pick,market,pages=capture(
            b,NOW,summary_collector,core_collector,clock=lambda:NOW)
        self.assertEqual(frame["universe_source_count"],10)
        self.assertEqual(frame["preliminary_financial_qualification_count"],10)
        self.assertEqual(len(market["reference_bars"]),10)
        self.assertEqual(len([q for q in b.queries if q[0]=="quote"]),10)
        self.assertFalse(frame["market_calendar_verified"])
        self.assertEqual(pick["selected_count"],8)
        self.assertEqual(pick["status"],"PROVISIONAL_VENDOR_CALENDAR_RESEARCH_ONLY")
        self.assertTrue(pick["calendar_pending_official_verification"])
        self.assertFalse(pick["calendar_officially_verified"])
        self.assertEqual(pick["live_buy_eligibility"],"NOT_AUTHORIZED")
        self.assertFalse(frame["source_original_filings_available"])
        self.assertEqual(len(pages["annual"]),1)
        with tempfile.TemporaryDirectory() as p:
            dest=Path(p)/"future-data"
            store(dest,frame,pick,market,pages)
            self.assertTrue((dest/"NORMALIZED_ALL_A_FRAME.json").exists())
            self.assertTrue((dest/"annual-summary/page-001.json").exists())
            self.assertFalse((dest/"FROZEN_EIGHT_RESEARCH_ONLY.json").exists())
            self.assertTrue((dest/"PROVISIONAL_EIGHT_RESEARCH_ONLY.json").exists())
            archived=json.loads((dest/"PROVISIONAL_EIGHT_RESEARCH_ONLY.json").read_text())
            self.assertEqual(archived["status"],"PROVISIONAL_VENDOR_CALENDAR_RESEARCH_ONLY")
            self.assertFalse(archived["all_selected_original_filings_verified"])
            with self.assertRaisesRegex(ValueError,"SOURCE_CAPTURE_DESTINATION_ALREADY_EXISTS"):
                store(dest,frame,pick,market,pages)

    def test_financially_ineligible_stocks_never_trigger_quotes(self):
        original=fixture()
        def summarized(period,notice_before):
            index=0 if period=="2026-12-31" else 1
            raw=json.loads(original[index][0])
            if index==0:
                raw["result"]["data"][0]["WEIGHTAVG_ROE"]=0.
                raw["result"]["data"][1]["YSTZ"]=-2.
            return None,[json.dumps(raw).encode()]
        b=FakeBao()
        frame,selected,market,_=capture(b,NOW,summarized,core_collector,clock=lambda:NOW)
        self.assertEqual(frame["universe_source_count"],10)
        self.assertEqual(frame["preliminary_financial_qualification_count"],8)
        self.assertEqual(len([x for x in b.queries if x[0]=="quote"]),8)
        self.assertEqual(len(market["reference_bars"]),8)
        self.assertEqual(frame["all_source_counts"]["missing_by_field_source"]["reference_bar"],2)
        self.assertEqual(selected["status"],"PROVISIONAL_VENDOR_CALENDAR_RESEARCH_ONLY")
        self.assertEqual(selected["selected_count"],8)
        self.assertFalse(selected["strategy_validated"])

    def test_separate_exchange_calendar_evidence_allows_research_selection(self):
        official={"source_type":"OFFICIAL_EXCHANGE_SCHEDULE",
                  "source_url":"https://www.sse.com.cn/fake-only-synthetic-test",
                  "first_trading_session":"2027-05-06",
                  "reference_trading_session":"2027-04-30"}
        frame,pick,market,pages=capture(
            FakeBao(),NOW,summary_collector,core_collector,
            official_calendar=official,clock=lambda:NOW)
        self.assertTrue(frame["market_calendar_verified"])
        self.assertEqual(pick["selected_count"],8)
        self.assertEqual(pick["status"],"FROZEN_NEW_REPORT_CANDIDATES_RESEARCH_ONLY")
        self.assertTrue(pick["calendar_officially_verified"])
        self.assertFalse(pick["preliminary_vendor_calendar_only"])
        self.assertEqual(pick["live_buy_eligibility"],"NOT_AUTHORIZED")
        self.assertFalse(pick["all_selected_original_filings_verified"])
        with tempfile.TemporaryDirectory() as temp:
            store(Path(temp)/"output",frame,pick,market,pages)
            self.assertTrue((Path(temp)/"output/FROZEN_EIGHT_RESEARCH_ONLY.json").exists())

    def test_missing_quote_does_not_disappear_or_get_substituted(self):
        sid="sz."+IDS[0]
        b=FakeBao(quote_missing=sid)
        frame,pick,market,_=capture(
            b,NOW,summary_collector,core_collector,clock=lambda:NOW)
        self.assertEqual(frame["universe_source_count"],10)
        self.assertEqual(frame["preliminary_financial_qualification_count"],10)
        self.assertEqual(len(market["reference_bars"]),9)
        self.assertEqual(market["market_quote_errors"]["SZSE:"+IDS[0]],"REFERENCE_QUOTE_UNAVAILABLE")
        self.assertIsNone(frame["rows"][0]["reference_close_cny"])

    def test_dated_pre_entry_gate_rejects_early_and_late_use(self):
        def do(when):
            return capture(FakeBao(),when,summary_collector,core_collector,clock=lambda:when)
        with self.assertRaisesRegex(ValueError,"FY2026_ANNUAL_DATA_NOT_YET_ELIGIBLE"):
            do(datetime(2026,11,5,12,tzinfo=CN))
        with self.assertRaisesRegex(ValueError,"FY26_SOURCE_NOT_PRE_ENTRY"):
            do(datetime(2027,5,6,10,tzinfo=CN))

if __name__=="__main__":
    unittest.main()
