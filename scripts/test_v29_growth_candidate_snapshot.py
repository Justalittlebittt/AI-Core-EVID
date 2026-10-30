"""Offline first-slice tests: source identity, completeness, as-of and no BUY promotion."""
import json
import sys
import unittest
from io import BytesIO
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from v29_growth_candidate_snapshot import build_snapshot, fetch_page, collect

AT = "2026-10-30T04:00:00+00:00"


def row(**kw):
    d = {"SECUCODE": "600519.SH", "SECURITY_CODE": "600519",
         "SECURITY_NAME_ABBR": "test_fixture_not_market_fact",
         "REPORTDATE": "2026-09-30 00:00:00",
         "NOTICE_DATE": "2026-10-25 00:00:00",
         "TOTAL_OPERATE_INCOME": 1000.0, "PARENT_NETPROFIT": 120.0,
         "YSTZ": 14.0, "SJLTZ": 12.0, "MGJYXJJE": 1.2,
         "WEIGHTAVG_ROE": 9.0}
    d.update(kw)
    return d


def make_pages(*groups):
    count = sum(map(len, groups))
    return [json.dumps({"success": True, "result": {
        "count": count, "pages": len(groups), "data": group
    }}).encode() for group in groups]


class GrowthCandidateTests(unittest.TestCase):
    def test_candidate_is_descriptive_not_buy(self):
        result = build_snapshot("2026-09-30", make_pages([row()]), AT)
        self.assertEqual(result["candidate_count"], 1)
        self.assertEqual(result["candidates"][0]["security_id"], "SSE:600519")
        self.assertEqual(result["candidates"][0]["notice_date"], "2026-10-25")
        self.assertFalse(result["strategy_validated"])
        self.assertFalse(result["historical_replay_pit_certified"])
        self.assertEqual(result["live_buy_eligibility"], "NOT_AUTHORIZED")
        self.assertEqual(len(result["raw_page_hashes"][0]["sha256"]), 64)

    def test_negative_growth_not_selected(self):
        result = build_snapshot("2026-09-30", make_pages([row(SJLTZ=-2)]), AT)
        self.assertEqual(result["candidate_count"], 0)
        self.assertEqual(result["counts"]["not_positive_growth"], 1)

    def test_missing_notice_cannot_enter_candidate_list(self):
        result = build_snapshot("2026-09-30", make_pages([row(NOTICE_DATE=None)]), AT)
        self.assertEqual(result["candidate_count"], 0)
        self.assertEqual(result["counts"]["missing_notice"], 1)

    def test_future_notice_rejected(self):
        with self.assertRaisesRegex(ValueError, "FUTURE_DISCLOSURE_DATE"):
            build_snapshot("2026-09-30", make_pages([row(NOTICE_DATE="2026-11-05")]), AT)

    def test_missing_cashflow_is_flagged_not_inferred(self):
        result = build_snapshot("2026-09-30", make_pages([row(MGJYXJJE=None)]), AT)
        self.assertEqual(result["candidate_count"], 1)
        self.assertIn("CASH_FLOW_MISSING_OR_NONPOSITIVE",
                      result["candidates"][0]["review_flags"])

    def test_duplicate_security_and_partial_pages_block(self):
        with self.assertRaisesRegex(ValueError, "DUPLICATE_SECURITY_REPORT"):
            build_snapshot("2026-09-30", make_pages([row(), row()]), AT)
        with self.assertRaisesRegex(ValueError, "PROVIDER_PAGINATION_INCOMPLETE"):
            build_snapshot("2026-09-30", make_pages([row()], [
                row(SECUCODE="000001.SZ", SECURITY_CODE="000001")])[:1], AT)

    def test_b_share_excluded(self):
        result = build_snapshot("2026-09-30", make_pages([
            row(), row(SECUCODE="900901.SH", SECURITY_CODE="900901")]), AT)
        self.assertEqual(result["candidate_count"], 1)
        self.assertEqual(result["counts"]["non_a_share"], 1)

    def test_pagination_count_drift_blocks(self):
        p = make_pages([row()], [row(SECUCODE="000001.SZ", SECURITY_CODE="000001")])
        changed = json.loads(p[1])
        changed["result"]["count"] = 9
        with self.assertRaisesRegex(ValueError, "PROVIDER_PAGINATION_CHANGED"):
            build_snapshot("2026-09-30", [p[0], json.dumps(changed).encode()], AT)

    def test_report_date_and_timezone(self):
        with self.assertRaisesRegex(ValueError, "REPORT_PERIOD_IN_FUTURE"):
            build_snapshot("2026-12-31", make_pages([row()]), AT)
        with self.assertRaisesRegex(ValueError, "CAPTURE_TIME_REQUIRES_OFFSET"):
            build_snapshot("2026-09-30", make_pages([row()]), "2026-10-30T12:00:00")

    def test_disclosure_cutoff_is_bound_to_source_and_content(self):
        from v29_growth_candidate_snapshot import fetch_page
        rec = make_pages([row()])[0]
        seen = {}
        def opener(req, timeout):
            seen.update(parse_qs(urlparse(req.full_url).query))
            return BytesIO(rec)
        fetch_page("2026-09-30", 1, opener, notice_before="2026-10-30")
        self.assertIn("(NOTICE_DATE<'2026-10-30')", seen["filter"][0])
        result = build_snapshot("2026-09-30", [rec], AT, notice_before="2026-10-30")
        self.assertEqual(result["notice_cutoff_exclusive"], "2026-10-30")
        with self.assertRaisesRegex(ValueError, "DISCLOSURE_OUTSIDE_SNAPSHOT_CUTOFF"):
            build_snapshot("2026-09-30",
                           make_pages([row(NOTICE_DATE="2026-10-30")]),
                           AT, notice_before="2026-10-30")

    def test_provider_request_and_capture(self):
        page = make_pages([row()])[0]
        calls = []
        def opener(req, timeout):
            params = parse_qs(urlparse(req.full_url).query)
            calls.append((params, timeout))
            return BytesIO(page)
        result, raw = collect("2026-09-30", opener=opener)
        self.assertEqual(result["candidate_count"], 1)
        self.assertEqual(raw, [page])
        self.assertEqual(calls[0][0]["filter"], ["(REPORTDATE='2026-09-30')"])
        self.assertEqual(calls[0][1], 15)


if __name__ == "__main__":
    unittest.main()
