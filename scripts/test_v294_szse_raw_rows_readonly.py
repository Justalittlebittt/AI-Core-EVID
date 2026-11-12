"""Offline row-materialization gate against canonical source fingerprints."""
import copy
import unittest
from v294_szse_raw_rows_readonly import reconcile,digest_rows
from v294_szse_frozen_24_month_census import months

def fixture():
    refs={};s={}
    for start,end in months():
        rows=[{"ann_id":start,"publication_day":start,"title":"Synthetic",
               "exchange_relative_path":"/disc/synthetic.pdf",
               "exchange_publish_time_raw":start+" 00:00:00",
               "exchange_stock_codes":["002667"]}]
        fp=digest_rows(rows)
        refs[start]={"ids":[start],"row_fingerprint":fp,"reported_totals":[1]}
        s[start]={"range":[start,end],"rows":rows,"row_fingerprint":fp,
                  "official_totals":[1],"complete":True,"error":None}
    return refs,[copy.deepcopy(s),copy.deepcopy(s)]

class SourceRowsTests(unittest.TestCase):
    def test_24_months_stable_but_no_frozen_science_admission(self):
        reference,sessions=fixture()
        outcome=reconcile(reference,sessions)
        self.assertTrue(outcome["full_source_row_reference_match"])
        self.assertEqual(len(outcome["rows"]),24)
        self.assertFalse(outcome["cninfo_temporal_provenance_verified"])
        self.assertFalse(outcome["cninfo_pdf_locator_compatible"])
        self.assertFalse(outcome["original_batch3_source_substitution_authorized"])
        self.assertFalse(outcome["protected_outcomes_consumed"])

    def test_source_contradictions_remove_all_exported_rows(self):
        for kind in ("id","hash","total","incomplete"):
            with self.subTest(kind=kind):
                refs,sessions=fixture()
                row=sessions[1]["2023-08-01"]
                if kind=="id":row["rows"][0]["ann_id"]="different"
                if kind=="hash":row["row_fingerprint"]="wrong"
                if kind=="total":row["official_totals"]=[2]
                if kind=="incomplete":row["complete"]=False
                result=reconcile(refs,sessions)
                self.assertFalse(result["full_source_row_reference_match"])
                self.assertEqual(result["rows"],[])

    def test_missing_period_blocks(self):
        refs,sessions=fixture()
        del refs["2023-01-01"]
        with self.assertRaisesRegex(ValueError,"TWO_COMPLETE_SESSIONS_AND_24_MONTH_REFERENCES_REQUIRED"):
            reconcile(refs,sessions)

if __name__=="__main__":
    unittest.main()
