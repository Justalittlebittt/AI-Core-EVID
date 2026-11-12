"""Fail-closed unit tests of source-only bounded ECONNRESET retry."""
import unittest
from v294_szse_independent_day_list_retry_v2 import fetch_one,validate,compare

DOC={"announceCount":1,"data":[{"title":"威领股份：关于控股股东部分股份质押的公告",
"publishTime":"2023-08-31 00:00:00",
"attachPath":"/disc/disk03/finalpage/2023-08-30/sample.PDF",
"annId":1217706310,"secCode":["002667"]}]}

class Response:
    status=200
    def json(self): return DOC
class Request:
    def __init__(self, outcomes):self.outcomes=iter(outcomes);self.calls=0
    def post(self,*args,**kwargs):
        self.calls+=1
        x=next(self.outcomes)
        if isinstance(x,Exception):raise x
        return x
class Tests(unittest.TestCase):
    def test_single_reset_then_complete_source(self):
        req=Request([RuntimeError("read ECONNRESET"),Response()])
        x=fetch_one(req,{"seDate":["2023-08-31","2023-08-31"]},20)
        self.assertEqual(req.calls,2)
        self.assertTrue(x["single_page_closed"])
        self.assertEqual(x["transport_attempts"],2)

    def test_two_resets_still_block(self):
        req=Request([RuntimeError("ECONNRESET"),RuntimeError("ECONNRESET")])
        x=fetch_one(req,{},20)
        self.assertEqual(req.calls,2)
        self.assertFalse(x["single_page_closed"])

    def test_valid_but_wrong_or_incomplete_response_is_not_retried(self):
        class WrongResponse:
            status=200
            def json(self):return {"announceCount":0,"data":[]}
        req=Request([WrongResponse(),Response()])
        x=fetch_one(req,{},30)
        self.assertEqual(req.calls,1)
        self.assertFalse(x["single_page_closed"])

    def test_exact_official_issuer_array_and_no_research_promotion(self):
        x=validate(DOC,30)
        self.assertTrue(x["single_page_closed"])
        out=compare([{20:validate(DOC,20),30:validate(DOC,30)},
                     {20:validate(DOC,20),30:validate(DOC,30)}])
        self.assertTrue(out["independent_szse_day_consistent"])
        self.assertFalse(out["full_2023_2024_issuer_census_certified"])
        self.assertFalse(out["batch3_authorized"])
        self.assertFalse(out["batch4_authorized"])
if __name__=="__main__":unittest.main()
