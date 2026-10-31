"""Deterministic checks that PDF unit display rounding is not restatement."""
import json
import sys
import unittest
from decimal import Decimal
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parent))
from v29_original_table_reporting_precision import source_quantum,reconcile_field
from v29_original_24_precision_reconciliation import SOURCE,audit

class HistoricalFinancialPresentationPrecisionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original=json.loads(SOURCE.read_bytes())
        cls.result=audit(cls.original)

    def test_persisted_real_24_reports_and_63_compared_cells_stay_fixed(self):
        d=self.result
        self.assertEqual(d["fixed_issuer_year_denominator"],24)
        self.assertEqual(d["fixed_original_report_full_identity_count"],19)
        self.assertEqual(d["fields_with_source_table_cell_and_vendor"],63)
        self.assertEqual(d["previous_unqualified_exact_currency_mismatch_count"],5)
        self.assertEqual(d["false_vintage_conflicts_removed_by_thousand_yuan_reporting_precision"],2)
        self.assertEqual(d["confirmed_after_source_unit_rounding_review"],3)
        self.assertEqual(d["live_buy_eligibility"],"NOT_AUTHORIZED")
        self.assertFalse(d["independent_untouched_oos_validated"])

    def test_two_688185_one_thousand_yuan_integer_fields_are_rounding_not_restatement(self):
        fields={x["original_source_row_field"]:x for x in self.result["field_results"]
                if x["security_id"]=="SSE:688185"}
        for key in ("revenue_yuan","parent_net_profit_yuan"):
            p=fields[key]
            self.assertEqual(p["original_reporting_quantum"],"1000")
            self.assertEqual(p["status"],
                             "COMPATIBLE_WITH_ORIGINAL_REPORTING_PRECISION_NOT_VERSION_PROOF")
            self.assertLess(Decimal(p["absolute_difference_cny_or_percentage_points"]),
                            Decimal("500"))
            self.assertEqual(p["source_pdf_evidence"][0]["unit_evidence"],
                             "thousand_yuan")

    def test_three_remaining_real_disagreements_are_not_rounding_false_positives(self):
        rows={(x["security_id"],x["financial_field"]):x
              for x in self.result["remaining_review_issuer_field_pairs"]}
        self.assertEqual(set(rows),{
            ("SSE:600088","parent_net_profit_yuan"),
            ("SSE:600088","weighted_roe_pct"),
            ("SZSE:001896","parent_net_profit_yuan")})
        self.assertEqual(rows[("SSE:600088","parent_net_profit_yuan")]
                         ["unrounded_difference"],"380405.97")
        self.assertEqual(rows[("SSE:600088","weighted_roe_pct")]
                         ["unrounded_difference"],"0.09")
        self.assertEqual(rows[("SZSE:001896","parent_net_profit_yuan")]
                         ["unrounded_difference"],"-18939.52")
        self.assertEqual(rows[("SZSE:001896","parent_net_profit_yuan")]
                         ["reporting_quantum"],"0.01")

    def test_example_1000_yuan_reporting_precision_rounds_450_but_not_501(self):
        field={"financial_field":"revenue_yuan",
               "original_current_year_table_source_status":"UNIQUE_FISCAL_YEAR_TABLE_CELL_EXTRACTED",
               "original_current_year_table_value":"123000",
               "vendor_2026_source_value":"123450",
               "original_pdf_table_evidence":[{
                   "financial_field":"revenue_yuan","unit_evidence":"thousand_yuan",
                   "table_cell_numeric":"123","normalized_value":"123000"}]}
        self.assertEqual(source_quantum(field),Decimal("1000"))
        self.assertEqual(reconcile_field(field)["status"],
                         "COMPATIBLE_WITH_ORIGINAL_REPORTING_PRECISION_NOT_VERSION_PROOF")
        field["vendor_2026_source_value"]="123501"
        self.assertEqual(reconcile_field(field)["status"],
                         "DIFFERENCE_BEYOND_PUBLISHED_PRECISION_REQUIRES_SOURCE_REVIEW")

    def test_yearly_percentages_use_published_two_decimal_percentage_points(self):
        field={"financial_field":"revenue_growth_yoy_pct",
               "original_current_year_table_source_status":"UNIQUE_FISCAL_YEAR_TABLE_CELL_EXTRACTED",
               "original_current_year_table_value":"17.79",
               "vendor_2026_source_value":"17.789781004",
               "original_pdf_table_evidence":[{
                   "financial_field":"revenue_growth_yoy_pct",
                   "unit_evidence":"percentage_points",
                   "table_cell_numeric":"17.79","normalized_value":"17.79"}]}
        self.assertEqual(source_quantum(field),Decimal("0.01"))
        self.assertEqual(reconcile_field(field)["status"],
                         "COMPATIBLE_WITH_ORIGINAL_REPORTING_PRECISION_NOT_VERSION_PROOF")

    def test_tampered_unit_or_field_mapping_cannot_convert_wrong_value_to_match(self):
        field={"financial_field":"parent_net_profit_yuan",
               "original_current_year_table_source_status":"UNIQUE_FISCAL_YEAR_TABLE_CELL_EXTRACTED",
               "original_current_year_table_value":"123000",
               "vendor_2026_source_value":"123100",
               "original_pdf_table_evidence":[{
                   "financial_field":"parent_net_profit_yuan",
                   "unit_evidence":"yuan",
                   "table_cell_numeric":"123","normalized_value":"123000"}]}
        with self.assertRaisesRegex(ValueError,"PDF_SOURCE_CELL_DOES_NOT_MATCH"):
            reconcile_field(field)
        field["original_pdf_table_evidence"][0]["unit_evidence"]="thousand_yuan"
        field["original_pdf_table_evidence"][0]["financial_field"]="revenue_yuan"
        with self.assertRaisesRegex(ValueError,"PDF_EVIDENCE_WRONG_FINANCIAL_FIELD"):
            reconcile_field(field)

if __name__=="__main__":
    unittest.main()
