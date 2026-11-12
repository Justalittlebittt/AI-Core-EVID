"""Fail-closed source title comparison with actual frozen triage, synthetic only."""
import copy
import unittest
from v294_cninfo_szse_april_title_equivalence import compare, TARGET

def fixture():
    exchange=[];cninfo=[]
    for i in range(53):
        aid=TARGET if i==12 else str(1280000000+i)
        desc="关于召开2022年度业绩说明会的公告" if i==12 else "关于项目进展的公告"
        exchange.append({"ann_id":aid,"publication_day":"2023-04-14",
                         "title":"鞍重股份："+desc})
        cninfo.append({"ann_id":aid,"announcement_title":desc,
                       "security_name":"鞍重股份",
                       "announcement_time_raw":"1681401600000",
                       "publication_day":"2023-04-14",
                       "cninfo_relative_pdf_path":"finalpage/2023-04-14/"+aid+".PDF"})
    run={"complete":True,"reported_totals":[53],"error":None,"rows":cninfo}
    return exchange,[{20:copy.deepcopy(run),30:copy.deepcopy(run)}
                     for _ in range(2)]

class AprilTitleTests(unittest.TestCase):
    def test_known_original_title_non_equivalence_is_measurable(self):
        exchange,sessions=fixture()
        out=compare(exchange,sessions)
        self.assertTrue(out["all_four_april_censuses_equal_to_szse"])
        self.assertEqual(out["candidate_decision_mismatch_count"],1)
        self.assertEqual(len(out["cninfo_to_szse_title_triad_disagreements"]),1)
        self.assertFalse(out["verified_full_486_cninfo_titles"])
        self.assertFalse(out["batch3_authorized"])
        self.assertFalse(out["outcomes_consumed"])

    def test_partial_or_title_drift_blocks(self):
        exchange,sessions=fixture()
        sessions[0][20]["complete"]=False
        out=compare(exchange,sessions)
        self.assertFalse(out["all_four_april_censuses_equal_to_szse"])
        self.assertEqual(out["cninfo_title_observations"],[])
        exchange,sessions=fixture()
        sessions[1][30]["rows"][0]["announcement_title"]="另外一篇公告"
        out=compare(exchange,sessions)
        self.assertFalse(out["all_four_april_censuses_equal_to_szse"])
        self.assertEqual(out["error"],"CROSS_SESSION_TITLE_OR_TIMESTAMP_DRIFT")

    def test_missing_reference_never_passes(self):
        exchange,sessions=fixture()
        with self.assertRaisesRegex(ValueError,"EXACT_APRIL_REFERENCE"):
            compare(exchange[:52],sessions)
if __name__=="__main__":unittest.main()
