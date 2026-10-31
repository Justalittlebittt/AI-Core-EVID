"""Offline integrity tests for CNINFO FY2024 original-report source discovery."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from v29_original_report_discovery_128 import _match_originals, locate, collect
from v29_historical_universe_sampling import build_frame


def ann(code, title, day, doc, ts=1745452800000):
    return {"secCode": code, "announcementTitle": title,
            "adjunctUrl": f"finalpage/{day}/{doc}.PDF",
            "announcementTime": ts}


def fake_request(path, params):
    code = params.get("keyWord") or params["stock"][:6]
    if path == "information/topSearch/query":
        return ([{"code": code, "zwjc": "样例公司", "orgId": "9900001234"}],
                json.dumps({"probe":code,"type":"orgid"}).encode())
    if path == "hisAnnouncement/query":
        assert params["stock"] == code + ",9900001234"
        # fixed PDF date corresponds to UTC timestamp, normalize for controlled fixture
        obj={"announcements": [],"totalRecordNum":0,"hasMore":False,"totalpages":0}
        return obj,json.dumps(obj).encode()
    raise AssertionError("unexpected path")


class OriginalDiscoveryTests(unittest.TestCase):
    def test_real_canonical_title_excludes_summary_english_and_wrong_stock(self):
        rows = [
            ann("002493","2024年年度报告", "2025-04-24","1111"),
            ann("002493","2024年年度报告摘要", "2025-04-24","2222"),
            ann("002493","2024 Annual Report", "2025-04-24","3333"),
            ann("002494","2024年年度报告", "2025-04-24","4444"),
            ann("002493","2024年年度报告修订版","2025-04-24","5555"),
        ]
        result=_match_originals(rows,"002493")
        self.assertEqual(len(result),1)
        self.assertEqual(result[0]["document_id"],"1111")

    def test_correct_orgid_is_required_even_if_guess_looks_plausible(self):
        result, raw=locate("SSE:601009",fake_request)
        self.assertEqual(result["org_id"],"9900001234")
        self.assertEqual(result["status"],"NO_MATCHING_2024_FULL_REPORT_IN_SOURCE_QUERY")
        self.assertEqual(len(raw),2)

    def test_orgid_ambiguous_is_a_distinct_failure(self):
        def ambiguous(path, params):
            return ([{"code":"601009","orgId":"1"},{"code":"601009","orgId":"2"}],b"[]")
        result,raw=locate("SSE:601009",ambiguous)
        self.assertEqual(result["status"],"ORG_ID_UNRESOLVED_OR_AMBIGUOUS")
        self.assertEqual(sorted(result["org_candidates"]),["1","2"])

    def test_query_exception_not_misclassified_as_no_report(self):
        def raise_query(path,params):
            if path.endswith("query"):
                raise ValueError("SIMULATED_PROVIDER_SCHEMA_BREAK")
        result,raw=locate("SSE:601009",raise_query)
        self.assertEqual(result["status"],"SOURCE_QUERY_FAILED_NOT_PROOF_OF_NO_REPORT")
        self.assertEqual(result["error_type"],"ValueError")

    def test_discards_mismatched_document_timestamp(self):
        rows=[ann("601009","2024年年度报告","2025-04-25","1111")]
        self.assertEqual(_match_originals(rows,"601009"),[])

    def test_fixed_frame_retains_every_attempted_issuer_and_raw_hashes(self):
        frame=build_frame()
        self.assertEqual(len(frame["selected_ids"]),128)
        with tempfile.TemporaryDirectory() as d:
            dest=Path(d)/"capture"
            result=collect(dest,limit=5,request=fake_request,sleep_seconds=0)
            self.assertEqual(result["attempted_sample_count"],5)
            self.assertEqual(result["no_original_url_count"],5)
            self.assertEqual(result["query_failed_count"],0)
            self.assertEqual(result["original_pdf_binary_captured_count"],0)
            self.assertFalse(result["independent_oos_validated"])
            self.assertEqual(result["live_buy_eligibility"],"NOT_AUTHORIZED")
            self.assertTrue((dest/"RAW_CNINFO_RESPONSES.zip").exists())
            self.assertEqual(len(result["rows"]),5)
            self.assertTrue(all(x["raw_request_sha256"] for x in result["rows"]))
            with self.assertRaisesRegex(ValueError,"REFUSE_TO_OVERWRITE"):
                collect(dest,limit=5,request=fake_request,sleep_seconds=0)

if __name__=="__main__":
    unittest.main()
