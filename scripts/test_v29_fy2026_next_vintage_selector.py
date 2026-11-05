"""Synthetic future annual statements only; never request unavailable FY26 filings."""
import copy
import json
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from v29_fy2026_next_vintage_selector import plan_source, select, record_filter

CN=ZoneInfo("Asia/Shanghai")
NOW=datetime(2027,5,1,10,5,tzinfo=CN)

def row(sid,roe=20,accel=12,verified=False):
    return {
        "security_id":sid,
        "annual_period":"2026-12-31","q3_period":"2026-09-30",
        "annual_disclosure_date":"2027-04-28","q3_disclosure_date":"2026-10-29",
        "source_original_filing_verified":verified,
        "reference_close_session":"2027-04-30","reference_close_cny":30.,
        "annual_revenue_yoy_pct":32.,"q3_ytd_revenue_yoy_pct":32.-accel,
        "annual_parent_profit_yuan":2000000.,
        "annual_parent_profit_yoy_pct":30.,"q3_ytd_parent_profit_yoy_pct":22.,
        "annual_deducted_parent_profit_yuan":1800000.,
        "q3_ytd_deducted_parent_profit_yuan":1200000.,
        "annual_roe_pct":float(roe),"annual_cfo_per_share_yuan":1.2,
        "annual_gross_margin_pct":34.,"q3_ytd_gross_margin_pct":32.,
        "annual_nonrecurring_parent_profit_yuan":100000.,
        "is_st_at_reference_session":False,
    }

def fixture():
    s=[row("SZSE:0019"+str(i).zfill(2),roe=20+i,verified=(i%2==0)) for i in range(8)]
    s.append(row("SZSE:300199",roe=40,verified=True))
    return {
        "schema":"V29_FY2026_NORMALIZED_ALL_A_SOURCE_FRAME_V1",
        "report_period":"2026-12-31","comparison_period":"2026-09-30",
        "financial_coverage_status":"COMPLETE_VENDOR_ALL_A_CROSS_SECTION",
        "market_calendar_verified":True,
        "source_original_filings_available":False,
        "first_trading_session_after_cutoff":"2027-05-06",
        "reference_close_session":"2027-04-30",
        "captured_at":"2027-05-01T10:00:00+08:00",
        "raw_source_sha256":{k:"a"*64 for k in
            ("annual","q3","reference_prices","calendar")},
        "universe_source_count":len(s),"rows":s,
    }

