"""Offline live-collector orchestration tests: no real provider or future quotes."""
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from test_v29_fy2026_full_source_frame import fixture, IDS, page
from v29_fy2026_capture_live import capture, store, preflight, last_preopen_capture_day, load_sealed_q3

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

def synthetic_q3_loader():
    d=fixture()
    return d[1],d[3],{
        "identity":"SYNTHETIC_2026_Q3_TEST_ONLY",
        "source_vintage_date":"2026-10-30",
        "disclosure_cutoff_exclusive":"2026-10-30",
        "q3_2026_late_oct30_oct31_not_covered":True,
        "q3_values_queried_again_in_2027":False,
    }


class OriginalQ3ArchiveTests(unittest.TestCase):
    def test_real_archived_q3_and_f10_pages_are_complete_and_source_bound(self):
        # Read actual 2026 raw files, not handcrafted financial test values.
        from v29_fy2026_full_source_frame import summary_index, Q3
        from v29_growth_core_earnings import _decode
        q3,core,prov=load_sealed_q3()
        issuers,audit=summary_index(q3,Q3,"2026-11-01")
        index,hashes,core_count=_decode(core,Q3,"2026-11-01")
        self.assertGreater(len(q3),1)
        self.assertGreater(len(core),1)
        self.assertGreater(len(issuers),1000)
        self.assertGreater(core_count,1000)
        self.assertEqual(len(q3),len(audit["page_hashes"]))
        self.assertEqual(len(core),len(hashes))
        self.assertTrue(all(r.get("NOTICE_DATE","")[:10]<"2026-10-30"
                            for r in issuers.values()))
        self.assertEqual(prov["disclosure_cutoff_exclusive"],"2026-10-30")
        self.assertTrue(prov["q3_2026_late_oct30_oct31_not_covered"])
        self.assertFalse(prov["q3_values_queried_again_in_2027"])
        self.assertEqual(len(prov["source_git_archive_sha256"]),2)


class CaptureTimingTests(unittest.TestCase):
    def test_final_vendor_preopen_date_defers_first_holiday_capture(self):
        b=FakeBao()
        early=preflight(b,datetime(2027,5,1,21,25,tzinfo=CN))
        self.assertFalse(early["capture_today"])
        self.assertEqual(early["first_trading_session"],"2027-05-06")
        self.assertEqual(early["last_preopen_scheduled_day"],"2027-05-05")
        self.assertEqual([r[0] for r in b.queries],["calendar"])
        end=preflight(FakeBao(),datetime(2027,5,5,21,25,tzinfo=CN))
        self.assertTrue(end["capture_today"])
        self.assertEqual(end["calendar_source"],"BAOSTOCK_UNVERIFIED_VENDOR_CALENDAR")

    def test_last_preopen_schedule_adapts_if_market_reopens_earlier(self):
        self.assertEqual(last_preopen_capture_day("2027-05-04").isoformat(),"2027-05-03")
        self.assertEqual(last_preopen_capture_day("2027-05-06").isoformat(),"2027-05-05")
        self.assertEqual(last_preopen_capture_day("2027-05-08").isoformat(),"2027-05-05")
        with self.assertRaisesRegex(ValueError,"OUTSIDE_BOUNDED_2027_FINANCIAL_CAPTURE_WINDOW"):
            preflight(FakeBao(),datetime(2027,5,6,21,25,tzinfo=CN))

class LiveCaptureTests(unittest.TestCase):
    def test_financial_gate_queries_only_eligible_names_and_preserves_all_ten(self):
        b=FakeBao()
        frame,pick,market,pages=capture(
            b,NOW,summary_collector,core_collector,clock=lambda:NOW,q3_source_loader=synthetic_q3_loader)
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
        self.assertEqual(frame["q3_original_source_vintage"]["disclosure_cutoff_exclusive"],"2026-10-30")
        self.assertFalse(pick["historical_q3_source_certified_by_original_archive"])
        self.assertEqual(pick["historical_q3_original_vendor_vintage"],frame["q3_original_source_vintage"])
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

    def test_live_capture_requests_new_annual_only_not_future_revised_q3(self):
        requests=[]
        def only_annual_summary(report_date,notice_before):
            requests.append(("summary",report_date))
            if report_date!="2026-12-31":raise AssertionError("2027_Q3_REFETCH_FORBIDDEN")
            return None,fixture()[0]
        def only_annual_core(period,cutoff):
            requests.append(("core",period))
            if period!="2026-12-31":raise AssertionError("2027_Q3_F10_REFETCH_FORBIDDEN")
            return fixture()[2]
        frame,pick,market,pages=capture(
            FakeBao(),NOW,only_annual_summary,only_annual_core,
            clock=lambda:NOW,q3_source_loader=synthetic_q3_loader)
        self.assertEqual(requests,[("summary","2026-12-31"),("core","2026-12-31")])
        self.assertEqual(len(pages["q3"]),1)
        self.assertEqual(len(pages["q3_core"]),1)
        self.assertFalse(frame["q3_original_source_vintage"]["q3_values_queried_again_in_2027"])
        self.assertEqual(pick["live_buy_eligibility"],"NOT_AUTHORIZED")

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
        frame,selected,market,_=capture(b,NOW,summarized,core_collector,clock=lambda:NOW,q3_source_loader=synthetic_q3_loader)
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
            official_calendar=official,clock=lambda:NOW,q3_source_loader=synthetic_q3_loader)
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
            b,NOW,summary_collector,core_collector,clock=lambda:NOW,q3_source_loader=synthetic_q3_loader)
        self.assertEqual(frame["universe_source_count"],10)
        self.assertEqual(frame["preliminary_financial_qualification_count"],10)
        self.assertEqual(len(market["reference_bars"]),9)
        self.assertEqual(market["market_quote_errors"]["SZSE:"+IDS[0]],"REFERENCE_QUOTE_UNAVAILABLE")
        self.assertIsNone(frame["rows"][0]["reference_close_cny"])

    def test_dated_pre_entry_gate_rejects_early_and_late_use(self):
        def do(when):
            return capture(FakeBao(),when,summary_collector,core_collector,clock=lambda:when,q3_source_loader=synthetic_q3_loader)
        with self.assertRaisesRegex(ValueError,"FY2026_ANNUAL_DATA_NOT_YET_ELIGIBLE"):
            do(datetime(2026,11,5,12,tzinfo=CN))
        with self.assertRaisesRegex(ValueError,"FY26_SOURCE_NOT_PRE_ENTRY"):
            do(datetime(2027,5,6,10,tzinfo=CN))

if __name__=="__main__":
    unittest.main()
