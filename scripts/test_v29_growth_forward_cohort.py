"""Synthetic-unit-only tests. No historical/future real returns are consulted."""
import copy
import json
import sys
import tempfile
import unittest
from datetime import date,datetime,timedelta,timezone
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parent))
from v29_growth_forward_cohort import readiness,evaluate,load_registered,PROTOCOL,ROOT

def fake():
    spec,ids,digest=load_registered()
    days=[]
    day=date(2026,11,2)
    while len(days)<20:
        if day.weekday()<5:
            days.append(day.isoformat())
        day+=timedelta(days=1)
    return {"schema":"V29_FORWARD_COHORT_OBSERVED_OUTCOMES_V1",
      "experiment_id":spec["experiment_id"],"protocol_sha256":digest,
      "verified_exchange_sessions":days,"calendar_source":"SYNTHETIC_TEST_CALENDAR_NOT_EXCHANGE",
      "calendar_sha256":"a"*64,
      "raw_outcome_sources_sha256":"b"*64,
      "capture_timestamp":"2026-12-02T16:30:00+08:00",
      "benchmark":{"security_id":"H00300.CSI","source_sha256":"c"*64,
         "entry_total_return_index_close":100.,"exit_total_return_index_close":105.},
      "securities":[{"canonical_security_id":sid,
          "adjusted_entry_close":100., "adjusted_exit_close":110.,
          "entry_tradeable_at_reference_close":True,
          "exit_tradeable_at_reference_close":True,
          "corporate_actions_and_dividends_adjusted":True,
          "raw_quote_sha256":"d"*64} for sid in ids]}

FUTURE_NOW=datetime(2026,12,15,tzinfo=timezone.utc)

class CohortForwardTests(unittest.TestCase):
    def test_real_manifest_bound_and_without_future_results(self):
        doc=readiness()
        self.assertEqual(doc["cohort_count"],122)
        self.assertEqual(doc["strategy_evidence_strength"],"INSUFFICIENT")
        self.assertEqual(doc["live_buy_eligibility"],"NOT_AUTHORIZED")
        self.assertEqual(doc["status"],"FROZEN_NO_FUTURE_OUTCOME_ADMITTED")

    def test_synthetic_numbers_are_arithmetic_not_buy(self):
        result=evaluate(fake(),now=FUTURE_NOW)
        self.assertEqual(result["status"],"ONE_EPISODE_DESCRIPTIVE_NOT_BUY_EVIDENCE")
        self.assertAlmostEqual(result["mean_gross"],.10)
        self.assertAlmostEqual(result["mean_net"],.097)
        self.assertAlmostEqual(result["mean_net_excess"],.047)
        self.assertEqual(result["outperforming_name_fraction"],1)
        self.assertFalse(result["strategy_validated"])
        self.assertEqual(result["live_buy_eligibility"],"NOT_AUTHORIZED")

    def test_mature_only_after_real_exit_time(self):
        with self.assertRaisesRegex(ValueError,"FUTURE_OUTCOME_NOT_YET_OBSERVABLE"):
            evaluate(fake(),now=datetime(2026,10,30,10,tzinfo=timezone.utc))

    def test_single_missing_quote_refuses_primary_metric(self):
        d=fake()
        d["securities"][0]["adjusted_exit_close"]=None
        r=evaluate(d,now=FUTURE_NOW)
        self.assertEqual(r["status"],"INCOMPLETE_NEVER_DROP_NAMES")
        self.assertIsNone(r["mean_net_excess"])
        self.assertEqual(r["unavailable_count"],1)

    def test_suspended_trade_refuses_primary_metric(self):
        d=fake()
        d["securities"][1]["entry_tradeable_at_reference_close"]=False
        r=evaluate(d,now=FUTURE_NOW)
        self.assertIsNone(r["mean_net_excess"])
        self.assertEqual(r["unavailable_count"],1)

    def test_missing_one_name_is_incomplete_not_outperforming(self):
        d=fake()
        d["securities"].pop()
        r=evaluate(d,now=FUTURE_NOW)
        self.assertEqual(r["observed_count"],121)
        self.assertIsNone(r["mean_net_excess"])

    def test_duplicate_name_rejected(self):
        d=fake()
        d["securities"][1]=copy.deepcopy(d["securities"][0])
        with self.assertRaisesRegex(ValueError,"DUPLICATE_OR_OUT_OF_UNIVERSE"):
            evaluate(d,now=FUTURE_NOW)

    def test_wrong_benchmark_is_rejected(self):
        d=fake()
        d["benchmark"]["security_id"]="000300.SH"
        with self.assertRaisesRegex(ValueError,"INVALID_TOTAL_RETURN_BENCHMARK"):
            evaluate(d,now=FUTURE_NOW)

    def test_fake_exit_before_freeze_is_rejected(self):
        d=fake()
        d["verified_exchange_sessions"]=[(date(2026,9,1)+timedelta(days=i)).isoformat() for i in range(20)]
        with self.assertRaisesRegex(ValueError,"FUTURE_CALENDAR_INVALID"):
            evaluate(d,now=FUTURE_NOW)

    def test_incomplete_calendar_is_rejected(self):
        d=fake()
        d["verified_exchange_sessions"]=d["verified_exchange_sessions"][:19]
        with self.assertRaisesRegex(ValueError,"REQUIRES_EXACT_20"):
            evaluate(d,now=FUTURE_NOW)

    def test_protocol_vintage_mismatch_is_rejected(self):
        d=fake()
        d["protocol_sha256"]="0"*64
        with self.assertRaisesRegex(ValueError,"FUTURE_OUTCOME_IDENTITY_MISMATCH"):
            evaluate(d,now=FUTURE_NOW)

    def test_missing_provenance_rejected(self):
        d=fake()
        d["raw_outcome_sources_sha256"]=""
        with self.assertRaisesRegex(ValueError,"CALENDAR_OR_SOURCE_NOT_BOUND"):
            evaluate(d,now=FUTURE_NOW)

    def test_invalid_price_rejected(self):
        d=fake()
        d["securities"][0]["adjusted_entry_close"]=0
        with self.assertRaisesRegex(ValueError,"INVALID_FINITE_POSITIVE_VALUE"):
            evaluate(d,now=FUTURE_NOW)

    def test_cost_precommitment_change_rejected(self):
        spec=json.loads(PROTOCOL.read_text(encoding="utf-8"))
        spec["costs"]["round_trip_fraction"]=0.
        with tempfile.TemporaryDirectory() as t:
            path=Path(t)/"experiment.json"
            path.write_text(json.dumps(spec),encoding="utf-8")
            with self.assertRaisesRegex(ValueError,"REGISTERED_EXPERIMENT_CHANGED"):
                load_registered(path,ROOT)

if __name__=="__main__":
    unittest.main()
