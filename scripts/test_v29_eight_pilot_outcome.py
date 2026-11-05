"""Synthetic-only maturity and frozen 8-vs-122 arithmetic regressions."""
import copy
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from test_v29_growth_forward_cohort import FUTURE_NOW, fake
from v29_eight_pilot_outcome import PILOT, evaluate

class FrozenEightTests(unittest.TestCase):
    def test_equal_parent_and_eight_under_identical_synthetic_returns(self):
        result=evaluate(fake(),now=FUTURE_NOW)
        self.assertEqual(result["status"],"ONE_EPISODE_EXPLORATORY_NOT_BUY_EVIDENCE")
        self.assertEqual(result["selected_count"],8)
        self.assertEqual(len(result["selected_eight_ids_in_frozen_rank_order"]),8)
        self.assertAlmostEqual(result["selected_eight_mean_net"],.097)
        self.assertAlmostEqual(result["selected_eight_minus_parent_122"],0)
        self.assertAlmostEqual(result["selected_eight_minus_H00300_total_return"],.047)
        self.assertEqual(result["live_buy_eligibility"],"NOT_AUTHORIZED")
        self.assertFalse(result["trade_authorized"])

    def test_subset_outperformance_is_not_parent_outperformance(self):
        outcome=fake()
        pick=evaluate(outcome,now=FUTURE_NOW)["selected_eight_ids_in_frozen_rank_order"][0]
        next(r for r in outcome["securities"] if r["canonical_security_id"]==pick)["adjusted_exit_close"]=120.
        result=evaluate(outcome,now=FUTURE_NOW)
        self.assertAlmostEqual(result["selected_eight_mean_net"],.1095)
        self.assertAlmostEqual(result["parent_122_mean_net"],.097+(.1/122))
        self.assertAlmostEqual(result["selected_eight_minus_parent_122"],.0125-.1/122)

    def test_real_sealed_20261102_entry_shares_and_capital_are_used(self):
        result=evaluate(fake(),now=FUTURE_NOW)
        budget=result["minimum_lot_entry_reference"]
        self.assertEqual(budget["actual_reference_session"],"2026-11-02")
        self.assertEqual(budget["min_lot_reference_notional_cny"],54558)
        self.assertEqual(len(budget["weights"]),8)
        self.assertTrue(all(x["shares"]==100 for x in budget["weights"]))
        self.assertAlmostEqual(sum(x["capital_weight"] for x in budget["weights"]),1)
        self.assertAlmostEqual(result["min_lot_weighted_net_proxy"],.097)
        self.assertAlmostEqual(result["min_lot_minus_equal_eight_net_proxy"],0)
        self.assertFalse(budget["tradeable_close_fill_proven"])
        self.assertFalse(result["trade_authorized"])

    def test_one_synthetic_winner_exposes_equal_weight_vs_actual_lot_difference(self):
        doc=fake()
        selected=evaluate(doc,now=FUTURE_NOW)["selected_eight_ids_in_frozen_rank_order"]
        next(r for r in doc["securities"] if r["canonical_security_id"]==selected[0])["adjusted_exit_close"]=120.
        result=evaluate(doc,now=FUTURE_NOW)
        weights=result["minimum_lot_entry_reference"]["weights"]
        self.assertAlmostEqual(result["selected_eight_mean_net"],.1095)
        self.assertAlmostEqual(result["min_lot_weighted_net_proxy"],.097+.1*weights[0]["capital_weight"])
        self.assertAlmostEqual(result["min_lot_minus_equal_eight_net_proxy"],
                               .1*(weights[0]["capital_weight"]-1/8))
        self.assertLess(result["min_lot_weighted_net_proxy"],result["selected_eight_mean_net"])
        self.assertTrue(result["min_lot_paper_proxy_not_broker_fill"])

    def test_incomplete_parent_does_not_create_subset_alpha(self):
        outcome=fake()
        outcome["securities"][0]["adjusted_exit_close"]=None
        result=evaluate(outcome,now=FUTURE_NOW)
        self.assertEqual(result["status"],"INSUFFICIENT_PARENT_122_NOT_COMPLETE")
        self.assertIsNone(result["selected_eight_mean_net"])
        self.assertIsNone(result["selected_eight_minus_parent_122"])
        self.assertIsNone(result["min_lot_weighted_net_proxy"])

    def test_immature_clock_blocks_synthetic_future_evidence(self):
        with self.assertRaisesRegex(ValueError,"FUTURE_OUTCOME_NOT_YET_OBSERVABLE"):
            evaluate(fake(),now=datetime(2026,11,3,12,tzinfo=timezone.utc))

    def test_modified_preoutcome_frozen_file_rejected_before_arithmetic(self):
        # Test the actual Git-blob seal without modifying the repository.
        from unittest.mock import patch
        import v29_eight_pilot_outcome as module
        with tempfile.TemporaryDirectory() as t:
            root=Path(t)
            target=root/PILOT.relative_to(module.ROOT)
            target.parent.mkdir(parents=True)
            target.write_bytes(PILOT.read_bytes()+b" ")
            with self.assertRaisesRegex(ValueError,"FROZEN_EIGHT_PREOUTCOME_BLOB_CHANGED"):
                evaluate(fake(),now=FUTURE_NOW,root=root)

    def test_price_index_substitution_rejected_by_parent(self):
        outcome=fake()
        outcome["benchmark"]["security_id"]="000300.SH"
        with self.assertRaisesRegex(ValueError,"INVALID_TOTAL_RETURN_BENCHMARK"):
            evaluate(outcome,now=FUTURE_NOW)

if __name__=="__main__":
    unittest.main()
