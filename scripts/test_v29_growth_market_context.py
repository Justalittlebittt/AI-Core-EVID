"""Offline tests: only correctly timestamped matching quotes enrich research, never BUY."""
import json
import sys
import unittest
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from v29_growth_market_context import (
    enrich, capture_review, fetch_market_batch, BATCH_SIZE
)

AT = "2026-10-30T06:00:00+00:00"
TS = int(datetime.fromisoformat(AT).timestamp())


def research(n=2):
    ids = ["SSE:600519"] + [f"SZSE:{i:06d}" for i in range(1, n)]
    return {
        "schema": "AI_CORE_EVID_GROWTH_RESEARCH_REVIEW_V1",
        "latest_period": "2026-09-30",
        "notice_cutoff_exclusive": "2026-10-30",
        "latest_source_page_hashes": [{"page": 1, "sha256": "a"*64}],
        "prior_source_page_hashes": [{"page": 1, "sha256": "b"*64}],
        "counts": {"both_positive_no_accounting_flags": n},
        "strategy_validated": False,
        "live_buy_eligibility": "NOT_AUTHORIZED",
        "full_research_list": [{
            "security_id": sid, "name": "fixture-not-a-real-quote",
            "review_tier": "A_BOTH_POSITIVE_NO_ACCOUNTING_FLAGS",
            "recent_report_date": "2026-09-30",
            "recent_notice_date": "2026-10-29",
            "revenue_yoy_pct_latest": 22., "profit_yoy_pct_latest": 33.
        } for sid in ids]
    }


def quote(sid, ts=TS, **changes):
    exch, code = sid.split(":")
    obj = {"f12": code, "f13": 1 if exch == "SSE" else 0,
           "f14": "fixture", "f2": 10., "f6": 1000000.,
           "f9": 20., "f23": 2., "f124": ts, "f20": 1000000000.,
           "f21": 500000000., "f100": "test-sector"}
    obj.update(changes)
    return obj


def page(*rows):
    return json.dumps({"rc": 0, "data": {"total": len(rows), "diff": list(rows)}}).encode()


class MarketContextTests(unittest.TestCase):
    def test_full_matching_fresh_context_only(self):
        report = enrich(research(), [page(quote("SSE:600519"), quote("SZSE:000001"))], AT)
        self.assertEqual(report["counts"]["fresh_quote_context"], 2)
        self.assertEqual(report["counts"]["pe_positive_available"], 2)
        self.assertEqual(report["queue"][0]["market_context_status"], "FRESH_OBSERVED_VENDOR_QUOTE")
        self.assertEqual(report["queue"][0]["reported_pe_f9"], 20.)
        self.assertFalse(report["queue"][0]["valuation_fairness_established"])
        self.assertFalse(report["strategy_validated"])
        self.assertEqual(report["live_buy_eligibility"], "NOT_AUTHORIZED")
        self.assertEqual(len(report["raw_quote_batch_provenance"][0]["raw_sha256"]), 64)

    def test_missing_or_old_quote_is_unknown_not_safe(self):
        stale = TS - 8000
        result = enrich(research(), [page(quote("SSE:600519", stale))], AT)
        self.assertEqual(result["counts"]["quote_missing_or_stale"], 2)
        self.assertEqual(result["queue"][0]["market_context_status"], "STALE_VENDOR_QUOTE")
        self.assertIsNone(result["queue"][0]["last_indicated_price_yuan"])
        self.assertEqual(result["queue"][1]["market_context_status"], "MISSING_QUOTE")

    def test_future_quote_cannot_be_used(self):
        r = enrich(research(), [page(quote("SSE:600519", TS+20))], AT)
        self.assertEqual(r["queue"][0]["market_context_status"], "VENDOR_QUOTE_FROM_FUTURE")
        self.assertIsNone(r["queue"][0]["reported_pe_f9"])

    def test_negative_or_unknown_pe_is_not_low_valuation(self):
        r = enrich(research(), [page(quote("SSE:600519", f9=-4, f23="-"))], AT)
        item = r["queue"][0]
        self.assertIsNone(item["reported_pe_f9"])
        self.assertIsNone(item["reported_pb_f23"])
        self.assertIn("PE_NOT_USABLE_OR_NONPOSITIVE", item["review_flags"])

    def test_duplicate_or_unrequested_quote_blocks(self):
        with self.assertRaisesRegex(ValueError, "UNEXPECTED_OR_DUPLICATE_MARKET_SECURITY"):
            enrich(research(), [page(quote("SSE:600519"), quote("SSE:600519"))], AT)
        with self.assertRaisesRegex(ValueError, "UNEXPECTED_OR_DUPLICATE_MARKET_SECURITY"):
            enrich(research(), [page(quote("SSE:600519"), quote("SSE:600000"))], AT)

    def test_wrong_batch_count_and_source_block(self):
        with self.assertRaisesRegex(ValueError, "QUOTE_BATCH_COUNT_MISMATCH"):
            enrich(research(), [], AT)
        bad = research()
        bad["live_buy_eligibility"] = "ACTION_ELIGIBLE"
        with self.assertRaisesRegex(ValueError, "INVALID_RESEARCH_REVIEW"):
            enrich(bad, [page()], AT)
        bad = research()
        bad["counts"]["both_positive_no_accounting_flags"] = 3
        with self.assertRaisesRegex(ValueError, "A_TIER_COUNT_MISMATCH"):
            enrich(bad, [page()], AT)

    def test_31_securities_two_batches(self):
        rows = research(31)
        ids = sorted(x["security_id"] for x in rows["full_research_list"])
        raw = [page(*[quote(sid) for sid in ids[:BATCH_SIZE]]),
               page(*[quote(sid) for sid in ids[BATCH_SIZE:]])]
        outcome = enrich(rows, raw, AT)
        self.assertEqual(outcome["counts"]["fresh_quote_context"], 31)
        self.assertEqual(len(outcome["raw_quote_batch_provenance"]), 2)
        self.assertEqual(len(outcome["queue"]), 20)
        self.assertEqual(len(outcome["full_research_list"]), 31)

    def test_live_batch_request_identity(self):
        called = {}
        def opener(req, timeout):
            called.update(parse_qs(urlparse(req.full_url).query))
            self.assertEqual(timeout, 15)
            return BytesIO(page(quote("SSE:600519"), quote("SZSE:000001")))
        raw = fetch_market_batch(["SSE:600519","SZSE:000001"], opener)
        self.assertIsInstance(raw, bytes)
        self.assertEqual(called["secids"], ["1.600519,0.000001"])
        self.assertIn("f124", called["fields"][0])

    def test_invalid_timestamp_and_missing_provenance(self):
        with self.assertRaisesRegex(ValueError, "CAPTURE_TIME_REQUIRES_OFFSET"):
            enrich(research(), [page()], "2026-10-30T14:00:00")
        bad = research()
        bad["prior_source_page_hashes"] = []
        with self.assertRaisesRegex(ValueError, "FINANCIAL_SOURCE_UNBOUND"):
            enrich(bad, [page()], AT)


if __name__ == "__main__":
    unittest.main()
