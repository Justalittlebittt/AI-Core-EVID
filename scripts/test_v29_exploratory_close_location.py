"""Offline, synthetic correctness checks for precommitted close-location study."""
import copy
import sys
import unittest
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from v29_exploratory_close_location import evaluate_panel


def contract():
    return {
        "schema": "SYNTHETIC_CLOSE_LOCATION",
        "research_class": "NEW_EXPLORATORY_RETROSPECTIVE_ONLY_NONPRISTINE_OOS",
        "signal": {"minimum_signal_universe_size": 10},
        "population": {
            "first_signal_date": "2025-01-02",
            "last_signal_date": "2025-12-31",
        },
        "outcome": {"primary_horizon_joint_sessions": 5,
                    "cost_round_trip_fraction": 0.003},
        "test_plan": {
            "minimum_evaluated_days": 1,
            "minimum_selected_outcome_coverage": 0.9,
            "block_bootstrap": {
                "seed": 20261027, "replicates": 60,
                "consecutive_day_block_length": 2,
            },
        },
    }


def dataset(missing_selected_target=False):
    calendar = [date(2025, 1, 2) + timedelta(days=i) for i in range(8)]
    rows = []
    for i in range(10):
        sid = f"SSE:{600000+i}"
        for d in calendar[:2]:
            strong = i == 0
            rows.append({"canonical_security_id": sid, "bar_date": d,
                         "low": 90.0, "high": 110.0,
                         "close": 108.0 if strong else 100.0})
        for d in calendar[5:7]:
            if missing_selected_target and i == 0:
                continue
            rows.append({"canonical_security_id": sid, "bar_date": d,
                         "low": 90.0, "high": 120.0,
                         "close": 118.8 if i == 0 else 100.0})
    return pd.DataFrame(rows), calendar


class CloseLocationTests(unittest.TestCase):
    def test_deterministic_top_decile_and_baseline(self):
        panel, calendar = dataset()
        got = evaluate_panel(panel, calendar, {}, contract())
        self.assertEqual(got["evaluated_signal_days"], 2)
        self.assertEqual(got["selected_events"], 2)
        self.assertEqual(got["selected_outcomes"], 2)
        self.assertEqual(got["selected_outcome_coverage"], 1.0)
        self.assertAlmostEqual(got["mean_selected_net_return"], 0.097)
        self.assertAlmostEqual(got["mean_market_gross_return"], 0.01)
        self.assertAlmostEqual(got["primary_mean_excess_vs_market"], 0.087)
        self.assertFalse(got["trade_authorized"])
        self.assertEqual(len(got["daily"][0]["selected_ids_sha256"]), 64)

    def test_future_target_prices_cannot_affect_selections(self):
        panel, calendar = dataset()
        first = evaluate_panel(panel, calendar, {}, contract())
        panel2 = panel.copy()
        panel2.loc[panel2["bar_date"].isin(calendar[5:7]), "close"] *= 1.03
        second = evaluate_panel(panel2, calendar, {}, contract())
        self.assertEqual([x["selected_ids_sha256"] for x in first["daily"]],
                         [x["selected_ids_sha256"] for x in second["daily"]])
        self.assertNotEqual(first["primary_mean_excess_vs_market"],
                            second["primary_mean_excess_vs_market"])

    def test_missing_selected_outcomes_reduce_coverage_not_filled(self):
        panel, calendar = dataset(missing_selected_target=True)
        got = evaluate_panel(panel, calendar, {}, contract())
        self.assertEqual(got["selected_outcomes"], 0)
        self.assertEqual(got["selected_outcome_coverage"], 0.0)
        self.assertFalse(got["trade_authorized"])
        self.assertFalse(got["minimum_information_floor_pass"])

    def test_duplicate_security_date_rejected(self):
        panel, calendar = dataset()
        repeated = pd.concat([panel, panel.iloc[[0]]], ignore_index=True)
        with self.assertRaisesRegex(ValueError, "DUPLICATE_SECURITY_DATE"):
            evaluate_panel(repeated, calendar, {}, contract())

    def test_zero_range_excluded_without_invented_price(self):
        panel, calendar = dataset()
        panel.loc[panel["canonical_security_id"] == "SSE:600001", "high"] = 90.0
        got = evaluate_panel(panel, calendar, {}, contract())
        self.assertGreater(got["invalid_signal_bars_excluded"], 0)
        self.assertFalse(got["trade_authorized"])


if __name__ == "__main__":
    unittest.main()
