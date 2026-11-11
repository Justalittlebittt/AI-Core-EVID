"""Synthetic-only no-promotion checks for the one-ID source locator."""
import copy
import unittest
from v294_cninfo_target_id_locator import TARGET, evaluate


def fixture():
    metadata={"announcement_id":TARGET,"announcement_time":"1692633600000",
              "official_observed_day":"2023-08-22",
              "original_pdf_path_day":"2023-08-22",
              "official_relative_pdf_path":"finalpage/2023-08-22/"+TARGET+".pdf",
              "sec_code":"002667","sec_name":"example","announcement_title":"test"}
    page={"target_present":True,"target_rows":[metadata]}
    return [[copy.deepcopy(page),copy.deepcopy(page)],
            [copy.deepcopy(page),copy.deepcopy(page)]]


class TargetLocatorTests(unittest.TestCase):
    def test_same_official_record_is_only_metadata_not_scientific_completeness(self):
        v=evaluate(fixture())
        self.assertTrue(v["source_metadata_reconciled"])
        self.assertEqual(v["verified_metadata"]["official_observed_day"],"2023-08-22")
        self.assertFalse(v["historical_full_range_complete"])
        self.assertFalse(v["batch3_aggregation_authorized"])
        self.assertFalse(v["batch4_authorized"])
        self.assertFalse(v["outcome_data_consumed"])

    def test_partial_missing_drift_and_outside_range_block(self):
        for change in ("missing","drift","path_date","outside"):
            with self.subTest(change=change):
                data=fixture()
                if change=="missing":
                    data[1][0]["target_present"]=False
                    data[1][0]["target_rows"]=[]
                elif change=="drift":
                    data[1][1]["target_rows"][0]["sec_code"]="000000"
                elif change=="path_date":
                    for sess in data:
                        for p in sess:
                            p["target_rows"][0]["original_pdf_path_day"]="2023-08-23"
                elif change=="outside":
                    for sess in data:
                        for p in sess:
                            p["target_rows"][0]["official_observed_day"]="2025-01-01"
                            p["target_rows"][0]["original_pdf_path_day"]="2025-01-01"
                self.assertFalse(evaluate(data)["source_metadata_reconciled"])

    def test_exact_two_sessions(self):
        with self.assertRaisesRegex(ValueError,"TWO_COMPLETE_SOURCE_SESSIONS_REQUIRED"):
            evaluate(fixture()[:1])


if __name__=="__main__":
    unittest.main()
