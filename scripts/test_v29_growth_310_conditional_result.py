import csv
import hashlib
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from v29_growth_310_conditional_result import evaluate, load_fixed, maturity, digest_ids

NOW = datetime(2026, 11, 27, 20, 0, tzinfo=timezone.utc)


class ConditionalResultTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root/"research").mkdir()
        self.ids = [f"SSE:{600000+i:06}" for i in range(310)]
        self.selected = self.ids[:122]
        others = self.ids[122:]
        reg = {
          "schema":"V29_GROWTH_310_CONDITIONAL_COMPARATOR_PREOUTCOME_V1",
          "supplementary_observation":{"transaction_cost_round_trip_fraction":0.003},
          "frozen_identity":{
            "all_310_sorted_ids":self.ids,
            "all_310_sorted_linefeed_sha256":digest_ids(self.ids),
            "selected_122_authority":"research/122.md",
            "selected_122_original_order_linefeed_sha256":digest_ids(self.selected),
            "comparator_188_sorted_linefeed_sha256":digest_ids(others)
          }
        }
        (self.root/"research/V2.9_GROWTH_310_CONDITIONAL_CONTROL_PREOUTCOME_20261102.json").write_text(json.dumps(reg))
        (self.root/"research/122.md").write_text("## Canonical identities (122)\n```\n"+"\n".join(self.selected)+"\n```\n")
        with (self.root/"research/V2.9_GROWTH_310_PREOUTCOME_FINANCIAL_FRAME_20261102.csv").open("w",newline="") as f:
            w=csv.writer(f);w.writerow(("security_id","group"))
            for sid in self.ids:w.writerow((sid,"SELECTED_122" if sid in self.selected else "COMPARATOR_188"))
        with (self.root/"research/V2.9_GROWTH_310_PREOUTCOME_SOURCE_RISK_FLAGS_20261102.csv").open("w",newline="") as f:
            w=csv.writer(f);w.writerow(("security_id","frozen_selected_122","no_specified_risk_flags","numeric_growth_and_core_pass"))
            for i,sid in enumerate(self.ids):w.writerow((sid,int(i<122),int(i<210),int(i<122)))
        days = [datetime(2026,11,d).date().isoformat() for d in range(2,28) if datetime(2026,11,d).weekday()<5]
        (self.root/"research/V2.9_GROWTH_122_FORWARD_EVALUATION_PROTOCOL.json").write_text('{"synthetic":true}')
        self.parent = {"protocol_sha256":hashlib.sha256(b'{"synthetic":true}').hexdigest(),
                       "securities":[{"canonical_security_id":s} for s in self.selected],
                       "schema":"V29_FORWARD_COHORT_OBSERVED_OUTCOMES_V1",
                       "experiment_id":"V29_122_GROWTH_COHORT_PROSPECTIVE_20261030",
                       "verified_exchange_sessions":days}
        self.prices = {"schema":"V29_310_SAME_VINTAGE_CLOSE_PROXIES_V1",
                       "entry_session":"2026-11-02","exit_session":"2026-11-27",
                       "vendor":"BAOSTOCK", "adjustment":"FORWARD_ADJUSTED_SAME_EXIT_CAPTURE_VINTAGE",
                       "captured_at":"2026-11-27T18:00:00+08:00",
                       "raw_sources_sha256":"a"*64,
                       "securities":[{"security_id":sid,"entry_tradeable":True,"exit_tradeable":True,
                          "adjusted_for_corporate_actions":True,"raw_quote_sha256":"b"*64,
                          "adjusted_entry_close":100,"adjusted_exit_close":110 if i<122 else 105}
                          for i,sid in enumerate(self.ids)]}

    def test_real_preoutcome_repo_manifest_is_frozen_and_consistent(self):
        # Reuse committed 2026-10-30 source identities; do not access price outcomes.
        repo_root = Path(__file__).resolve().parents[1]
        registered, all_ids, selected, complement = load_fixed(repo_root)
        self.assertEqual((len(all_ids), len(selected), len(complement)), (310, 122, 188))
        self.assertTrue(selected.isdisjoint(complement))
        self.assertEqual(set(all_ids), selected | set(complement))
        self.assertEqual(
            registered["supplementary_observation"]["transaction_cost_round_trip_fraction"],
            0.003
        )

    def test_full_310_exact_difference(self):
        result = evaluate(self.prices,self.parent,self.root,NOW)
        self.assertEqual(result["status"],"ONE_EPISODE_DESCRIPTIVE_NOT_BUY_EVIDENCE")
        self.assertAlmostEqual(result["selected_minus_comparator"],.05)
        self.assertEqual(result["clean_88_comparator_total"],88)
        self.assertEqual(result["clean_88_computable"],88)
        self.assertAlmostEqual(result["mean_clean_88_net"],.047)
        self.assertAlmostEqual(result["selected_minus_clean_88"],.05)
        self.assertEqual(result["live_buy_eligibility"],"NOT_AUTHORIZED")

    def test_clean88_comparator_uses_same_original_flags_not_selected_100(self):
        # Distinguish original 122-vs-188 from secondary clean-only
        # comparison. No quotes from the real 20th-session experiment.
        for x in self.prices["securities"]:
            if x["security_id"] in self.ids[210:]:
                x["adjusted_exit_close"]=90
        result=evaluate(self.prices,self.parent,self.root,NOW)
        clean_expected=.097-.047
        combined_b=(88*.047+100*(-.103))/188
        self.assertAlmostEqual(result["selected_minus_clean_88"],clean_expected)
        self.assertAlmostEqual(result["selected_minus_comparator"],.097-combined_b)
        self.assertGreater(result["selected_minus_comparator"],result["selected_minus_clean_88"])
        self.assertEqual(result["clean_88_computable"],88)

    def test_missing_quotes_never_silently_disappear(self):
        self.prices["securities"][-1]["exit_tradeable"]=False
        result=evaluate(self.prices,self.parent,self.root,NOW)
        self.assertEqual(result["status"],"INSUFFICIENT_NEVER_DROP_NAMES")
        self.assertIsNone(result["selected_minus_comparator"])
        self.assertEqual(result["comparator_computable"],187)
        self.assertEqual(result["clean_88_computable"],88)
        self.assertIsNone(result["selected_minus_clean_88"])

    def test_cohort_mutation_rejected(self):
        self.prices["securities"][-1]["security_id"]="SSE:999999"
        with self.assertRaises(ValueError):evaluate(self.prices,self.parent,self.root,NOW)

    def test_premature_result_blocked(self):
        with self.assertRaisesRegex(ValueError,"NOT_YET_MATURE"):
            evaluate(self.prices,self.parent,self.root,datetime(2026,11,26,tzinfo=timezone.utc))

    def test_source_flag_mutation_rejected(self):
        p=self.root/"research/V2.9_GROWTH_310_PREOUTCOME_SOURCE_RISK_FLAGS_20261102.csv"
        s=p.read_text();p.write_text(s.replace("SSE:600000,1,1,1","SSE:600000,1,0,1"))
        with self.assertRaises(ValueError):load_fixed(self.root)


if __name__=="__main__":
    unittest.main()
