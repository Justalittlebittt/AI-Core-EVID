"""Synthetic-only fail-closed direct-day source consistency contract tests."""
import copy
import unittest
from v294_cninfo_direct_day_identity import DAY, TARGET, evaluate


def make():
    row={"id":TARGET,"local_date":DAY,"pdf_path_day":DAY,
         "pdf_path":"finalpage/2023-08-31/"+TARGET+".PDF",
         "stock_code":"002667","short_name":"威领股份",
         "title":"关于控股股东部分股份质押的公告","timestamp":"1693411200000"}
    def run(sz):
        return {"page_size":sz,"reported_totals":[2],
                "page_counts":[2],"raw_count":2,"distinct_count":2,
                "duplicate_ids":[],"ids":["a",TARGET],
                "target_rows":[row],"errors":[],"closed":True}
    return [{30:copy.deepcopy(run(30)),20:copy.deepcopy(run(20))}
            for _ in range(2)]


class DirectDayTests(unittest.TestCase):
    def test_consistent_two_source_sessions_are_not_historical_admission(self):
        out=evaluate(make())
        self.assertTrue(out["direct_day_technical_consistency_pass"])
        self.assertEqual(out["target_verified_metadata"]["local_date"],DAY)
        self.assertFalse(out["historical_full_range_complete"])
        self.assertFalse(out["batch3_aggregation_authorized"])
        self.assertFalse(out["batch4_authorized"])
        self.assertFalse(out["outcomes_consumed"])

    def test_all_inconsistencies_block(self):
        for kind in ("duplicate","id_drift","total_drift","metadata_drift","missing_target"):
            with self.subTest(kind=kind):
                x=make()
                if kind=="duplicate":x[1][20]["closed"]=False
                if kind=="id_drift":x[1][20]["ids"]=["b",TARGET]
                if kind=="total_drift":x[1][30]["reported_totals"]=[3]
                if kind=="metadata_drift":x[0][20]["target_rows"][0]["title"]="different"
                if kind=="missing_target":x[1][20]["target_rows"]=[]
                self.assertFalse(evaluate(x)["direct_day_technical_consistency_pass"])

    def test_session_requirements(self):
        with self.assertRaisesRegex(ValueError,"EXACT_TWO_SESSIONS_TWO_PAGE_SIZES_REQUIRED"):
            evaluate(make()[:1])


if __name__=="__main__":
    unittest.main()
