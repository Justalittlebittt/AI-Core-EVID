"""Tests source-only historical frames, never inferred alpha or BUY."""
import copy
import hashlib
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parent))
from v29_prior_year_original_source_cohorts import select_cohorts,COHORTS,SAMPLE_SIZE
from v29_historical_universe_sampling import select_membership_frame

class PriorSourceFrames(unittest.TestCase):
    def test_real_2023_2024_asof_frames_are_distinct_and_have_full_denominators(self):
        d=select_cohorts()
        self.assertEqual(len(d["cohorts"]),2)
        self.assertEqual([x["expected_issuer_publication_year"] for x in d["cohorts"]],
                         [2023,2024])
        self.assertEqual([x["asof_membership_date"] for x in d["cohorts"]],
                         ["2023-01-03","2024-01-02"])
        for x in d["cohorts"]:
            self.assertEqual(x["selected_count"],SAMPLE_SIZE)
            self.assertEqual(len(set(x["selected_ids"])),SAMPLE_SIZE)
            self.assertGreater(x["population_count"],SAMPLE_SIZE)
            self.assertEqual(x["selected_ids_sha256"],hashlib.sha256(
                ("\n".join(x["selected_ids"])+"\n").encode()).hexdigest())
            self.assertTrue(x["future_delisting_NOT_used_for_membership_or_sampling"])
        self.assertNotEqual(d["cohorts"][0]["selected_ids_sha256"],
                            d["cohorts"][1]["selected_ids_sha256"])
        self.assertFalse(d["chronological_untouched_oos_certified"])
        self.assertFalse(d["source_only_sample_no_outcome_data_read"] is False)
        self.assertEqual(d["live_buy_eligibility"],"NOT_AUTHORIZED")

    def test_shuffling_source_does_not_change_historical_sample(self):
        base=[
            {"canonical_security_id":"SSE:600001","official_list_date":"2015-01-01","official_delist_date":""},
            {"canonical_security_id":"SZSE:000001","official_list_date":"2000-01-01","official_delist_date":""},
            {"canonical_security_id":"SSE:600002","official_list_date":"2016-01-01","official_delist_date":""},
        ]
        for _,day,_,_,seed in COHORTS:
            a=select_membership_frame(base,frame_date=day,seed=seed,sample_size=2)
            b=select_membership_frame(list(reversed(base)),frame_date=day,seed=seed,sample_size=2)
            self.assertEqual(a,b)

    def test_future_delisting_changes_neither_frozen_sample_2023_nor_2024(self):
        base=[
            {"canonical_security_id":f"SSE:{n:06d}","official_list_date":"2017-01-01",
             "official_delist_date":""} for n in range(100,110)]
        for _,day,_,_,seed in COHORTS:
            a=select_membership_frame(base,frame_date=day,seed=seed,sample_size=4)
            changed=copy.deepcopy(base)
            changed[0]["official_delist_date"]="2025-10-20"
            changed[1]["2026_stock_return"]=-0.999
            changed[2]["fy2024_profit"]=10**15
            b=select_membership_frame(changed,frame_date=day,seed=seed,sample_size=4)
            self.assertEqual(a,b)

if __name__=="__main__":
    unittest.main()
