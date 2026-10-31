"""Deterministic original PDF identity and historic-vendor boundary checks."""
from __future__ import annotations
import copy
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parent))
from v29_historical_universe_sampling import build_frame
from v29_original_filing_pdf_proof import (
    COVERAGE,TARGETS,fetch_binary,validate_targets,verify_pdf,
)

class MockResponse:
    def __init__(self,data):self.data=data;self.cursor=0
    def __enter__(self):return self
    def __exit__(self,*a):return False
    def read(self,n):
        result=self.data[self.cursor:self.cursor+n]
        self.cursor+=len(result)
        return result

class MockPage:
    def __init__(self,t):self.t=t
    def extract_text(self):return self.t

class MockPdf:
    def __init__(self,_buf,strict=True):
        self.pages=[MockPage("2024 年度报告 股票代码 601009")] + [MockPage("营业收入 50,273,070 归母净利润 20,176,728")]+[MockPage("其他页")]*40

class OriginalPdfTests(unittest.TestCase):
    def setUp(self):
        self.frame=build_frame()
        self.coverage=json.loads(COVERAGE.read_text(encoding="utf-8"))

    def test_frozen_sample_and_expected_financial_numbers(self):
        checked=validate_targets(TARGETS,self.frame,self.coverage)
        self.assertEqual(len(checked),2)
        self.assertEqual([x[0]["security_id"] for x in checked],
                         ["SSE:601009","SZSE:002493"])

    def test_post_publication_vendor_update_not_pit_authorized(self):
        for t,row in validate_targets(TARGETS,self.frame,self.coverage):
            self.assertGreater(row["vendor_update_dates"][-1],t["publication_day"])

    def test_wrong_publication_and_value_rejected(self):
        changed=[copy.deepcopy(x) for x in TARGETS]
        changed[0]["publication_day"]="2025-04-23"
        with self.assertRaisesRegex(ValueError,"PUBLICATION_DAY_OR_VENDOR_IDENTITY_CONFLICT"):
            validate_targets(changed,self.frame,self.coverage)
        changed=[copy.deepcopy(x) for x in TARGETS]
        changed[0]["numbers_in_pdf_units"]["revenue"]="50273071"
        with self.assertRaisesRegex(ValueError,"REVENUE_EXPECTATION"):
            validate_targets(changed,self.frame,self.coverage)

    def test_non_pdf_bytes_cannot_be_sealed(self):
        with self.assertRaisesRegex(ValueError,"INVALID_OR_INCOMPLETE_PDF_BYTES"):
            fetch_binary(TARGETS[0]["url"],opener=lambda _req,timeout:MockResponse(b"<html>Blocked</html>"))

    def test_identity_and_amount_presence_are_distinct_from_semantic_certification(self):
        with patch("pypdf.PdfReader",MockPdf):
            result=verify_pdf(b"%PDF-1.7 mock %%EOF",TARGETS[0])
        self.assertTrue(result["expected_amounts_text_present"])
        self.assertTrue(result["pdf_structurally_parsed"])
        self.assertFalse(result["semantic_field_to_table_cell_automatically_certified"])
        self.assertEqual(result["expected_financial_amount_text_pages_first_42"]["revenue"],[2])

    def test_wrong_issuer_identity_rejected(self):
        with patch("pypdf.PdfReader",MockPdf):
            with self.assertRaisesRegex(ValueError,"PDF_SECURITY_YEAR_OR_FULL_REPORT_IDENTITY_FAILED"):
                verify_pdf(b"%PDF-1.7 mock %%EOF",TARGETS[1])

if __name__=="__main__":
    unittest.main()
