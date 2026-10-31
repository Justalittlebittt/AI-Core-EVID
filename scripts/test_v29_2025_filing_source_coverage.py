"""Offline-only tests for FY2024 issuer filing source capture and fail-closed coverage."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import parse_qs

sys.path.insert(0, str(Path(__file__).resolve().parent))
from v29_2025_filing_source_coverage import (
    _annual_versions, _org_id, _pdf_capture, collect, evaluate_one,
    FIELDNAMES,
)

class Response:
    def __init__(self, raw):
        self.raw = raw
        self.offset = 0
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def read(self, limit):
        chunk = self.raw[self.offset:self.offset+limit]
        self.offset += len(chunk)
        return chunk

def fake_opener(request, timeout=None):
    if "hisAnnouncement/query" in request.full_url:
        q = parse_qs(request.data.decode("utf-8"))
        code = q["stock"][0][:6]
        events = [{
            "secCode": code, "announcementTitle": "甲公司：2024年年度报告摘要",
            "announcementTime": 1745424000000,
            "adjunctUrl": "finalpage/2025-04-24/1111111111.PDF",
        }, {
            "secCode": code, "announcementTitle": "甲公司：2024年年度报告",
            "announcementTime": 1745424000000,
            "adjunctUrl": "finalpage/2025-04-24/2222222222.PDF",
        }]
        return Response(json.dumps({"announcements": events, "totalpages": 1}).encode())
    if "static.cninfo.com.cn" in request.full_url:
        return Response(b"%PDF-1.4\nexample\n%%EOF\n")
    raise AssertionError("Unexpected network request " + request.full_url)

def blocked_opener(request, timeout=None):
    raise HTTPError(request.full_url, 403, "Forbidden", None, None)

class CoverageTests(unittest.TestCase):
    def test_fixed_id_org_mapping(self):
        self.assertEqual(_org_id("SSE:600001"), "gssh0600001")
        self.assertEqual(_org_id("SZSE:000001"), "gssz0000001")

    def test_only_original_full_report_not_summary(self):
        events = [{
            "secCode": "600001", "announcementTitle": "公司2024年年度报告摘要",
            "announcementTime": 1745424000000,
            "adjunctUrl": "finalpage/2025-04-24/1111111111.PDF",
        }, {
            "secCode": "600001", "announcementTitle": "公司2024年年度报告",
            "announcementTime": 1745424000000,
            "adjunctUrl": "finalpage/2025-04-24/2222222222.PDF",
        }]
        out = _annual_versions("SSE:600001", events)
        self.assertEqual(len(out), 1)
        self.assertTrue(out[0]["url"].endswith("2222222222.PDF"))
        self.assertEqual(out[0]["day"], "2025-04-24")

    def test_announcement_is_not_false_pdf_certification(self):
        row, raw = evaluate_one("SSE:600001", fake_opener)
        self.assertEqual(row["status"], "FULL_REPORT_METADATA_IDENTIFIED_NOT_PDF_CERTIFIED")
        self.assertFalse(row["source_vintage_verified_pit"])
        self.assertIsNone(row["pdf_sha256"])
        self.assertEqual(len(raw), 1)

    def test_full_pdf_header_trailer_and_sha_from_bytes(self):
        with tempfile.TemporaryDirectory() as t:
            path = Path(t) / "out.pdf"
            data = _pdf_capture("https://static.cninfo.com.cn/finalpage/2025-04-24/2222222222.PDF", path, fake_opener)
            self.assertTrue(path.exists())
            self.assertEqual(len(data["pdf_sha256"]), 64)
            self.assertEqual(data["pdf_bytes"], path.stat().st_size)

    def test_failed_provider_never_claims_missing_filing(self):
        row, raw = evaluate_one("SSE:600001", blocked_opener)
        self.assertEqual(row["status"], "QUERY_FAILED_NOT_PROOF_OF_ABSENCE")
        self.assertEqual(row["query_error"], "HTTP_403")
        self.assertEqual(raw, [])

    def test_first_six_fixed_sample_ids_and_failure_retention(self):
        with tempfile.TemporaryDirectory() as t:
            out = Path(t) / "capture"
            result = collect(out, limit=6, pdf_limit=2, opener=fake_opener)
            self.assertEqual(result["requested_issuer_count"], 6)
            self.assertEqual(result["metadata_identified"], 6)
            self.assertEqual(result["full_pdf_bytes_captured"], 2)
            self.assertEqual(result["source_attempt_is_complete_128"], False)
            self.assertEqual(result["live_buy_eligibility"], "NOT_AUTHORIZED")
            self.assertEqual(len(result["rows"]), 6)
            self.assertTrue((out/"coverage.csv").exists())
            self.assertTrue((out/"coverage.json").exists())
            with self.assertRaisesRegex(ValueError, "CANNOT_OVERWRITE"):
                collect(out, limit=6, pdf_limit=2, opener=fake_opener)

    def test_circuit_break_preserves_all_rows(self):
        with tempfile.TemporaryDirectory() as t:
            result = collect(Path(t)/"capture", limit=7, pdf_limit=0, opener=blocked_opener)
            self.assertEqual(result["requested_issuer_count"], 7)
            self.assertEqual(result["queried_issuers"], 4)
            self.assertEqual(result["failed_or_unresolved"], 7)
            self.assertEqual(result["rows"][4]["status"], "UNQUERIED_SOURCE_UNAVAILABLE_CIRCUIT_BREAK")
            self.assertEqual(result["metadata_identified"], 0)

if __name__ == "__main__":
    unittest.main()
