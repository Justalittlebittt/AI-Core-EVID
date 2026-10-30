"""Offline quality audit tests; no financial provider calls or trading."""
import hashlib
import json
import sys
import unittest
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from v29_growth_raw_quality_audit import audit


def raw(period, **changes):
    data = {
        "SECURITY_CODE": "600000", "SECUCODE": "600000.SH", "ORG_CODE": "123456",
        "REPORTDATE": period+" 00:00:00",
        "NOTICE_DATE": ("2026-10-20" if period == "2026-09-30" else "2026-08-20")+" 00:00:00",
        "UPDATE_DATE": ("2026-10-20" if period == "2026-09-30" else "2026-08-20")+" 00:00:00",
        "TOTAL_OPERATE_INCOME": 1000 if period == "2026-09-30" else 650,
        "PARENT_NETPROFIT": 100 if period == "2026-09-30" else 70,
        "BASIC_EPS": 1.2 if period == "2026-09-30" else 0.9,
        "DEDUCT_BASIC_EPS": None if period == "2026-09-30" else 0.8,
        "XSMLL": 22.0 if period == "2026-09-30" else 24.0
    }
    data.update(changes)
    return data


def page(*rows):
    return json.dumps({"success": True, "result": {
        "pages": 1, "count": len(rows), "data": list(rows)
    }}, ensure_ascii=False).encode()


def fixture(latest=None, prior=None):
    latest = latest or raw("2026-09-30")
    prior = prior or raw("2026-06-30")
    pages = [[page(latest)], [page(prior)]]
    review = {
        "schema": "AI_CORE_EVID_GROWTH_RESEARCH_REVIEW_V1",
        "live_buy_eligibility": "NOT_AUTHORIZED",
        "notice_cutoff_exclusive": "2026-10-30",
        "latest_period": "2026-09-30", "prior_period": "2026-06-30",
        "latest_source_page_hashes": [{
            "page": 1, "sha256": hashlib.sha256(pages[0][0]).hexdigest()
        }],
        "prior_source_page_hashes": [{
            "page": 1, "sha256": hashlib.sha256(pages[1][0]).hexdigest()
        }],
        "counts": {"both_positive_no_accounting_flags": 1},
        "full_research_list": [{
            "security_id": "SSE:600000", "name": "*ST示例",
            "review_tier": "A_BOTH_POSITIVE_NO_ACCOUNTING_FLAGS",
            "recent_notice_date": "2026-10-20"
        }]
    }
    return review, *pages


class QualityAuditTests(unittest.TestCase):
    def test_positive_quarter_quality_unknown_and_st_warned(self):
        result = audit(*fixture())
        self.assertEqual(result["counts"]["reviewed_a_tier"], 1)
        self.assertEqual(result["counts"]["latest_deduct_eps_missing"], 1)
        self.assertEqual(result["counts"]["st_name_warning"], 1)
        self.assertEqual(result["counts"]["cumulative_gross_margin_lower"], 1)
        self.assertEqual(result["quality_rows"][0]["quarter_parent_profit_yuan_cumulative_difference"], 30.)
        self.assertIn("Q3_DEDUCT_EPS_UNAVAILABLE_CANNOT_VERIFY_CORE_EARNINGS",
                      result["quality_rows"][0]["review_flags"])
        self.assertEqual(result["live_buy_eligibility"], "NOT_AUTHORIZED")
        self.assertFalse(result["strategy_validated"])

    def test_source_hash_mismatch_rejected(self):
        rev, q3, h1 = fixture()
        rev["latest_source_page_hashes"][0]["sha256"] = "0"*64
        with self.assertRaisesRegex(ValueError, "RAW_FINANCIAL_SOURCE_HASH_MISMATCH"):
            audit(rev, q3, h1)

    def test_issuer_id_change_rejected(self):
        obj = fixture(prior=raw("2026-06-30", ORG_CODE="other"))
        with self.assertRaisesRegex(ValueError, "MATERIAL_ISSUER_IDENTITY_MISMATCH"):
            audit(*obj)

    def test_after_cutoff_update_rejected(self):
        obj = fixture(latest=raw("2026-09-30", UPDATE_DATE="2026-10-30 00:00:00"))
        with self.assertRaisesRegex(ValueError, "SELECTED_SOURCE_REVISED_AFTER_CAPTURE_CUTOFF"):
            audit(*obj)

    def test_unrelated_late_update_does_not_block_selected_a_tier(self):
        r, q3, h1 = fixture()
        other = raw("2026-09-30", SECUCODE="600001.SH",
                    SECURITY_CODE="600001", ORG_CODE="OTHER",
                    UPDATE_DATE="2026-10-30 00:00:00")
        q3 = [page(raw("2026-09-30"), other)]
        r["latest_source_page_hashes"][0]["sha256"] = hashlib.sha256(q3[0]).hexdigest()
        out = audit(r, q3, h1)
        self.assertEqual(out["counts"]["reviewed_a_tier"], 1)

    def test_missing_raw_source_row_rejected(self):
        r, q3, h1 = fixture()
        r["full_research_list"][0]["security_id"] = "SSE:600001"
        with self.assertRaisesRegex(ValueError, "CANDIDATE_RAW_SOURCE_ROW_MISSING"):
            audit(r, q3, h1)

    def test_cumulative_delta_nonpositive_flag_not_buy(self):
        obj = fixture(prior=raw("2026-06-30", TOTAL_OPERATE_INCOME=1200, PARENT_NETPROFIT=140))
        result = audit(*obj)
        self.assertEqual(result["counts"]["quarter_revenue_nonpositive"], 1)
        self.assertEqual(result["counts"]["quarter_profit_nonpositive"], 1)
        self.assertEqual(result["quality_rows"][0]["buy_eligibility"], "NOT_AUTHORIZED")

    def test_available_deduct_eps_does_not_claim_full_certification(self):
        obj = fixture(latest=raw("2026-09-30", DEDUCT_BASIC_EPS=1.12, XSMLL=25.0))
        out = audit(*obj)
        self.assertEqual(out["counts"]["latest_deduct_eps_missing"], 0)
        self.assertEqual(out["counts"]["cumulative_gross_margin_lower"], 0)
        self.assertFalse(out["quality_rows"][0]["core_earnings_quality_verified"])


if __name__ == "__main__":
    unittest.main()
