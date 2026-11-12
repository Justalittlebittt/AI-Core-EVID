"""Synthetic only full-range SZSE source audit invariants; no science promotion."""
import copy
import unittest
from v294_szse_frozen_24_month_census import months, evaluate, fetch_page, collect, SIZES

def fixture():
    a={};b={}
    for start,end in months():
        one={}
        for size in SIZES:
            one[str(size)]={"range":[start,end],"size":size,
                  "complete":True,"ids":[start],"id_sha256":start,
                  "row_fingerprint":"exact:"+start,
                  "unique_count":1,"reported_totals":[1],"error":None}
        a[start]=copy.deepcopy(one);b[start]=copy.deepcopy(one)
    return [a,b]

class FrozenCensusTests(unittest.TestCase):
    def test_24_months_and_no_scientific_admission(self):
        x=evaluate(fixture())
        self.assertEqual(x["passed_months"],24)
        self.assertTrue(x["frozen_range_month_source_consistency_pass"])
        self.assertEqual(x["conditional_unique_union_count"],24)
        self.assertFalse(x["historical_full_range_scientifically_certified"])
        self.assertFalse(x["batch3_authorized"])
        self.assertFalse(x["batch4_authorized"])
        self.assertFalse(x["trading_authorized"])

    def test_conflicting_sources_fail_closed(self):
        for kind in ("incomplete","drift","total","cross_month"):
            with self.subTest(kind=kind):
                s=fixture()
                if kind=="incomplete":s[1]["2023-08-01"]["30"]["complete"]=False
                elif kind=="drift":s[1]["2023-08-01"]["50"]["id_sha256"]="not-equal"
                elif kind=="total":s[0]["2023-08-01"]["50"]["reported_totals"]=[2]
                elif kind=="cross_month":
                    for part in s:
                        for size in ("30","50"):
                            part["2023-09-01"][size]["ids"]=["2023-08-01"]
                self.assertFalse(evaluate(s)["frozen_range_month_source_consistency_pass"])

    def test_missing_month_prevents_source_census(self):
        a=fixture();a[1].pop("2024-12-01")
        with self.assertRaisesRegex(ValueError,"EXACT_TWO_FULL_MONTH_SESSIONS_REQUIRED"):
            evaluate(a)

if __name__=="__main__":
    unittest.main()
