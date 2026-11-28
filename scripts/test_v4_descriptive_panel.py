import unittest
from collections import Counter
from v4_descriptive_panel import load, screen

class DataFoundationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows=list(load())
    def test_real_coverage(self):
        self.assertEqual(len(self.rows),61952)
        self.assertEqual(Counter(r["observation_status"] for r in self.rows),{"OBSERVED_BAR":61480,"UNRESOLVED_NO_BAR":12,"CONFIRMED_SUSPENSION":123,"POST_DELISTING":337})
    def test_isolation(self):
        for r in self.rows:
            self.assertFalse(r["independent_oos"])
            self.assertIsNone(r["economic_return"])
            self.assertEqual(r["execution_status"],"UNKNOWN")
            if r["observation_status"]!="OBSERVED_BAR":
                self.assertIsNone(r["intraday_return"])
                self.assertIsNone(r["raw_close"])
    def test_consumer(self):
        r=screen("2023-01-03")
        self.assertTrue(r)
        self.assertTrue(all(x["observation_status"]=="OBSERVED_BAR" and x["session"]=="2023-01-03" for x in r))
    def test_fail_closed(self):
        for purpose in ("LIVE","INDEPENDENT_OOS","MODEL_TRAINING"):
            with self.assertRaises(ValueError):
                list(load(purpose))
if __name__=="__main__":
    unittest.main()