class FY2026SelectorTests(unittest.TestCase):
    def test_registered_plan_sealed_before_future_financial_disclosures(self):
        p,sha=plan_source()
        self.assertEqual(p["registered_on"],"2026-11-05")
        self.assertEqual(sha,"6658fd16f481dbc13e25b256233a9fa10ebf7cf5")
        self.assertFalse(p["strict_interpretation"]["identical_original_2026Q3_rule_replication"])

    def test_full_universe_selects_eight_without_vendor_only_filing_blocker(self):
        result=select(fixture(),NOW)
        self.assertEqual(result["status"],"FROZEN_NEW_REPORT_CANDIDATES_RESEARCH_ONLY")
        self.assertEqual(result["total_source_universe"],9)
        self.assertEqual(result["total_rule_eligible"],9)
        self.assertEqual(result["selected_count"],8)
        self.assertEqual(result["selected_in_frozen_ranking_order"][0]["security_id"],"SZSE:300199")
        self.assertEqual(result["overlap_with_original_2026q3_122"],1)
        self.assertEqual(result["selected_original_filing_verified_count"],4)
        self.assertFalse(result["all_selected_original_filings_verified"])
        self.assertTrue(result["vendor_vintage_not_independent_original_release_pit_certification"])
        self.assertEqual(result["live_buy_eligibility"],"NOT_AUTHORIZED")

    def test_no_rule_relaxation_if_six_firms_qualify(self):
        d=fixture()
        d["rows"]=d["rows"][:6]
        d["universe_source_count"]=6
        result=select(d,NOW)
        self.assertEqual(result["status"],"INSUFFICIENT_NO_EIGHT_NO_THRESHOLD_RELAXATION")
        self.assertEqual(result["selected_count"],0)
        self.assertEqual(result["total_rule_eligible"],6)
        self.assertEqual(result["selected_in_frozen_ranking_order"],[])

    def test_missing_or_post_cutoff_report_fails_per_issuer_without_disappearing(self):
        d=fixture()
        d["rows"][0]["annual_disclosure_date"]="2027-05-02"
        d["rows"][1]["annual_gross_margin_pct"]=30.
        d["rows"][2]["annual_nonrecurring_parent_profit_yuan"]=1500000.
        d["rows"][3]["annual_deducted_parent_profit_yuan"]=1000000.
        d["rows"][4]["is_st_at_reference_session"]=True
        result=select(d,NOW)
        self.assertEqual(result["total_source_universe"],9)
        self.assertEqual(result["total_rule_eligible"],4)
        self.assertEqual(result["selected_count"],0)
        self.assertEqual(result["source_exclusion_reason_counts"]["ANNUAL_REPORT_DISCLOSED_AFTER_CUTOFF"],1)
        self.assertEqual(result["source_exclusion_reason_counts"]["ANNUAL_GROSS_MARGIN_DECLINE"],1)
        self.assertEqual(result["source_exclusion_reason_counts"]["NONRECURRING_PROFIT_EXCESS"],1)
        self.assertEqual(result["source_exclusion_reason_counts"]["PARENT_OR_STANDALONE_Q4_CORE_PROFIT_RULE_FAILED"],1)
        self.assertEqual(result["source_exclusion_reason_counts"]["ST_OR_ST_STATUS_UNVERIFIED"],1)
        d=fixture()
        d["rows"][0]["annual_parent_profit_yuan"]=0.
        r=select(d,NOW)
        self.assertEqual(r["total_rule_eligible"],8)
        self.assertEqual(r["source_exclusion_reason_counts"]["NONRECURRING_PROFIT_EXCESS"],1)

    def test_minimum_lots_and_annual_roe_ranking(self):
        p=plan_source()[0]
        x=row("SSE:688999")
        x["reference_close_cny"]=61.
        reasons,candidate=record_filter(x,p["selection"],"2027-04-30")
        self.assertIn("MINIMUM_EXCHANGE_LOT_OUT_OF_BUDGET",reasons)
        self.assertIsNone(candidate)
        x["reference_close_cny"]=60.
        reasons,candidate=record_filter(x,p["selection"],"2027-04-30")
        self.assertEqual(reasons,[])
        self.assertEqual(candidate["minimum_lot_shares"],200)
        self.assertEqual(candidate["pre_entry_reference_notional_cny"],12000)

    def test_not_allowed_before_new_disclosures_or_after_first_open(self):
        d=fixture()
        for when in (datetime(2026,11,5,13,tzinfo=CN),
                     datetime(2027,5,6,9,30,tzinfo=CN)):
            with self.assertRaisesRegex(ValueError,"NEW_REPORT_SOURCE_MUST_BE_CAPTURED"):
                select(d,when)
        d["captured_at"]="2027-05-06T09:45:00+08:00"
        with self.assertRaisesRegex(ValueError,"NEW_REPORT_SOURCE_MUST_BE_CAPTURED"):
            select(d,datetime(2027,5,6,10,tzinfo=CN))

    def test_no_future_entry_close_or_hidden_incomplete_universe(self):
        d=fixture()
        d["rows"][0]["reference_close_session"]="2027-05-06"
        r=select(d,NOW)
        self.assertEqual(r["total_source_universe"],9)
        self.assertEqual(r["total_rule_eligible"],8)
        self.assertEqual(r["source_exclusion_reason_counts"]["REFERENCE_PRICE_SESSION_CHANGED"],1)
        d=fixture()
        d["universe_source_count"]=10
        with self.assertRaisesRegex(ValueError,"ALL_SOURCE_ISSUER_DENOMINATOR_NOT_COMPLETE"):
            select(d,NOW)

    def test_no_duplicate_and_no_unproven_complete_calendar(self):
        d=fixture()
        d["rows"][0]["security_id"]=d["rows"][1]["security_id"]
        with self.assertRaisesRegex(ValueError,"DUPLICATE_SOURCE_ISSUER"):
            select(d,NOW)
        d=fixture()
        d["market_calendar_verified"]=False
        with self.assertRaisesRegex(ValueError,"COMPLETE_EXCHANGE_SOURCE_OR_CALENDAR_REQUIRED"):
            select(d,NOW)

if __name__=="__main__":
    unittest.main()
