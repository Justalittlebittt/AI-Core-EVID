"""No-network invariants for new experimental hypothesis."""
import json
import sys
import unittest
from datetime import date
from pathlib import Path
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from v29_exploratory_opening_gap import evaluate_panel

CONTRACT = json.loads((Path(__file__).resolve().parents[1] / "research/EXPLORATORY_OPENING_GAP_V1.json").read_text())


def fixture(missing_target=False):
    calendar = [date.fromisoformat(s) for s in ["2025-01-02", "2025-01-03", "2025-01-06", "2025-01-07", "2025-01-08", "2025-01-09", "2025-01-10"]]
    records = []
    for n in range(100):
        for i, d in enumerate(calendar):
            if missing_target and i == 6:
                continue
            close = 100.0 + i + (n * 0.001)
            opening = close if i != 1 else 95.0 + n * 0.10
            records.append({"canonical_security_id": f"SZSE:{n:06d}",
                            "bar_date": d, "open": opening, "close": close})
    return pd.DataFrame(records), calendar, {d: 100.0 + i for i, d in enumerate(calendar)}


class StudyTests(unittest.TestCase):
    def test_precommitted_experiment_produces_no_buy_signal(self):
        df, calendar, benchmark = fixture()
        result = evaluate_panel(df, calendar, benchmark, CONTRACT)
        self.assertEqual(result["study_status"], "DESCRIPTIVE_RETROSPECTIVE_NOT_TRADING_AUTHORIZED")
        self.assertTrue(result["no_trade_authorization"])
        self.assertEqual(result["evidence_strength"], "UNSCORED_PENDING_THRESHOLD_CONTRACT")
        self.assertEqual(result["days_evaluated"], 1)
        self.assertEqual(result["selected_events"], 10)

    def test_missing_target_never_shifts_to_different_date(self):
        df, calendar, benchmark = fixture(missing_target=True)
        with self.assertRaisesRegex(RuntimeError, "NO_EVALUABLE_DATES"):
            evaluate_panel(df, calendar, benchmark, CONTRACT)

    def test_duplicate_price_bar_fails(self):
        df, calendar, benchmark = fixture()
        with self.assertRaisesRegex(ValueError, "DUPLICATE_SECURITY_DATE"):
            evaluate_panel(pd.concat([df, df.head(1)]), calendar, benchmark, CONTRACT)


if __name__ == "__main__":
    unittest.main()
