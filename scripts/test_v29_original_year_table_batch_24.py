"""Real four-archived-PDF parser regression, plus fixed 24-source failure cases.

The test references actual 2026-sealed original PDF bytes on main and visually
reviewed current-year table values; no simulated returns or live network calls.
"""
import json
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parent))

from v29_original_year_table_parser import (
    classify,number,parse_original_table,currency_unit,FIELDS,
)
from v29_prior_year_original_table_batch_24 import load_pilot,one,collect
from v29_prior_year_four_original_table_reconciliation import (
    TABLE,BINARY,METADATA,
)

class Batch24TableTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import pymupdf
        cls.pdf = pymupdf
        cls.manifest=json.loads(METADATA.read_bytes())

    def test_all_four_real_original_report_table_cells_match_visual_source_values(self):
        byid={x["security_id"]:x for x in self.manifest["rows"]}
        for sid,checked in TABLE.items():
            doc=self.pdf.open(BINARY/byid[sid]["stored_pdf_file"])
            d=parse_original_table(doc,checked["fiscal_year"])
            self.assertEqual(d["status"],"ORIGINAL_YEAR_ACCOUNTING_TABLE_SCAN_COMPLETE")
            for field in FIELDS:
                extracted=d["fields"][field]
                self.assertEqual(extracted["status"],
                                 "UNIQUE_FISCAL_YEAR_TABLE_CELL_EXTRACTED",
                                 f"{sid}/{field} {extracted}")
                original_value=Decimal(str(checked[field][0]))
                expected=Decimal(extracted["extracted_value"])
                self.assertEqual(original_value,expected,f"{sid}/{field}")
                self.assertTrue(all(x["year_mapping_evidence"]
                                    for x in extracted["evidence"]))
                self.assertFalse(extracted[
                    "automatically_certified_as_original_release_time_vintage"])

    def test_never_take_quarterly_income_instead_of_fy2022_annual(self):
        byid={x["security_id"]:x for x in self.manifest["rows"]}
        sid="SSE:600088"
        document=self.pdf.open(BINARY/byid[sid]["stored_pdf_file"])
        result=parse_original_table(document,2022)
        candidates=result["fields"]["revenue_yuan"]["evidence"]
        self.assertEqual({v["normalized_value"] for v in candidates},
                         {"1149492197.34"})
        self.assertNotIn("201388759.28",
                         {v["normalized_value"] for v in candidates})
        self.assertTrue(result["other_quarterly_tables_not_treated_as_annual"])

    def test_discounted_profits_and_revenue_in_business_tables_not_relabelled(self):
        self.assertEqual(classify("归属于上市公司股东的扣除非经常性损益的净利润"),[])
        self.assertEqual(classify("扣除与主营业务无关的业务收入"),[])
        self.assertEqual(classify("研发投入占营业收入的比例"),[])
        self.assertEqual(classify("归属于上市公司股东的净利润"),
                         ["parent_net_profit_yuan"])
        self.assertIsNone(number("2023年末"))
        self.assertIsNone(number("不适用"))
        self.assertEqual(currency_unit("单位：万元",""),"ten_thousand_yuan")
        self.assertEqual(currency_unit("单位：元 币种人民币",""),"yuan")
        self.assertEqual(currency_unit("","营业收入（元）"),"yuan")

    def test_first_twelve_each_locked_before_pdf_download_with_missing_vendor_retained(self):
        selected,hashes=load_pilot()
        self.assertEqual(len(selected),24)
        self.assertEqual(len({(x["cohort_id"],x["security_id"])
                              for x in selected}),24)
        self.assertEqual(selected[0]["security_id"],"SSE:688416")
        self.assertEqual(selected[1]["security_id"],"SSE:600088")
        self.assertEqual(selected[12]["security_id"],"SSE:688031")
        self.assertEqual(selected[13]["security_id"],"SZSE:000070")
        self.assertEqual(len(hashes["frozen_original_cohorts_sha256"]),64)
        self.assertTrue(any(x["retrospective_vendor"]["matched_vendor_rows"]==0
                            for x in selected))
        self.assertTrue(any(not x["original_metadata"].get("chosen")
                            for x in selected))

    def test_source_checksum_and_vendor_restatement_separation_with_stored_four_pdfs(self):
        byid={x["security_id"]:x for x in self.manifest["rows"]}
        targets,_=load_pilot()
        test_sources=[x for x in targets if x["security_id"] in TABLE]
        def local_fetch(url):
            obj=next(x for x in byid.values() if x["source_url"]==url)
            return (BINARY/obj["stored_pdf_file"]).read_bytes()
        for source in test_sources:
            record=one(source,local_fetch)
            self.assertTrue(record["pdf_original_current_year_field_source"])
            self.assertTrue(record["original_table_all_four_fields_unambiguous"])
            self.assertEqual(len(record["field_sources"]),4)
            self.assertEqual(record["live_buy_eligibility"],"NOT_AUTHORIZED")
            self.assertFalse(record["original_PDF_release_time_sha256_certified"])
            if source["security_id"]=="SSE:600088":
                self.assertEqual(
                    record["field_sources"]["parent_net_profit_yuan"]
                    ["comparison_status"],
                    "ORIGINAL_AS_DISCLOSED_DIFFERS_FROM_LATER_VENDOR_VALUE")
                self.assertEqual(
                    record["field_sources"]["parent_net_profit_yuan"]
                    ["vendor_minus_source_value"],"380405.97")
                self.assertEqual(
                    record["field_sources"]["weighted_roe_pct"]
                    ["vendor_minus_source_value"],"0.09")

    def test_frozen_sample_is_not_reduced_if_original_missing_or_network_fails(self):
        with tempfile.TemporaryDirectory() as temp:
            dest=Path(temp)/"report"
            d=collect(dest,fetch=lambda _url:(_ for _ in ()).throw(OSError("offline fixture")))
            self.assertEqual(d["attempted_count"],24)
            self.assertEqual(d["frozen_audit_sample_count"],24)
            self.assertEqual(d["original_pdf_full_identity_verified_count"],0)
            self.assertEqual(len(d["rows"]),24)
            self.assertTrue(any(x["status"]=="NO_UNIQUE_ORIGINAL_2023_OR_2024_PDF_SOURCE"
                                for x in d["rows"]))
            self.assertFalse(d["no_historical_or_future_price_outcomes_queried"] is False)
            self.assertFalse(d["strategy_validated"])
            self.assertEqual(d["live_buy_eligibility"],"NOT_AUTHORIZED")
            with self.assertRaisesRegex(ValueError,"NO_OVERWRITE"):
                collect(dest,fetch=lambda _url:b"")

if __name__=="__main__":
    unittest.main()
