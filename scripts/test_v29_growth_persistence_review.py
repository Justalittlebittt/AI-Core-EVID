"""Offline two-period financial research tests; no price/outcome data."""
import copy
import hashlib
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from v29_growth_persistence_review import compare

def snap(period, securities):
    rows = []
    for sid, kw in securities.items():
        rows.append({
            "security_id": sid, "name": "Example " + sid, "report_date": period,
            "notice_date": "2026-08-20" if period == "2026-06-30" else "2026-10-25",
            "revenue_yuan": 1000., "parent_profit_yuan": 100.,
            "revenue_yoy_pct": 12., "parent_profit_yoy_pct": 10.,
            "operating_cash_flow_per_share_yuan": 1., "roe_pct": 10.,
            "review_flags": [], "status": "RESEARCH_CANDIDATE_ONLY",
            "buy_eligibility": "NOT_AUTHORIZED",
            **kw,
        })
    return {
        "schema": "AI_CORE_EVID_GROWTH_CANDIDATE_SNAPSHOT_V1",
        "source": "UNOFFICIAL_EASTMONEY_FINANCIAL_AGGREGATE",
        "report_date": period, "captured_at": "2026-10-30T04:00:00+00:00",
        "raw_page_hashes": [{"page": 1, "sha256": "a" * 64, "rows": len(rows)}],
        "candidates": rows, "candidate_count": len(rows),
        "strategy_validated": False, "live_buy_eligibility": "NOT_AUTHORIZED",
    }


class GrowthReviewTests(unittest.TestCase):
    def setUp(self):
        self.recent = snap("2026-09-30", {
            "SZSE:000001": {},
            "SZSE:000002": {"review_flags": ["CASH_FLOW_MISSING_OR_NONPOSITIVE"]},
            "SZSE:000003": {},
            "SSE:600519": {},
        })
        self.earlier = snap("2026-06-30", {
            "SZSE:000001": {},
            "SZSE:000002": {},
            "SZSE:000003": {"parent_profit_yuan": 120.},
        })

    def test_persistence_with_flags_and_missing_prior(self):
        result = compare(self.recent, self.earlier)
        self.assertEqual(result["counts"], {
            "both_positive": 3,
            "both_positive_no_accounting_flags": 1,
            "both_positive_with_review_flags": 2,
            "prior_positive_not_observed": 1,
        })
        self.assertEqual(result["review_queue"][0]["security_id"], "SZSE:000001")
        self.assertEqual(result["review_queue"][-1]["security_id"], "SSE:600519")
        self.assertEqual(result["review_queue"][-1]["review_tier"],
                         "C_PRIOR_POSITIVE_NOT_OBSERVED")
        self.assertEqual(result["live_buy_eligibility"], "NOT_AUTHORIZED")
        self.assertFalse(result["strategy_validated"])

    def test_lower_cumulative_margin_is_flag_not_autoblock(self):
        result = compare(self.recent, self.earlier)
        r = {x["security_id"]: x for x in result["full_research_list"]}
        self.assertIn("CUMULATIVE_PARENT_NET_MARGIN_LOWER",
                      r["SZSE:000003"]["review_flags"])
        self.assertEqual(r["SZSE:000003"]["buy_eligibility"], "NOT_AUTHORIZED")

    def test_earlier_absence_is_not_negative_growth_claim(self):
        result = compare(self.recent, self.earlier)
        last = result["full_research_list"][-1]
        self.assertIsNone(last["profit_yoy_pct_prior"])
        self.assertIn("PRIOR_POSITIVE_UNOBSERVED_NOT_PROOF_OF_DECLINE", last["review_flags"])

    def test_non_ascending_period_rejected(self):
        with self.assertRaisesRegex(ValueError, "PRIOR_PERIOD_NOT_EARLIER"):
            compare(self.earlier, self.recent)

    def test_future_disclosure_rejected(self):
        bad = copy.deepcopy(self.recent)
        bad["candidates"][0]["notice_date"] = "2026-11-02"
        with self.assertRaisesRegex(ValueError, "FUTURE_DISCLOSURE_DATE"):
            compare(bad, self.earlier)

    def test_duplicate_candidate_and_count_conflict(self):
        bad = copy.deepcopy(self.recent)
        bad["candidates"].append(copy.deepcopy(bad["candidates"][0]))
        bad["candidate_count"] += 1
        with self.assertRaisesRegex(ValueError, "DUPLICATE_OR_MISMATCHED_CANDIDATE"):
            compare(bad, self.earlier)
        bad = copy.deepcopy(self.recent)
        bad["candidate_count"] -= 1
        with self.assertRaisesRegex(ValueError, "CANDIDATE_COUNT_MISMATCH"):
            compare(bad, self.earlier)

    def test_authority_and_source_mismatch_block(self):
        bad = copy.deepcopy(self.recent)
        bad["live_buy_eligibility"] = "ACTION_ELIGIBLE"
        with self.assertRaisesRegex(ValueError, "UNVERIFIED_FINANCIAL_SNAPSHOT_PROVENANCE|UNEXPECTED_TRADING_AUTHORITY"):
            compare(bad, self.earlier)
        bad = copy.deepcopy(self.recent)
        bad["source"] = "AUTHENTIC_EXCHANGE_VERIFIED"
        with self.assertRaisesRegex(ValueError, "UNVERIFIED_FINANCIAL_SNAPSHOT_PROVENANCE"):
            compare(bad, self.earlier)

    def test_queue_bound_and_provenance(self):
        result = compare(self.recent, self.earlier, 2)
        self.assertEqual(len(result["review_queue"]), 2)
        self.assertEqual(len(result["full_research_list"]), 4)
        self.assertEqual(result["latest_source_page_hashes"],
                         self.recent["raw_page_hashes"])
        self.assertTrue(result["overlapping_cumulative_periods_are_not_independent_validation"])
        for n in (0, 101):
            with self.assertRaisesRegex(ValueError, "INVALID_REVIEW_QUEUE_LIMIT"):
                compare(self.recent, self.earlier, n)

if __name__ == "__main__":
    unittest.main()
