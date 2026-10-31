"""Regression checks on actual archived FY2022/FY2023 annual PDF table cells.

This test requires the FOUR already committed original binaries; no source
network or historical price/outcome queries. FY2022 original ≠ later restated.
"""
import copy
import json
import sys
import unittest
from decimal import Decimal
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parent))
from v29_prior_year_four_original_table_reconciliation import (
    SCHEMA,TABLE,read_sources,evaluate,collect,exact_value_on_original_page
)

class OriginalDisclosureFieldVintageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original,cls.retrospective,cls.frames=read_sources()

    def test_four_real_original_pdfs_16_original_year_financial_cells(self):
        rows=evaluate(self.original,self.retrospective,self.frames)
        self.assertEqual(len(rows),16)
        self.assertEqual(len({(x["security_id"],x["financial_field"]) for x in rows}),16)
        self.assertEqual(sum(x["same_as_original_table_printed"] for x in rows),14)
        self.assertEqual(sum(not x["same_as_original_table_printed"] for x in rows),2)
        self.assertTrue(all(x["source_page_field_label_and_amount_present"] for x in rows))
        self.assertFalse(any(x["release_time_pdf_byte_hash_known"] for x in rows))
        self.assertTrue(all(x["live_buy_eligibility"]=="NOT_AUTHORIZED" for x in rows))

    def test_600088_original_vs_later_restatement_is_never_overwritten(self):
        rows=evaluate(self.original,self.retrospective,self.frames)
        by={(x["security_id"],x["financial_field"]):x for x in rows}
        profit=by[("SSE:600088","parent_net_profit_yuan")]
        roe=by[("SSE:600088","weighted_roe_pct")]
        self.assertEqual(profit["original_annual_report_current_year_table_value"],"-65289963.12")
        self.assertEqual(profit["retrospective_2026_vendor_financial_value"],"-64909557.15")
        self.assertEqual(Decimal(profit["vendor_minus_original_at_reported_precision"]),
                         Decimal("380405.97"))
        self.assertEqual(roe["original_annual_report_current_year_table_value"],"-6.32")
        self.assertEqual(roe["retrospective_2026_vendor_financial_value"],"-6.23")
        self.assertEqual(Decimal(roe["vendor_minus_original_at_reported_precision"]),
                         Decimal("0.09"))
        self.assertFalse(profit["same_as_original_table_printed"])
        self.assertFalse(roe["same_as_original_table_printed"])

    def test_wrong_original_value_or_year_prohibited_even_if_vendor_matches(self):
        f=self.original
        v=self.retrospective
        frames=self.frames
        bad=copy.deepcopy(v)
        x=next(r for r in bad["cohorts"][0]["rows"] if r["security_id"]=="SSE:688416")
        x["retrospective_financial_field_values"]["revenue_yuan"]+=1234.56
        with self.assertRaisesRegex(ValueError,"EXPECTED_16_FIELD_SOURCE_AND_2_KNOWN"):
            evaluate(f,bad,frames)
        altered=copy.deepcopy(f)
        x=next(r for r in altered["rows"] if r["security_id"]=="SSE:688416")
        x["fiscal_year"]=2023
        with self.assertRaisesRegex(ValueError,"WRONG_ORIGINAL_RELEASE_YEAR"):
            evaluate(altered,v,frames)

    def test_existing_pdf_sha_must_match_manifest_not_a_numerical_lookalike(self):
        modified=copy.deepcopy(self.original)
        x=next(r for r in modified["rows"] if r["security_id"]=="SSE:600088")
        x["2026_capture_pdf_sha256"]="0"*64
        with self.assertRaisesRegex(ValueError,"ORIGINAL_PDF_BYTES_OR_SHA_CHANGED"):
            evaluate(modified,self.retrospective,self.frames)

    def test_numeric_token_boundaries_disallow_substring_false_positive(self):
        self.assertTrue(exact_value_on_original_page(
            "归属于上市公司股东的净利润 -65,289,963.12","-65289963.12"))
        self.assertFalse(exact_value_on_original_page(
            "归属于上市公司股东的净利润 -65,289,963.1200","-65289963.12"))

    def test_complete_research_receipt_rejects_false_pit_and_oos_certification(self):
        d=collect()
        self.assertEqual(d["schema"],SCHEMA)
        self.assertEqual(d["matching_to_vendor_at_original_report_precision"],14)
        self.assertEqual(d["nonmatching_to_vendor_at_original_report_precision"],2)
        self.assertFalse(d["historical_financial_value_release_time_SHA_certified"])
        self.assertFalse(d["chronologically_unseen_oos_validated"])
        self.assertFalse(d["factor_model_promoted"])
        self.assertTrue(d["all_other_252_frozen_issuer_years_not_field_certified"])
        self.assertEqual(d["live_buy_eligibility"],"NOT_AUTHORIZED")

if __name__=="__main__":
    unittest.main()
