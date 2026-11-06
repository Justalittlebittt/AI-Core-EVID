"""Future-only synthetic tests for the 122/8/310 user-readable decision brief."""
import copy
import unittest
from datetime import datetime
from unittest.mock import patch

from test_v29_growth_forward_cohort import fake, FUTURE_NOW
from v29_growth_forward_cohort import evaluate as parent_evaluate
from v29_eight_pilot_outcome import evaluate as eight_evaluate
from v29_forward_maturity_decision_brief import brief, COMPLETE

def evidence(doc=None):
    doc=doc if doc is not None else fake()
    parent=parent_evaluate(doc,now=FUTURE_NOW)
    verdict={
        "schema":"V29_122_FROZEN_FORWARD_20TH_SESSION_EXIT_EVIDENCE_V1",
        "frozen_cohort_count":122,
        "fixed_entry_session":"2026-11-02",
        "fixed_exit_session":"2026-11-27",
        "quote_source_eligible_count":parent.get("computable_count",122),
        "benchmark_source_status":"OFFICIAL_H00300_ENTRY_AND_EXIT_VERIFIED",
        "source_bytes_sha256":doc["raw_outcome_sources_sha256"],
        "protocol_sha256":doc["protocol_sha256"],
        "outcome_evaluation":parent,
        "trade_authorized":False,
        "live_buy_eligibility":"NOT_AUTHORIZED"
    }
    return verdict,doc

class MaturityBriefTests(unittest.TestCase):
    def test_complete_positive_parent_and_real_frozen_eight_are_descriptive_only(self):
        verdict,doc=evidence()
        eight=eight_evaluate(doc,now=FUTURE_NOW)
        body=brief(verdict,doc,eight=eight,now=FUTURE_NOW)
        self.assertIn("+4.70%",body)
        self.assertIn("+9.70%",body)
        self.assertIn("NO ACTION",body)
        self.assertIn("资金加权",body)
        self.assertIn("尚未提供或尚未落盘",body)
        self.assertNotIn("建议买入",body)

    def test_negative_excess_does_not_become_paper_buy(self):
        doc=fake()
        for row in doc["securities"]:
            row["adjusted_exit_close"]=103.
        verdict,doc=evidence(doc)
        eight=eight_evaluate(doc,now=FUTURE_NOW)
        body=brief(verdict,doc,eight=eight,now=FUTURE_NOW)
        self.assertIn("-2.30%",body)
        self.assertIn("该时段落后",body)
        self.assertIn("NO ACTION",body)

    def test_incomplete_parent_refuses_to_show_subset_return_or_fake_alpha(self):
        doc=fake()
        doc["securities"][0]["adjusted_exit_close"]=None
        verdict,doc=evidence(doc)
        body=brief(verdict,doc,now=FUTURE_NOW)
        self.assertIn("未取得有效结果",body)
        self.assertIn("NO ACTION",body)
        with self.assertRaisesRegex(ValueError,"EIGHT_CANNOT_COMPLETE_BEFORE_PARENT"):
            brief(verdict,doc,eight={"status":"FAKE"},now=FUTURE_NOW)

    def test_parent_metric_tampering_cannot_change_decision_brief(self):
        verdict,doc=evidence()
        verdict["outcome_evaluation"]["mean_net_excess"]=0.90
        with self.assertRaisesRegex(ValueError,"PARENT_EVALUATION_RECOMPUTE_MISMATCH"):
            brief(verdict,doc,now=FUTURE_NOW)

    def test_wrong_source_hash_or_packet_authorization_is_rejected(self):
        verdict,doc=evidence()
        verdict["source_bytes_sha256"]="0"*64
        with self.assertRaisesRegex(ValueError,"PARENT_EVIDENCE_NOT_BOUND"):
            brief(verdict,doc,now=FUTURE_NOW)
        verdict,doc=evidence()
        verdict["trade_authorized"]=True
        with self.assertRaisesRegex(ValueError,"PARENT_EVIDENCE_NOT_BOUND"):
            brief(verdict,doc,now=FUTURE_NOW)

    def test_modified_eight_result_is_not_accepted_as_strategy_advantage(self):
        verdict,doc=evidence()
        eight=eight_evaluate(doc,now=FUTURE_NOW)
        eight["selected_eight_minus_parent_122"]=9.0
        with self.assertRaisesRegex(ValueError,"EIGHT_OUTCOME_NOT_REPRODUCIBLE"):
            brief(verdict,doc,eight=eight,now=FUTURE_NOW)

    def test_310_is_optional_but_must_be_recomputed_and_source_paired(self):
        verdict,doc=evidence()
        control={"status":COMPLETE,"fixed_entry_session":"2026-11-02",
                 "fixed_exit_session":"2026-11-27","selected_total":122,
                 "comparator_total":188,"selected_minus_comparator":0.015,
                 "selected_minus_clean_88":0.012}
        with patch("v29_forward_maturity_decision_brief.evaluate_control",return_value=copy.deepcopy(control)) as fn:
            content=brief(verdict,doc,control=control,control_prices={"synthetic":True},now=FUTURE_NOW)
        fn.assert_called_once()
        self.assertIn("+1.50%",content)
        self.assertIn("+1.20%",content)
        self.assertIn("NO ACTION",content)
        with self.assertRaisesRegex(ValueError,"CONTROL_PRICES_AND_RESULT_MUST_BE_PAIRED"):
            brief(verdict,doc,control=control,now=FUTURE_NOW)
        bad={**control,"selected_minus_clean_88":0.99}
        with patch("v29_forward_maturity_decision_brief.evaluate_control",return_value=control):
            with self.assertRaisesRegex(ValueError,"CONTROL_METRIC_NOT_REPRODUCIBLE"):
                brief(verdict,doc,control=bad,control_prices={"synthetic":True},now=FUTURE_NOW)

    def test_maturity_gate_prevents_early_rereading(self):
        verdict,doc=evidence()
        with self.assertRaisesRegex(ValueError,"FROZEN_OUTCOME_NOT_YET_MATURE"):
            brief(verdict,doc,now=datetime.fromisoformat("2026-11-06T15:00:00+08:00"))

if __name__=="__main__":
    unittest.main()
