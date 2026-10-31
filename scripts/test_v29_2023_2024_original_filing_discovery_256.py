"""Source-only checks for two pre-frozen historical original-report cohorts."""
import copy
import hashlib
import json
import sys
import tempfile
import unittest
from datetime import datetime,timezone,timedelta
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parent))
from v29_2023_2024_original_filing_discovery_256 import (
    SOURCE_SCHEMA,load_frozen_frames,choose_originals,locate,collect,
)

CHINA=timezone(timedelta(hours=8))

def notice(code,year,day,document_id,title=None):
    return {
        "secCode":code,
        "announcementTitle":title if title is not None else f"{year-1}年年度报告",
        "adjunctUrl":f"finalpage/{day}/{document_id}.PDF",
        "announcementTime":int(datetime.fromisoformat(day+"T10:30:00").replace(
            tzinfo=CHINA).timestamp()*1000),
    }

def mock_source(path,fields):
    if path=="information/topSearch/query":
        code=fields["keyWord"]
        result=[{"code":code,"orgId":"9900012345"}]
        return result,json.dumps(result).encode()
    if path=="hisAnnouncement/query":
        code,org=fields["stock"].split(",")
        year=int(fields["seDate"][:4])
        assert org=="9900012345"
        assert fields["category"]=="category_ndbg_szsh"
        if year not in (2023,2024):
            raise ValueError("wrong year")
        one=notice(code,year,f"{year}-04-27","1234567890")
        response={"announcements":[one],"totalRecordNum":1,
                  "totalpages":1,"hasMore":False}
        return response,json.dumps(response,ensure_ascii=False).encode()
    raise AssertionError("unexpected endpoint")

class EarlierFilingSourceTests(unittest.TestCase):
    def test_real_2023_2024_frozen_two_128_samples(self):
        d,source=load_frozen_frames()
        self.assertEqual(len(d["cohorts"]),2)
        self.assertEqual([x["population_count"] for x in d["cohorts"]],[4905,5096])
        self.assertEqual([len(x["selected_ids"]) for x in d["cohorts"]],[128,128])
        self.assertEqual(len(source),64)

    def test_year_specific_original_full_report_not_summary_restated_or_other_issuer(self):
        rows=[
            notice("688416",2023,"2023-04-27","100"),
            notice("688416",2023,"2023-04-27","101",title="2022年年度报告摘要"),
            notice("688416",2023,"2023-04-27","102",title="2022年年度报告（修订版）"),
            notice("688416",2023,"2023-04-27","103",title="2021年年度报告"),
            notice("688416",2023,"2023-04-27","104",title="2023年年度报告"),
            notice("688419",2023,"2023-04-27","105"),
            notice("688416",2024,"2024-04-27","106",title="2022年年度报告"),
        ]
        selected=choose_originals(rows,"SSE:688416",2022,2023)
        self.assertEqual(len(selected),1)
        self.assertTrue(selected[0]["original_pdf_url"].endswith("/100.PDF"))

    def test_correct_actual_org_id_and_expected_report_year(self):
        result,raw=locate("SZSE:002177",2022,2023,mock_source)
        self.assertEqual(result["status"],"ONE_ORIGINAL_ANNUAL_PDF_CANDIDATE")
        self.assertEqual(result["chosen"]["notice_day"],"2023-04-27")
        self.assertEqual(result["org_id"],"9900012345")
        self.assertEqual(len(raw),2)
        result2,raw2=locate("SSE:688031",2023,2024,mock_source)
        self.assertEqual(result2["chosen"]["notice_day"],"2024-04-27")

    def test_duplicate_same_day_stays_ambiguous(self):
        def ambiguous(path,fields):
            if path=="information/topSearch/query":
                return mock_source(path,fields)
            code=fields["stock"].split(",")[0]
            objs=[notice(code,2023,"2023-04-27","100"),
                  notice(code,2023,"2023-04-27","101")]
            response={"announcements":objs,"totalpages":1,"totalRecordNum":2,"hasMore":False}
            return response,json.dumps(response).encode()
        result,_=locate("SSE:688416",2022,2023,ambiguous)
        self.assertEqual(result["status"],
                         "SAME_DAY_MULTIPLE_ORIGINAL_CANDIDATES_NEEDS_PDF_IDENTITY_CHECK")
        self.assertIsNone(result["chosen"])

    def test_source_failure_is_not_mistaken_for_no_original_filing(self):
        def unavailable(path,fields):
            raise OSError("blocked")
        r,raw=locate("SSE:688416",2022,2023,unavailable)
        self.assertEqual(r["status"],"SOURCE_QUERY_ERROR_NOT_PROOF_OF_NO_REPORT")
        self.assertEqual(raw,{})

    def test_two_sample_years_retain_each_security_and_raw_api_sha(self):
        with tempfile.TemporaryDirectory() as d:
            dest=Path(d)/"raw_and_results"
            report=collect(dest,limit_per_cohort=3,request=mock_source,sleep_seconds=0)
            self.assertEqual(report["schema"],SOURCE_SCHEMA)
            self.assertEqual(len(report["cohorts"]),2)
            self.assertEqual([x["single_source_candidate_count"] for x in report["cohorts"]],[3,3])
            self.assertEqual([x["attempted_count"] for x in report["cohorts"]],[3,3])
            self.assertTrue(all(len(c["rows"])==3 for c in report["cohorts"]))
            self.assertTrue(all(r["api_response_sha256"] for c in report["cohorts"] for r in c["rows"]))
            self.assertEqual(report["raw_api_zip_sha256"],
                             hashlib.sha256((dest/"RAW_CNINFO_2023_2024_RESPONSES.zip").read_bytes()).hexdigest())
            self.assertFalse(report["pristine_chronological_oos_validated"])
            self.assertEqual(report["live_buy_eligibility"],"NOT_AUTHORIZED")
            with self.assertRaisesRegex(ValueError,"REFUSE_TO_OVERWRITE"):
                collect(dest,limit_per_cohort=3,request=mock_source,sleep_seconds=0)

if __name__=="__main__":
    unittest.main()
