"""Historical factor admission regression checks, no network or market outcomes."""
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from v29_historical_factor_admission import FINAL, RECEIPT, assess_factor_admission


class AdmissionTests(unittest.TestCase):
    def test_frozen_real_result_blocks_candidate_promotion(self):
        result = assess_factor_admission()
        self.assertEqual(result["factors_tested"], 9)
        self.assertEqual(result["factors_promoted"], 0)
        self.assertEqual(result["research_candidate_admission"], "BLOCKED_NO_PROMOTED_FACTOR")
        self.assertEqual(result["live_buy_eligibility"], "NOT_AUTHORIZED")

    def check_modified(self, section, key, value):
        with tempfile.TemporaryDirectory() as d:
            f = json.loads(FINAL.read_text(encoding="utf-8"))
            r = json.loads(RECEIPT.read_text(encoding="utf-8"))
            (f if section == "final" else r)[key] = value
            fp, rp = Path(d) / "final.json", Path(d) / "receipt.json"
            fp.write_text(json.dumps(f), encoding="utf-8")
            rp.write_text(json.dumps(r), encoding="utf-8")
            with self.assertRaises(ValueError):
                assess_factor_admission(fp, rp)

    def test_tampered_receipt_seal_fails_closed(self):
        self.check_modified("receipt", "promoted_count", 2)

    def test_mismatched_snapshot_identity_fails_closed(self):
        f = json.loads(FINAL.read_text(encoding="utf-8"))
        f["canonical_snapshot"]["panel_sha256"] = "0" * 64
        self.check_modified("final", "canonical_snapshot", f["canonical_snapshot"])

    def test_unexpected_live_authorization_fails_closed(self):
        f = json.loads(FINAL.read_text(encoding="utf-8"))
        f["governance"]["live_authorized"] = True
        self.check_modified("final", "governance", f["governance"])


if __name__ == "__main__":
    unittest.main()
