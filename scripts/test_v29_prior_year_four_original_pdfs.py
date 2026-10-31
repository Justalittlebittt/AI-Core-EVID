"""Offline regression tests of four fixed original PDFs and field-label proximity.

Never represent a number appearing elsewhere on a page as a verified row.
"""
import copy
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parent))
from v29_prior_year_four_original_pdfs import (
    sources,numeric_candidates,nearby_labels_and_numbers,examine_pdf,collect,
)

class Page:
    def __init__(self,t): self.t=t
    def get_text(self,method,sort=False): return self.t

class Reader:
    def __init__(self,texts): self.pages=[Page(t) for t in texts]+[Page("正文")]*35
    def __len__(self): return len(self.pages)
    def __getitem__(self,i): return self.pages[i]

def fake_document(row="营业收入（元）\n433,277,479.71\n归属于上市公司股东的净利润（元）\n21,205,562.13"):
    return Reader(["股票代码 688416 2022 年年度报告 恒烁股份",row])

class FourOriginalPdfTests(unittest.TestCase):
    def test_all_four_are_preselected_official_url_and_vendor_notice_matches(self):
        entries,sources_sha=sources()
        self.assertEqual(len(entries),4)
        self.assertEqual([x["security_id"] for x in entries],
                         ["SSE:688416","SSE:600088","SSE:688031","SZSE:000070"])
        self.assertEqual([x["fiscal_year"] for x in entries],[2022,2022,2023,2023])
        for row in entries:
            self.assertTrue(row["source_url"].startswith(
                f"https://static.cninfo.com.cn/finalpage/{row['source_notice']}/"))
            self.assertGreater(len(row["vendor_source_hashes"]),0)
            self.assertTrue(row["vendor_update_days"])
        self.assertEqual(len(sources_sha["official_metadata_sha256"]),64)

    def test_financial_token_near_same_label_is_only_candidate_not_pit_certification(self):
        pages=[(4,["主要会计数据","单位：元",
                   "营业收入（元） 433,277,479.71",
                   "归属于上市公司股东的净利润（元） 21,205,562.13"])]
        v=nearby_labels_and_numbers(pages,("营业收入",),433277479.71)
        self.assertGreater(v["candidate_count"],0)
        self.assertFalse(v["semantic_table_cell_certified"])
        self.assertEqual(v["candidate_rows"][0]["pdf_page"],4)
        self.assertEqual(v["candidate_rows"][0]["provisional_unit"],"yuan")
        p=nearby_labels_and_numbers(
            pages,("归属于上市公司股东的净利润",),21205562.13)
        self.assertGreater(p["candidate_count"],0)
        self.assertFalse(p["semantic_table_cell_certified"])

    def test_lonely_number_elsewhere_never_becomes_field_semantic_evidence(self):
        data=[(7,["营业收入（元）","完全无对应的数字"]),
              (8,["433,277,479.71","计算范例"]),
              (9,["21,205,562.13","利润别的段落"])]
        v=nearby_labels_and_numbers(data,("营业收入",),433277479.71)
        self.assertEqual(v["status"],"NO_FIELD_ROW_VALUE_PROXIMITY_FOUND")
        self.assertFalse(v["semantic_table_cell_certified"])

    def test_reversed_amount_before_label_never_certifies(self):
        v=nearby_labels_and_numbers([(4,["433,277,479.71 营业收入（元）"])],
                                    ("营业收入",),433277479.71)
        self.assertEqual(v["candidate_count"],0)

    def test_rounded_ten_thousand_yuan_matches_unit_as_candidate_not_equality(self):
        nums=numeric_candidates(433277479.71)
        self.assertIn(("ten_thousand_yuan","43327.75"),nums)
        row=nearby_labels_and_numbers([(4,["单位：万元","营业收入 43,327.75"])],
                                      ("营业收入",),433277479.71)
        self.assertGreater(row["candidate_count"],0)
        self.assertFalse(row["semantic_table_cell_certified"])

    def test_pdf_issuer_fiscal_year_and_full_report_identity_is_strict(self):
        t=sources()[0][0]
        import pymupdf
        with patch.object(pymupdf,"open",return_value=fake_document()):
            r=examine_pdf(b"%PDF fake document",t)
        self.assertTrue(r["original_full_issuer_report_identity_verified"])
        self.assertFalse(r["semantic_table_cell_certified"])
        self.assertGreater(r["field_nearby_value_hits"],0)
        with patch.object(pymupdf,"open",return_value=Reader([
                "股票代码 688416 2024 年年度报告","营业收入 433,277,479.71"])):
            with self.assertRaisesRegex(ValueError,"ORIGINAL_PDF_ISSUER_YEAR"):
                examine_pdf(b"%PDF fake document",t)
        with patch.object(pymupdf,"open",return_value=Reader([
                "股票代码 688416 2022 年年度报告摘要","营业收入 433,277,479.71"])):
            with self.assertRaisesRegex(ValueError,"ORIGINAL_PDF_ISSUER_YEAR"):
                examine_pdf(b"%PDF fake document",t)

    def test_capture_with_broken_download_retains_all_four_and_never_promotes(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/"audit"
            r=collect(p,fetch=lambda _url: (_ for _ in ()).throw(OSError("offline")))
            self.assertEqual(len(r["rows"]),4)
            self.assertEqual(r["archived_full_original_pdf_count"],0)
            self.assertEqual(r["complete_original_financial_field_pit_certified_count"],0)
            self.assertEqual(r["live_buy_eligibility"],"NOT_AUTHORIZED")
            with self.assertRaisesRegex(ValueError,"ALREADY_EXISTS_NO_OVERWRITE"):
                collect(p,fetch=lambda _url:None)

if __name__=="__main__":
    unittest.main()
