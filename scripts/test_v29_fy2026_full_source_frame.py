"""Synthetic, offline raw annual/Q3/F10 join and full-market denominator tests."""
import copy
import json
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from v29_fy2026_full_source_frame import build, summary_index, validate_market
from v29_fy2026_next_vintage_selector import select

NOW="2027-05-01T12:00:00+08:00"
CN=ZoneInfo("Asia/Shanghai")
IDS=[f"0019{i:02}" for i in range(10)]

def summary(code,period,**changes):
    annual=period=="2026-12-31"
    values={
        "SECUCODE":code+".SZ","SECURITY_CODE":code,
        "ORG_CODE":"ORG"+code,"REPORTDATE":period+" 00:00:00",
        "NOTICE_DATE":("2027-04-27" if annual else "2026-10-28")+" 00:00:00",
        "PARENT_NETPROFIT":2000000 if annual else 1300000,
        "YSTZ":32 if annual else 14,
        "SJLTZ":30 if annual else 25,
        "MGJYXJJE":1.2,
        "WEIGHTAVG_ROE":24,"XSMLL":35 if annual else 32
    }
    values.update(changes)
    return values

def core(code,period,**changes):
    annual=period=="2026-12-31"
    values={
        "SECUCODE":code+".SZ","SECURITY_CODE":code,
        "ORG_CODE":"ORG"+code,"REPORT_DATE":period+" 00:00:00",
        "NOTICE_DATE":("2027-04-27" if annual else "2026-10-28")+" 00:00:00",
        "UPDATE_DATE":("2027-04-27" if annual else "2026-10-28")+" 00:00:00",
        "PARENTNETPROFIT":2000000 if annual else 1300000,
        "KCFJCXSYJLR":1800000 if annual else 1100000
    }
    values.update(changes)
    return values

def page(rows):
    return json.dumps({"success":True,"result":{"count":len(rows),"pages":1,"data":rows}}).encode()

def market():
    calendar=[
        {"calendar_date":f"2027-05-{i:02}","is_trading_day":"1" if i==6 else "0"}
        for i in range(1,7)]
    calendar.insert(0,{"calendar_date":"2027-04-30","is_trading_day":"1"})
    return {
        "schema":"V29_FY2026_MARKET_REFERENCE_SOURCE_V1",
        "official_calendar_verified":True,
        "calendar":calendar,
        "all_stock":[{"code":"sz."+c,"tradeStatus":"1","code_name":"synthetic"} for c in IDS],
        "reference_bars":[{"date":"2027-04-30","code":"sz."+c,"adjustflag":"3",
                           "close":"30","volume":"12000",
                           "tradestatus":"1","isST":"0"} for c in IDS]
    }

def fixture():
    annual=[summary(c,"2026-12-31") for c in IDS]
    q3=[summary(c,"2026-09-30") for c in IDS]
    ac=[core(c,"2026-12-31") for c in IDS]
    qc=[core(c,"2026-09-30") for c in IDS]
    return ([page(annual)],[page(q3)],[page(ac)],[page(qc)],market(),NOW)

