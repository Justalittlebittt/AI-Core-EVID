"""Synthetic-only contract tests; cannot promote source completeness."""
import copy
import unittest
from v294_cninfo_august_split_audit import PARTS, evaluate_sessions


def fixture():
    ids={"first_half":["a","b"],"second_half":["c"],
         "full_august":["a","b","c"],"left_boundary":["j"],"right_boundary":["k"]}
    s={key:{"complete":True,"ids":value,"reported_totals":[len(value)]}
       for key,value in ids.items()}
    return [copy.deepcopy(s),copy.deepcopy(s)]


class AugustAuditTests(unittest.TestCase):
    def test_only_two_reproducible_disjoint_sessions_pass_technical_check(self):
        a=fixture()
        r=evaluate_sessions(a)
        self.assertTrue(r["technical_consistency_pass"])
        self.assertFalse(r["scientific_completeness_certified"])
        self.assertFalse(r["batch3_aggregation_authorized"])
        self.assertFalse(r["batch4_authorized"])
        self.assertFalse(r["outcomes_consumed"])

    def test_each_source_inconsistency_blocks(self):
        for kind in ("unstable","duplicate","missing","boundary"):
            with self.subTest(kind=kind):
                a=fixture()
                if kind=="unstable":
                    a[1]["first_half"]["ids"]=["a"]
                if kind=="duplicate":
                    a[0]["second_half"]["complete"]=False
                if kind=="missing":
                    a[0]["full_august"]["ids"]=["a","b"]
                    a[1]["full_august"]["ids"]=["a","b"]
                if kind=="boundary":
                    a[0]["right_boundary"]["ids"]=["c"]
                    a[1]["right_boundary"]["ids"]=["c"]
                self.assertFalse(evaluate_sessions(a)["technical_consistency_pass"])

    def test_incomplete_session_fails_closed(self):
        with self.assertRaisesRegex(ValueError,"EXACT_TWO_COMPLETE_SESSIONS_REQUIRED"):
            evaluate_sessions(fixture()[:1])


if __name__=="__main__":
    unittest.main()
