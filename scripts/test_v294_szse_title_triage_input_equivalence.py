"""Synthetic title-variant tests using the actual frozen triage implementation."""
import unittest
from v294_szse_title_triage_input_equivalence import analyze

def make():
    rows=[]
    for i in range(486):
        name="鞍重股份" if i<198 else "威领股份"
        suffix="关于召开 2022 年度业绩说明会的公告" if i==10 else "关于子公司业务合同进展的公告"
        rows.append({"ann_id":str(1200000000+i),"publication_day":"2023-04-14",
                     "title":name+"："+suffix,"exchange_stock_codes":["002667"]})
    return rows

class TriageVariantTests(unittest.TestCase):
    def test_real_frozen_title_semantics_can_disagree(self):
        out=analyze(make())
        self.assertEqual(out["scoped_rows"],486)
        self.assertEqual(out["input_variant_disagreement_count"],1)
        disputed=out["input_variant_disagreements"][0]
        self.assertEqual(disputed["variants"]["raw"]["triage_state"],"MATERIALIZE_CANDIDATE")
        self.assertEqual(disputed["variants"]["with_historic_name"]["triage_state"],"MATERIALIZE_CANDIDATE")
        self.assertEqual(disputed["variants"]["strip_prefix_separator"]["triage_state"],"SKIP_LOW_INFORMATION_ADMIN_NOTICE")
        self.assertFalse(out["original_batch3_triage_source_migration_authorized"])
        self.assertFalse(out["price_or_return_data_consumed"])

    def test_missing_or_cross_issuer_rows_block(self):
        with self.assertRaisesRegex(ValueError,"EXACT_486_UNIQUE_OFFICIAL_ROWS_REQUIRED"):
            analyze(make()[:485])
        wrong=make()
        wrong[0]["exchange_stock_codes"]=["000001"]
        with self.assertRaisesRegex(ValueError,"SOURCE_TITLE_IDENTITY_PREFIX_BLOCK"):
            analyze(wrong)
        no_known_prefix=make()
        no_known_prefix[1]["title"]="其他名称：关于子公司业务合同进展的公告"
        with self.assertRaisesRegex(ValueError,"SOURCE_TITLE_IDENTITY_PREFIX_BLOCK"):
            analyze(no_known_prefix)

if __name__=="__main__":
    unittest.main()
