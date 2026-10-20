"""Synthetic temporal and sample-size regression checks for exploratory outcome study."""
import csv,sys,tempfile,unittest
from datetime import date,timedelta
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from ashare_state_outcome_exploration import study

def make(prices_a,prices_b,source_b="candidate"):
    f=tempfile.NamedTemporaryFile("w",newline="",delete=False)
    w=csv.DictWriter(f,fieldnames=["index_id","date","close","source_id","retrieved_at_utc"])
    w.writeheader()
    for idx,prices,src in [("000300.SH",prices_a,"candidate"),("000688.SH",prices_b,source_b)]:
        for i,p in enumerate(prices):
            w.writerow(dict(index_id=idx,date=(date(2025,1,1)+timedelta(days=i)).isoformat(),
                            close=p,source_id=src,retrieved_at_utc="2026-10-20T09:00:00+00:00"))
    f.close()
    return Path(f.name)

class OutcomeStudyTests(unittest.TestCase):
    def setUp(self):self.prices=[100+i*0.1+(i%9)*0.02 for i in range(450)]
    def run_study(self,a,b,**kw):
        p=make(a,b,**kw);self.addCleanup(p.unlink);return study(p,date(2026,1,1))
    def test_nonoverlap_windows_not_claim_predictive_skill(self):
        x=self.run_study(self.prices,self.prices)
        self.assertFalse(x["predictive_efficacy_verified"])
        self.assertFalse(x["trade_authorized"])
        w=x["indices"]["000300.SH"]["windows"]
        self.assertTrue(w)
        self.assertTrue(all(x["asof"]<x["outcome_end"] for x in w))
        self.assertTrue(all(w[i]["outcome_end"]<=w[i+1]["asof"] for i in range(len(w)-1)))
    def test_future_prices_never_change_earlier_features(self):
        x=self.run_study(self.prices,self.prices)
        q=self.prices.copy();q[-25:]=[v*1.7 for v in q[-25:]]
        y=self.run_study(q,q)
        a=x["indices"]["000300.SH"]["windows"]
        b=y["indices"]["000300.SH"]["windows"]
        for u,v in zip(a,b):
            if u["outcome_end"]<"2026-03-01":
                self.assertEqual(u["rv20_at_asof"],v["rv20_at_asof"])
    def test_mixed_source_rejected(self):
        with self.assertRaisesRegex(ValueError,"MIXED_SOURCE"):
            self.run_study(self.prices,self.prices,source_b="other")
    def test_insufficient_history_yields_no_outcomes(self):
        x=self.run_study(self.prices[:260],self.prices[:260])
        self.assertEqual(x["indices"]["000300.SH"]["nonoverlap_windows"],0)

if __name__=="__main__":unittest.main()
