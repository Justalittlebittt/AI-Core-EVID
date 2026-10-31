"""Pure, offline source-integrity tests for retrospective financial coverage."""
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from v29_historical_universe_sampling import build_frame
from v29_2025_filing_source_coverage import valid_pages, match_fixed_sample, collect

FRAME = build_frame()

def row(sid, notice="2025-04-20", update="2025-04-20", revenue=200):
    exchange, code = sid.split(":")
    return {"SECUCODE":code+(".SH" if exchange=="SSE" else ".SZ"),
            "SECURITY_CODE":code, "REPORTDATE":"2024-12-31 00:00:00",
            "NOTICE_DATE":notice+" 00:00:00","UPDATE_DATE":update+" 00:00:00",
            "TOTAL_OPERATE_INCOME":revenue,"PARENT_NETPROFIT":20}

def pages(rows):
    half=len(rows)//2
    parts=[rows[:half],rows[half:]]
    n=len(rows)
    return [json.dumps({"success":True,"result":{"count":n,"pages":2,"data":p}},
                       ensure_ascii=False).encode() for p in parts]

class FixedHistoricalCoverageTests(unittest.TestCase):
    def test_frozen_128_population(self):
        self.assertEqual(len(FRAME["selected_ids"]),128)
        self.assertEqual(FRAME["population_count"],5121)

    def test_real_identity_join_and_all_missing_retained(self):
        s=FRAME["selected_ids"]
        raw=pages([row(s[0]),row(s[1]),row(s[1],notice="2025-05-10"),
                   row(s[2],update="2026-05-10")])
        records, receipts=valid_pages(raw)
        result=match_fixed_sample(FRAME,records,receipts)
        self.assertEqual(len(result["rows"]),128)
        self.assertEqual(result["vendor_metadata_matched_count"],3)
        self.assertEqual(result["unmatched_count"],125)
        self.assertEqual(result["multiple_version_count"],1)
        self.assertEqual(result["rows"][0]["coverage_status"],"SINGLE_VENDOR_SUMMARY_RECORD_NOT_OFFICIAL_PDF_CERTIFIED")
        self.assertEqual(result["rows"][1]["coverage_status"],"MULTIPLE_VENDOR_RECORDS_VERSION_NOT_UNIQUELY_RESOLVED")
        self.assertEqual(result["rows"][2]["coverage_status"],"VENDOR_ROW_UPDATED_AFTER_2025_CUTOFF_NOT_ASOF_CERTIFIED")
        self.assertIsNone(result["rows"][1]["vendor_revenue_yuan"])
        self.assertEqual(result["original_issuer_pdf_sha256_certified_count"],0)
        self.assertFalse(result["independent_oos_validated"])
        self.assertEqual(result["live_buy_eligibility"],"NOT_AUTHORIZED")
        self.assertTrue(all(not r["historical_pit_certified"] for r in result["rows"]))

    def test_no_future_notice_or_report_period(self):
        s=FRAME["selected_ids"][0]
        bad=row(s,notice="2026-04-20")
        badperiod=row(s)
        badperiod["REPORTDATE"]="2025-12-31"
        rows, receipts=valid_pages(pages([bad,badperiod]))
        result=match_fixed_sample(FRAME,rows,receipts)
        self.assertEqual(result["vendor_metadata_matched_count"],0)

    def test_source_page_truncation_and_count_drift_block(self):
        src=pages([row(FRAME["selected_ids"][0]),row(FRAME["selected_ids"][1])])
        with self.assertRaisesRegex(ValueError,"VENDOR_PAGINATION_OR_ROW_TOTAL_INCOMPLETE"):
            valid_pages(src[:1])
        wrong=json.loads(src[1])
        wrong["result"]["count"]=100
        with self.assertRaisesRegex(ValueError,"VENDOR_PAGINATION_CHANGED"):
            valid_pages([src[0],json.dumps(wrong).encode()])

    def test_outcome_fields_do_not_affect_join_or_select(self):
        s=FRAME["selected_ids"][0]
        original=row(s)
        updated=copy.deepcopy(original)
        updated["future_2025_return"]=99999
        for source in (original,updated):
            records,receipts=valid_pages(pages([source]))
            result=match_fixed_sample(FRAME,records,receipts)
            self.assertEqual(result["rows"][0]["coverage_status"],
                             "SINGLE_VENDOR_SUMMARY_RECORD_NOT_OFFICIAL_PDF_CERTIFIED")
            self.assertEqual(result["rows"][0]["vendor_revenue_yuan"],200)

    def test_network_free_capture_persists_all_rows_and_raw_pages(self):
        raw=pages([row(FRAME["selected_ids"][0]),row(FRAME["selected_ids"][1])])
        def fetch(period,page,notice_before=None):
            self.assertEqual(period,"2024-12-31")
            self.assertEqual(notice_before,"2025-07-01")
            return raw[page-1]
        with tempfile.TemporaryDirectory() as d:
            dest=Path(d)/"capture"
            result=collect(dest,fetch)
            self.assertEqual(result["fixed_sample_count"],128)
            self.assertEqual(len(list((dest/"raw_vendor_pages").glob("*.json"))),2)
            self.assertEqual(len(result["source_pages"]),2)
            self.assertTrue((dest/"coverage.csv").exists())
            self.assertTrue((dest/"coverage.json").exists())
            with self.assertRaisesRegex(ValueError,"NO_OVERWRITE"):
                collect(dest,fetch)

if __name__=="__main__":
    unittest.main()
