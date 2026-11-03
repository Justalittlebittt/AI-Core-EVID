"""Price benchmark is distinct from H00300 TR and retains exit-ST rows."""
import unittest
from v29_historical_original15_market_comparator import (
    CODE,compute,index_by_year,read_source
)

def fixture():
    rows=[{"security_id":"SZSE:000070","fiscal_year":2023,
           "entry_session":"2024-04-29","twentieth_session":"2024-05-29",
           "status":"INCOMPLETE_NEVER_DROP"}]
    stock={"quotes":{"2023|SZSE:000070":{"forward_adjusted":[
        {"date":"2024-04-29","adjustflag":"2","close":"8.14"},
        {"date":"2024-05-29","adjustflag":"2","close":"4.55"}]}}}
    idx={"2023":[],"2024":[{"date":"2024-04-29","code":CODE,"close":"4000"},
                              {"date":"2024-05-29","code":CODE,"close":"4040"}]}
    return {"rows":rows},stock,idx

class Tests(unittest.TestCase):
    def test_fifteen_still_bound_to_archived_price_receipt(self):
        d,stock=read_source()
        self.assertEqual(len(d["rows"]),15)
        self.assertEqual(d["paired_count"],13)
        self.assertEqual(len(stock["quotes"]),15)

    def test_realistic_negative_exit_st_is_retained_as_sensitivity(self):
        d,stock,index=fixture()
        x=compute(d,stock,index)[0]
        self.assertFalse(x["original_nonST_filter_pass"])
        self.assertEqual(x["status"],"HISTORICAL_PRICE_ONLY_COMPARISON")
        self.assertAlmostEqual(x["csi300_price_index_return"],.01)
        self.assertAlmostEqual(x["stock_minus_csi300_price_index_sensitivity"],
                               4.55/8.14-1-.003-.01)
        self.assertFalse(x["total_return_benchmark_used"])

    def test_missing_index_is_not_filled_or_dropped(self):
        d,stock,index=fixture()
        index["2024"].pop()
        x=compute(d,stock,index)[0]
        self.assertEqual(x["status"],"INCOMPLETE_NO_SUBSTITUTION")
        self.assertIsNone(x["stock_minus_csi300_price_index_sensitivity"])

    def test_csi300_index_code_is_not_substitutable(self):
        d,stock,index=fixture()
        index["2024"][0]["code"]="sh.H00300"
        with self.assertRaisesRegex(ValueError,"INDEX_CODE_YEAR_OR_DUPLICATE_CHANGED"):
            compute(d,stock,index)

if __name__=="__main__":
    unittest.main()
