"""Offline pre-entry source checks, no post-freeze market quotes or future outcomes."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parent))
from v29_forward122_preentry_source_check import (
    REFERENCE_DAY,collect,parse_total_return,inspect_reference_quotes,
    fetch_total_return,baostock_code
)

class FakeResult:
    error_code="0"
    error_msg=""
    def __init__(self,fields,rows):
        self.fields=fields.split(",")
        self.rows=rows
        self.i=0
    def next(self):
        self.i+=1
        return self.i<=len(self.rows)
    def get_row_data(self):
        r=self.rows[self.i-1]
        return [str(r.get(f,"")) for f in self.fields]

class FakeBS:
    def __init__(self):
        self.requests=[]
    def login(self):return FakeResult("date",[])
    def logout(self):pass
    def query_history_k_data_plus(self,code,fields,**kw):
        self.requests.append((code,fields,kw))
        assert kw["start_date"]==REFERENCE_DAY==kw["end_date"]
        assert kw["adjustflag"] in ("2","3")
        row={"date":REFERENCE_DAY,"code":code,"close":"33.5",
             "adjustflag":kw["adjustflag"],"tradestatus":"1",
             "isST":"0","volume":"1000","amount":"100000"}
        return FakeResult(fields,[row])

def index_stub():
    return {"source":"CSINDEX_OFFICIAL_INDEX_PERF","requested_index":"H00300.CSI",
            "benchmark_source_status":"OFFICIAL_H00300_PRE_FREEZE_REFERENCE_BAR_VERIFIED",
            "reference_close":5555.0},b'{"data":[]}'

class Future122ReadinessTests(unittest.TestCase):
    def test_official_total_return_only_not_csi300_price(self):
        ok={"data":[["2026-10-30","H00300","沪深300全收益","s","e","a","b","c","d",5555.0]]}
        x=parse_total_return(json.dumps(ok).encode())
        self.assertEqual(x["requested_index"],"H00300.CSI")
        self.assertEqual(x["reference_close"],5555.0)
        price={"data":[["2026-10-30","000300","沪深300","s","e","a","b","c","d",5555.0]]}
        with self.assertRaisesRegex(ValueError,"NOT_CSI300_TOTAL_RETURN_IDENTITY"):
            parse_total_return(json.dumps(price).encode())

    def test_future_bar_and_wrong_identity_rejected(self):
        invalid={"data":[["2026-11-02","H00300","沪深300全收益","s","e","a","b","c","d",5555.0]]}
        with self.assertRaisesRegex(ValueError,"OUTSIDE_ALLOWED_PRE_FREEZE_WINDOW"):
            parse_total_return(json.dumps(invalid).encode())
        with self.assertRaisesRegex(ValueError,"CSINDEX_TOTAL_RETURN_RESPONSE_SCHEMA_INVALID"):
            parse_total_return(b'<html>Blocked</html>')

    def test_old_day_quote_suspension_st_and_zero_volume_only_descriptive(self):
        code="sh.601965"
        b={"date":REFERENCE_DAY,"code":code,"adjustflag":"3","close":"20",
           "tradestatus":"1","isST":"1","volume":"100","amount":"2000"}
        adj={**b,"adjustflag":"2"}
        x=inspect_reference_quotes("SSE:601965",[b],[adj])
        self.assertFalse(x["reference_valid_both_price_versions"])
        self.assertEqual(x["unadjusted"]["status"],
                         "REFERENCE_BAR_ST_SUSPENSION_OR_VOLUME_UNCERTAIN")
        b={**b,"isST":"0","volume":"0"}
        adj={**adj,"isST":"0","volume":"0"}
        self.assertFalse(inspect_reference_quotes("SSE:601965",[b],[adj])
                         ["reference_valid_both_price_versions"])

    def test_no_future_data_requested_even_if_research_invoked_later(self):
        provider=FakeBS()
        r=collect(provider,limit=4,index_fetch=index_stub)
        self.assertEqual(r["frozen_cohort_count"],122)
        self.assertEqual(r["attempted_count"],4)
        self.assertEqual(r["stock_reference_bar_both_versions_ok"],4)
        self.assertEqual(len(provider.requests),8)
        self.assertTrue(all(q[2]["start_date"]==REFERENCE_DAY and
                            q[2]["end_date"]==REFERENCE_DAY
                            for q in provider.requests))
        self.assertFalse(r["future_sessions_queried"])
        self.assertFalse(r["prospective_122_price_outcomes_ready"])
        self.assertEqual(r["live_buy_eligibility"],"NOT_AUTHORIZED")

    def test_unverified_benchmark_does_not_get_price_index_fallback(self):
        provider=FakeBS()
        def unavailable():
            return {"source":"CSINDEX_OFFICIAL_INDEX_PERF",
                    "requested_index":"H00300.CSI",
                    "benchmark_source_status":"UNVERIFIED_OFFICIAL_TOTAL_RETURN_SOURCE",
                    "reason":"simulated_source_error"},None
        r=collect(provider,limit=4,index_fetch=unavailable)
        self.assertEqual(r["stock_reference_bar_both_versions_ok"],4)
        self.assertFalse(r["benchmark_type_price_index_substitution_allowed"])
        self.assertEqual(r["benchmark"]["benchmark_source_status"],
                         "UNVERIFIED_OFFICIAL_TOTAL_RETURN_SOURCE")
        self.assertFalse(r["prospective_122_price_outcomes_ready"])

if __name__=="__main__":
    unittest.main()
