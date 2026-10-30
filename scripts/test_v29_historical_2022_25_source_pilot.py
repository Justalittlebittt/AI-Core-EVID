"""Offline test BaoStock historical data shape/chronology. No provider or future outcomes."""
import tempfile
import unittest
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
from v29_historical_2022_25_source_pilot import (
    first_eligible_session, _historical_sample, collect, CANDIDATES, YEARS
)

class FakeResponse:
    error_code="0"
    error_msg=""
    def __init__(self,fields,rows):
        self.fields=fields.split(",")
        self.rows=rows
        self.index=0
    def next(self):
        if self.index<len(self.rows):
            self.current=self.rows[self.index]
            self.index+=1
            return True
        return False
    def get_row_data(self):
        return [self.current.get(f,"") for f in self.fields]

class FakeBao:
    def __init__(self):
        self.closed=False
    def login(self):
        return FakeResponse("a",[])
    def logout(self):
        self.closed=True
    def query_trade_dates(self,start_date,end_date):
        return FakeResponse("calendar_date,is_trading_day",[
         {"calendar_date":f"2025-04-{d:02d}","is_trading_day":"1"}
         for d in range(1,29) if d not in (5,6,12,13,19,20,26,27)])
    def query_history_k_data_plus(self, code,fields,start_date,end_date,frequency,adjustflag):
        return FakeResponse(fields,[{
          "date":start_date,"code":code,"close":"10.0","volume":"100",
          "amount":"1000","adjustflag":adjustflag,"tradestatus":"1",
          "peTTM":"12.5","pbMRQ":"2.4","isST":"0"}])

class TestHistoricalSourcePilot(unittest.TestCase):
    def test_notice_not_fiscal_cutoff(self):
        dates=["2025-04-24","2025-04-25","2025-04-28"]
        out=first_eligible_session("2024-12-31","2025-04-24",dates)
        self.assertEqual(out,"2025-04-25")

    def test_friday_notice_waits_until_monday(self):
        dates=["2025-04-11","2025-04-14"]
        out=first_eligible_session("2024-12-31","2025-04-11",dates)
        self.assertEqual(out,"2025-04-14")

    def test_missing_post_notice_calendar_never_guessed(self):
        with self.assertRaisesRegex(ValueError,"NO_VERIFIED_POST_NOTICE"):
            first_eligible_session("2024-12-31","2025-04-24",["2025-04-23"])

    def test_future_period_or_impossible_notice_rejected(self):
        with self.assertRaisesRegex(ValueError,"REPORT_PUBLISHED_BEFORE"):
            first_eligible_session("2025-12-31","2025-04-24",["2026-01-05"])

    def test_unadjusted_vendor_prices_and_coverage(self):
        row={"date":"2024-04-03","code":"sz.300408","close":"10",
             "adjustflag":"3","tradestatus":"1","peTTM":"32","pbMRQ":"5"}
        o=_historical_sample([row],2024,"sz.300408")
        self.assertEqual(o["rows"],1)
        self.assertEqual(o["nonempty_pe_ttm"],1)
        self.assertEqual(o["first_bar"],"2024-04-03")

    def test_current_forward_adjustment_not_labeled_pit(self):
        row={"date":"2024-04-03","code":"sz.300408","close":"10",
             "adjustflag":"2","tradestatus":"1","peTTM":"32","pbMRQ":"5"}
        with self.assertRaisesRegex(ValueError,"UNEXPECTED_ADJUSTED_PRICE"):
            _historical_sample([row],2024,"sz.300408")

    def test_wrong_issuer_blocks(self):
        row={"date":"2024-04-03","code":"sz.300401","close":"10",
             "adjustflag":"3","tradestatus":"1","peTTM":"32","pbMRQ":"5"}
        with self.assertRaisesRegex(ValueError,"IDENTITY_OR_DATE"):
            _historical_sample([row],2024,"sz.300408")

    def test_capture_auditable_and_research_only(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"audit"
            bs=FakeBao()
            o=collect(path,bs)
            self.assertTrue(bs.closed)
            self.assertEqual(len(o["sample"]),2)
            self.assertEqual(len(o["sample"][0]["sample_by_year"]),4)
            self.assertFalse(o["backtest_executed"])
            self.assertFalse(o["historical_market_data_asof_2022_2025_certified"])
            self.assertFalse(o["external_pdf_vintage_certified"])
            self.assertEqual(o["live_buy_eligibility"],"NOT_AUTHORIZED")
            self.assertTrue((path/"raw_quotes_and_calendar.json").exists())
            with self.assertRaisesRegex(ValueError,"NO_OVERWRITE"):
                collect(path,FakeBao())

if __name__=="__main__":
    unittest.main()
