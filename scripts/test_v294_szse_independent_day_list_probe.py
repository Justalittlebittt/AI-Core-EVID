"""Synthetic fail-closed tests of the separate SZSE direct-day probe."""
import copy
import unittest
from v294_szse_independent_day_list_probe import compare, validate

TARGET="关于控股股东部分股份质押的公告"
def make():
    record={"title":TARGET,"publishTime":"2023-08-31 00:00:00",
            "attachPath":"/disc/disk03/finalpage/2023-08-31/test.PDF",
            "annId":1217706310,"secCode":"002667"}
    return {"announceCount":1,"data":[record]}

class SZSEProbeTests(unittest.TestCase):
    def test_one_day_repeat_never_certifies_historical_full_range(self):
        a=validate(make(),20);b=validate(make(),30)
        out=compare([{20:a,30:b},{20:copy.deepcopy(a),30:copy.deepcopy(b)}])
        self.assertTrue(out["independent_szse_day_consistent"])
        self.assertFalse(out["full_2023_2024_issuer_census_certified"])
        self.assertFalse(out["batch3_authorized"])
        self.assertFalse(out["batch4_authorized"])
        self.assertFalse(out["protected_outcomes_consumed"])

    def test_wrong_day_duplicate_or_zero_count_block(self):
        for kind in ("wrong_day","wrong_code","missing","duplicate"):
            with self.subTest(kind=kind):
                payload=make()
                if kind=="wrong_day":payload["data"][0]["publishTime"]="2023-08-30 00:00:00"
                elif kind=="wrong_code":payload["data"][0]["secCode"]="009999"
                elif kind=="missing":payload["announceCount"]=0;payload["data"]=[]
                elif kind=="duplicate":payload["announceCount"]=2;payload["data"]*=2
                self.assertFalse(validate(payload,20)["single_page_closed"])

    def test_szse_official_sec_code_array_is_strictly_bound(self):
        data=make()
        data["data"][0]["secCode"]=["002667"]
        self.assertTrue(validate(data,20)["single_page_closed"])
        for invalid in (["002667","000001"],[],["009999"]):
            with self.subTest(raw_code=invalid):
                candidate=copy.deepcopy(data)
                candidate["data"][0]["secCode"]=invalid
                self.assertFalse(validate(candidate,20)["single_page_closed"])

    def test_empty_endpoint_schema_does_not_pass(self):
        self.assertFalse(validate({"data":[]},20)["parse_valid"])
        with self.assertRaisesRegex(ValueError,"TWO_SESSIONS_TWO_SIZES_REQUIRED"):
            compare([{20:validate(make(),20),30:validate(make(),30)}])

if __name__=="__main__":unittest.main()