class FutureSourceFrameTests(unittest.TestCase):
    def test_complete_raw_vendor_join_ranks_eight_from_ten(self):
        frame=build(*fixture())
        self.assertEqual(frame["universe_source_count"],10)
        self.assertEqual(len(frame["rows"]),10)
        self.assertEqual(frame["all_source_counts"]["missing_by_field_source"]["annual_summary"],0)
        self.assertEqual(frame["rows"][0]["annual_deducted_parent_profit_yuan"],1800000)
        self.assertEqual(frame["rows"][0]["annual_nonrecurring_parent_profit_yuan"],200000)
        self.assertEqual(frame["rows"][0]["q3_ytd_deducted_parent_profit_yuan"],1100000)
        self.assertFalse(frame["rows"][0]["source_original_filing_verified"])
        self.assertTrue(frame["market_calendar_verified"])
        result=select(frame,datetime(2027,5,1,12,tzinfo=CN))
        self.assertEqual(result["total_rule_eligible"],10)
        self.assertEqual(result["selected_count"],8)
        self.assertEqual(result["live_buy_eligibility"],"NOT_AUTHORIZED")
        self.assertFalse(result["all_selected_original_filings_verified"])

    def test_unreported_and_unpriced_issuers_kept_in_denominator(self):
        ann,q3,ca,cq,quote,at=fixture()
        data=json.loads(ann[0])
        data["result"]["data"]=data["result"]["data"][1:]
        data["result"]["count"]=len(data["result"]["data"])
        ann=[json.dumps(data).encode()]
        quote["reference_bars"]=[x for x in quote["reference_bars"] if x["code"]!="sz."+IDS[1]]
        frame=build(ann,q3,ca,cq,quote,at)
        self.assertEqual(len(frame["rows"]),10)
        self.assertEqual(frame["all_source_counts"]["missing_by_field_source"]["annual_summary"],1)
        self.assertEqual(frame["all_source_counts"]["missing_by_field_source"]["reference_bar"],1)
        result=select(frame,datetime(2027,5,1,12,tzinfo=CN))
        self.assertEqual(result["total_source_universe"],10)
        self.assertEqual(result["total_rule_eligible"],8)
        self.assertEqual(result["source_exclusion_reason_counts"]["ANNUAL_OR_Q3_DISCLOSURE_MISSING"],1)
        self.assertEqual(result["source_exclusion_reason_counts"]["MANDATORY_FUNDAMENTAL_OR_REFERENCE_PRICE_MISSING"],1)

    def test_f10_parent_profit_mismatch_excludes_instead_of_fabricating_core(self):
        ann,q3,ca,cq,quote,at=fixture()
        d=json.loads(ca[0])
        d["result"]["data"][0]["PARENTNETPROFIT"]=33
        ca=[json.dumps(d).encode()]
        frame=build(ann,q3,ca,cq,quote,at)
        self.assertEqual(frame["rows"][0]["annual_core_source_status"],"PARENT_PROFIT_SOURCE_CONFLICT")
        self.assertIsNone(frame["rows"][0]["annual_deducted_parent_profit_yuan"])
        result=select(frame,datetime(2027,5,1,12,tzinfo=CN))
        self.assertEqual(result["total_rule_eligible"],9)

    def test_duplicate_or_truncated_financial_pages_fail_closed(self):
        rows=[summary(IDS[0],"2026-12-31")]
        with self.assertRaisesRegex(ValueError,"DUPLICATE_FINANCIAL_ISSUER"):
            summary_index([page(rows+rows)],"2026-12-31","2027-05-01")
        d=json.loads(page(rows));d["result"]["count"]=4
        with self.assertRaisesRegex(ValueError,"FINANCIAL_PAGES_INCOMPLETE"):
            summary_index([json.dumps(d).encode()],"2026-12-31","2027-05-01")

    def test_market_calendar_missing_or_price_date_shift_rejected(self):
        x=market()
        x["calendar"]=x["calendar"][:-1]
        with self.assertRaisesRegex(ValueError,"REFERENCE_OR_FIRST_SESSION_UNAVAILABLE"):
            validate_market(x)
        x=market()
        x["reference_bars"][0]["date"]="2027-05-06"
        with self.assertRaisesRegex(ValueError,"REFERENCE_BAR_DATE_VINTAGE_OR_IDENTITY_INVALID"):
            validate_market(x)

    def test_vendor_calendar_not_called_official_without_confirmation(self):
        ann,q3,ca,cq,m,at=fixture()
        m["official_calendar_verified"]=False
        frame=build(ann,q3,ca,cq,m,at)
        self.assertFalse(frame["market_calendar_verified"])
        with self.assertRaisesRegex(ValueError,"COMPLETE_EXCHANGE_SOURCE_OR_CALENDAR_REQUIRED"):
            select(frame,datetime(2027,5,1,12,tzinfo=CN))

    def test_future_source_cannot_be_made_from_2026(self):
        x=list(fixture());x[-1]="2026-11-05T12:00:00+08:00"
        with self.assertRaisesRegex(ValueError,"FUTURE_YEAR_ANNUAL_SOURCE_NOT_OBSERVABLE"):
            build(*x)

if __name__=="__main__":
    unittest.main()
