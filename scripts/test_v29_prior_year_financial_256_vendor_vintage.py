"""Source coverage checks: retrospective vendors must not be promoted to PIT."""
import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parent))
from v29_prior_year_financial_256_vendor_vintage import (
    SCHEMA,collect,match_frame,acquire_year
)
from v29_2023_2024_original_filing_discovery_256 import load_frozen_frames

FRAMES,_=load_frozen_frames()

def sample_financial(frame):
    sid=frame["selected_ids"][0]
    exch,code=sid.split(":")
    return {
        "SECUCODE":code+(".SH" if exch=="SSE" else ".SZ"),
        "SECURITY_CODE":code,
        "REPORTDATE":frame["report_period_end"]+" 00:00:00",
        "NOTICE_DATE":f"{frame['expected_issuer_publication_year']}-04-25 00:00:00",
        "UPDATE_DATE":"2026-06-19 00:00:00",
        "TOTAL_OPERATE_INCOME":123456789.00,
        "PARENT_NETPROFIT":3210000.00,
        "YSTZ":12.4,
        "WEIGHTAVG_ROE":6.8,
    }

def fake_financial_fetch(report_date,pageno,notice_before):
    frame=next(x for x in FRAMES["cohorts"] if x["report_period_end"]==report_date)
    assert pageno==1
    assert notice_before==f"{frame['expected_issuer_publication_year']+1}-01-01"
    source={"success":True,"result":{
        "count":1,"pages":1,"data":[sample_financial(frame)]
    }}
    return json.dumps(source).encode()

class HistoricalFinanceVendorTests(unittest.TestCase):
    def test_one_to_one_year_scope_no_future_issued_reporting_date(self):
        for f in FRAMES["cohorts"]:
            row=sample_financial(f)
            matches=match_frame(f,[row])
            self.assertEqual(len(matches),128)
            self.assertEqual(matches[0]["matched_vendor_rows"],1)
            self.assertEqual(sum(x["matched_vendor_rows"]==0 for x in matches),127)
            self.assertEqual(matches[0]["retrospective_financial_field_values"]
                             ["revenue_growth_yoy_pct"],12.4)
            self.assertEqual(matches[0]["update_days"],["2026-06-19"])
            self.assertFalse(matches[0]["financial_record_2023_or_2024_vintage_certified"])

    def test_wrong_fiscal_or_publication_year_is_not_a_usable_source(self):
        f=FRAMES["cohorts"][0]
        row=sample_financial(f)
        row["NOTICE_DATE"]="2024-04-25"
        with self.assertRaisesRegex(ValueError,"VENDOR_ISSUER_REPORT_NOTICE_DATE_OUTSIDE_YEAR"):
            match_frame(f,[row])
        row=sample_financial(f)
        row["REPORTDATE"]="2023-12-31"
        with self.assertRaisesRegex(ValueError,"FROZEN_FISCAL_YEAR_VENDOR_MISMATCH"):
            match_frame(f,[row])

    def test_multiple_financial_versions_stay_unresolved(self):
        f=FRAMES["cohorts"][0]
        row=sample_financial(f)
        row2={**row,"UPDATE_DATE":"2025-03-17","TOTAL_OPERATE_INCOME":999}
        matches=match_frame(f,[row,row2])
        self.assertEqual(matches[0]["coverage_status"],"MULTIPLE_VENDOR_VINTAGES_UNRESOLVED")
        self.assertEqual(matches[0]["matched_vendor_rows"],2)
        self.assertIsNone(matches[0]["retrospective_financial_field_values"]["revenue_yuan"])

    def test_exact_two_year_page_and_raw_sha_preserved_with_128_denominators(self):
        for f in FRAMES["cohorts"]:
            rows,raw,pages=acquire_year(
                f["report_period_end"],
                f"{f['expected_issuer_publication_year']+1}-01-01",
                fetch=fake_financial_fetch)
            self.assertEqual(len(rows),1)
            self.assertEqual(len(raw),len(pages))
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)/"source"
            receipt=collect(root,fetch=fake_financial_fetch)
            self.assertEqual(receipt["schema"],SCHEMA)
            self.assertEqual(receipt["total_sampled_issuer_year_cases"],256)
            self.assertEqual([c["vendor_single_record_matched_count"]
                              for c in receipt["cohorts"]],[1,1])
            self.assertEqual([c["vendor_missing_count"] for c in receipt["cohorts"]],[127,127])
            raw=(root/"RAW_EASTMONEY_2022_2023_FINANCIAL_PAGES.zip").read_bytes()
            self.assertEqual(receipt["raw_financial_page_zip_sha256"],
                             hashlib.sha256(raw).hexdigest())
            self.assertFalse(receipt["point_in_time_financial_values_certified"])
            self.assertEqual(receipt["live_buy_eligibility"],"NOT_AUTHORIZED")
            with self.assertRaisesRegex(ValueError,"NO_OVERWRITE"):
                collect(root,fetch=fake_financial_fetch)

if __name__=="__main__":
    unittest.main()
