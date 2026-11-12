"""Offline row-materialization gate against canonical source fingerprints."""
import copy
import unittest
from v294_szse_raw_rows_readonly import reconcile,digest_rows
from v294_szse_frozen_24_month_census import months

def fixture():
    refs={};s={}
    for idx,(start,end) in enumerate(months()):
        count=26 if idx==23 else 20
        rows=[{"ann_id":f"{start}-synthetic-{i:03d}","publication_day":start,
               "title":"Synthetic","exchange_relative_path":"/disc/synthetic.pdf",
               "exchange_publish_time_raw":start+" 00:00:00",
               "exchange_stock_codes":["002667"]} for i in range(count)]
        fp=digest_rows(rows)
        refs[start]={"ids":[r["ann_id"] for r in rows],
                     "row_fingerprint":fp,"reported_totals":[count]}
        s[start]={"range":[start,end],"rows":rows,"row_fingerprint":fp,
                  "official_totals":[count],"complete":True,"error":None}
    return refs,[copy.deepcopy(s),copy.deepcopy(s)]

class SourceRowsTests(unittest.TestCase):
    def test_24_months_stable_but_no_frozen_science_admission(self):
        reference,sessions=fixture()
        outcome=reconcile(reference,sessions)
        self.assertTrue(outcome["full_source_row_reference_match"])
        self.assertEqual(len(outcome["rows"]),486)
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
