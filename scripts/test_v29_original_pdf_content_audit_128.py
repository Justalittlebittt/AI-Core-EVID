"""Deterministic tests for content-based FY2024 PDF evidence checks."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parent))
from v29_original_pdf_content_audit_128 import (
    verify_document,_numeric_text_tokens,_sources,target_for,collect
)


class FakePage:
    def __init__(self,text):self.text=text
    def extract_text(self):return self.text

class FakeReader:
    def __init__(self,_buf,strict=True):
        self.pages=[
            FakePage("南京银行 2024年度报告"),
            FakePage("营业收入 50,273,070 归母净利润 20,176,728"),
        ]+[FakePage("正文")]*38

class SummaryReader:
    def __init__(self,_buf,strict=True):
        self.pages=[FakePage("南京银行 2024年年度报告摘要")]+[FakePage("摘要")]*10

class PdfContentTests(unittest.TestCase):
    def test_yuan_thousand_and_ten_thousand_text_candidates(self):
        d=_numeric_text_tokens(50273070000)
        self.assertIn("50273070000",d["yuan"])
        self.assertIn("50273070",d["thousand_yuan"])
        self.assertIn("5027307",d["ten_thousand_yuan"])

    def test_first_pages_title_and_two_amounts_not_semantic_certification(self):
        with patch("pypdf.PdfReader",FakeReader):
            result=verify_document(b"%PDF-1.7 sample","南京银行",
                 {"revenue_yuan":50273070000,"parent_profit_yuan":20176728000})
        self.assertTrue(result["full_report_identity_pass"])
        self.assertTrue(result["both_financial_amounts_have_text_matches"])
        self.assertEqual(result["pdf_page_count"],40)
        self.assertFalse(result["field_semantic_table_row_certified"])

    def test_summary_never_promoted(self):
        with patch("pypdf.PdfReader",SummaryReader):
            result=verify_document(b"%PDF-1.7 sample","南京银行",
                 {"revenue_yuan":50273070000,"parent_profit_yuan":20176728000})
        self.assertTrue(result["cover_indicates_summary"])
        self.assertFalse(result["full_report_identity_pass"])
        self.assertFalse(result["both_financial_amounts_have_text_matches"])

    def test_wrong_issuer_rejected_without_ignoring_filename_or_vendor(self):
        with patch("pypdf.PdfReader",FakeReader):
            result=verify_document(b"%PDF-1.7 sample","上海电力",
                                   {"revenue_yuan":50273070000,"parent_profit_yuan":20176728000})
        self.assertFalse(result["cover_has_expected_issuer_name"])
        self.assertFalse(result["full_report_identity_pass"])

    def test_600021_mislabeled_summary_redirected_to_checked_full_source(self):
        frame,names,discovery,financial,resolution=_sources()
        self.assertEqual(len(frame["selected_ids"]),128)
        sid="SSE:600021"
        self.assertEqual(len(discovery[sid]["original_candidates"]),2)
        self.assertIsNone(discovery[sid]["chosen"])
        url,how=target_for(sid,discovery[sid],resolution)
        self.assertTrue(url.endswith("1222972839.PDF"))
        self.assertEqual(how,"PDF_COVER_AND_PAGE_COUNT_DISAMBIGUATED")

    def test_cannot_hide_failures_when_actual_download_broken(self):
        with tempfile.TemporaryDirectory() as d:
            def offline_failed(_url):
                raise OSError("blocked fixture")
            result=collect(Path(d)/"proof",limit=8,fetch=offline_failed)
            self.assertEqual(result["requested_count"],8)
            self.assertEqual(len(result["rows"]),8)
            self.assertEqual(result["pdf_fetch_or_decode_failed_count"],6)
            self.assertFalse(result["independent_oos_validated"])
            self.assertEqual(result["live_buy_eligibility"],"NOT_AUTHORIZED")
            self.assertEqual(result["rows"][7]["status"],
                             "UNQUERIED_AFTER_SIX_PDF_FETCH_FAILURES")

if __name__=="__main__":
    unittest.main()
