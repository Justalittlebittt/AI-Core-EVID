"""Offline regression for capture-bound deducted parent profit, never BUY."""
import hashlib
import json
import sys
import unittest
from copy import deepcopy
from pathlib import Path
from io import BytesIO
from urllib.parse import urlparse, parse_qs
sys.path.insert(0,str(Path(__file__).resolve().parent))
from v29_growth_core_earnings import enrich, fetch_page, _decode

def page(data):
    return json.dumps({"success":True,"result":{"count":len(data),"pages":1,"data":data}},ensure_ascii=False).encode()

def row(period, source, **kwargs):
    d={"SECUCODE":"600078.SH","SECURITY_CODE":"600078","ORG_CODE":"10002302",
       "NOTICE_DATE": "2026-10-28 00:00:00" if period=="2026-09-30" else "2026-08-18 00:00:00",
       "UPDATE_DATE": "2026-10-28 00:00:00" if period=="2026-09-30" else "2026-08-18 00:00:00"}
    if source=="summary":
        d.update({"REPORTDATE":period+" 00:00:00",
                  "PARENT_NETPROFIT":264724884.25 if period=="2026-09-30" else 100000000.})
    else:
        d.update({"REPORT_DATE":period+" 00:00:00",
                  "PARENTNETPROFIT":264724884.25 if period=="2026-09-30" else 100000000.,
                  "KCFJCXSYJLR":259509358.65 if period=="2026-09-30" else 95000000.,
                  "KCFJCXSYJLRTZ":1037.})
    d.update(kwargs)
    return d

def setup():
    q3=page([row("2026-09-30","summary")])
    h1=page([row("2026-06-30","summary")])
    r={"schema":"AI_CORE_EVID_GROWTH_RESEARCH_REVIEW_V1",
       "live_buy_eligibility":"NOT_AUTHORIZED",
       "latest_period":"2026-09-30","prior_period":"2026-06-30",
       "notice_cutoff_exclusive":"2026-10-30",
       "latest_source_page_hashes":[{"page":1,"sha256":hashlib.sha256(q3).hexdigest()}],
       "prior_source_page_hashes":[{"page":1,"sha256":hashlib.sha256(h1).hexdigest()}],
       "counts":{"both_positive_no_accounting_flags":1},
       "full_research_list":[{"security_id":"SSE:600078",
         "name":"澄星股份","review_tier":"A_BOTH_POSITIVE_NO_ACCOUNTING_FLAGS"}]}
    iq3=page([row("2026-09-30","core")])
    ih1=page([row("2026-06-30","core")])
    return r,[q3],[h1],[iq3],[ih1]

class CoreEarningsTests(unittest.TestCase):
    def test_realistic_coverage_and_no_buy(self):
        result=enrich(*setup())
        self.assertEqual(result["counts"]["both_core_profit_available"],1)
        self.assertEqual(result["counts"]["unmatched_or_missing"],0)
        self.assertEqual(result["quality_rows"][0]["q3_deducted_parent_profit_yuan"],259509358.65)
        self.assertGreater(result["quality_rows"][0]["standalone_q3_deducted_parent_profit_yuan_cumulative_difference"],0)
        self.assertFalse(result["return_or_alpha_validated"])
        self.assertEqual(result["live_buy_eligibility"],"NOT_AUTHORIZED")
    def test_parent_profit_source_conflict_is_explicit_unknown(self):
        r,l,p,q,h=setup()
        q=[page([row("2026-09-30","core",PARENTNETPROFIT=1.)])]
        out=enrich(r,l,p,q,h)
        self.assertEqual(out["counts"]["both_core_profit_available"],0)
        self.assertIn("Q3_PARENT_PROFIT_SOURCE_CONFLICT",out["quality_rows"][0]["review_flags"])
    def test_missing_core_profit_stays_missing(self):
        r,l,p,q,h=setup()
        q=[page([row("2026-09-30","core",KCFJCXSYJLR=None)])]
        out=enrich(r,l,p,q,h)
        self.assertIsNone(out["quality_rows"][0]["q3_deducted_parent_profit_yuan"])
        self.assertFalse(out["quality_rows"][0]["official_filings_independently_verified"])
    def test_cutoff_mismatch_blocks(self):
        r,l,p,q,h=setup()
        q=[page([row("2026-09-30","core",NOTICE_DATE="2026-10-30 00:00:00")])]
        with self.assertRaisesRegex(ValueError,"F10_NOTICE_OUTSIDE_CUTOFF"):
            enrich(r,l,p,q,h)
    def test_notice_mismatch_is_unknown(self):
        r,l,p,q,h=setup()
        q=[page([row("2026-09-30","core",NOTICE_DATE="2026-10-20 00:00:00")])]
        out=enrich(r,l,p,q,h)
        self.assertIn("Q3_NO_UNIQUE_IDENTITY_AND_DISCLOSURE_MATCH",out["quality_rows"][0]["review_flags"])
    def test_duplication_is_never_silently_selected(self):
        r,l,p,q,h=setup()
        q=[page([row("2026-09-30","core"),row("2026-09-30","core")])]
        out=enrich(r,l,p,q,h)
        self.assertEqual(out["counts"]["both_periods_matched"],0)
    def test_pages_changed_blocks_entire_capture(self):
        r,l,p,q,h=setup()
        o=json.loads(q[0]);o["result"]["count"]=2
        with self.assertRaisesRegex(ValueError,"F10_SOURCE_PAGINATION_INCOMPLETE"):
            enrich(r,l,p,[json.dumps(o).encode()],h)
    def test_org_mismatch_is_not_accepted(self):
        r,l,p,q,h=setup()
        q=[page([row("2026-09-30","core",ORG_CODE="WRONG")])]
        out=enrich(r,l,p,q,h)
        self.assertEqual(out["counts"]["unmatched_or_missing"],1)
    def test_requested_dates_are_bound(self):
        observed={}
        def opener(req, timeout):
            observed.update(parse_qs(urlparse(req.full_url).query))
            return BytesIO(b"{}")
        fetch_page("2026-09-30","2026-10-30",1,opener)
        self.assertIn("(NOTICE_DATE<'2026-10-30')",observed["filter"][0])
        self.assertEqual(observed["pageSize"],["500"])
    def test_negative_core_profit_flag(self):
        r,l,p,q,h=setup()
        q=[page([row("2026-09-30","core",KCFJCXSYJLR=-2.)])]
        o=enrich(r,l,p,q,h)
        self.assertEqual(o["counts"]["latest_core_profit_nonpositive"],1)
        self.assertEqual(o["counts"]["standalone_q3_core_profit_nonpositive"],1)
if __name__=="__main__":
    unittest.main()
