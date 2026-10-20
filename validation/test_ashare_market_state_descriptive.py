"""Offline regression checks for additive state descriptors; no historical acceptance gate changes."""
import csv,sys,tempfile,unittest
from datetime import date,timedelta
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from ashare_market_state_descriptive import evaluate

def fixture(prices_a,prices_b,mixed=False):
    f=tempfile.NamedTemporaryFile('w',delete=False,newline='')
    writer=csv.DictWriter(f,fieldnames=['index_id','date','close','source_id','retrieved_at_utc'])
    writer.writeheader()
    ds=[date(2025,1,1)+timedelta(days=i) for i in range(len(prices_a))]
    for idx,prices in [('000300.SH',prices_a),('000688.SH',prices_b)]:
        for d,p in zip(ds,prices):
            writer.writerow({'index_id':idx,'date':d.isoformat(),'close':p,
                'source_id':'CANDIDATE_B' if mixed and idx=='000688.SH' else 'CANDIDATE_A',
                'retrieved_at_utc':'2026-10-20T10:00:00+00:00'})
    f.close();return Path(f.name),ds

class StateTests(unittest.TestCase):
    def setUp(self):self.p=[100+i*.2+(i%7)*.1 for i in range(340)]
    def test_descriptive_not_signal(self):
        f,d=fixture(self.p,self.p);self.addCleanup(f.unlink)
        a=evaluate(f,d[-1]);self.assertFalse(a['trading_authorized'])
        self.assertEqual(a['state_label'],'UNASSIGNED_NO_EMPIRICAL_VALIDATION')
        self.assertTrue(0<=a['indices']['000300.SH']['rv20_percentile_252']<=1)
    def test_future_price_isolation(self):
        f,d=fixture(self.p,self.p);self.addCleanup(f.unlink)
        q=self.p[:];q[-10:]=[v*2 for v in q[-10:]]
        g,_=fixture(q,q);self.addCleanup(g.unlink)
        self.assertEqual(evaluate(f,d[-11])['indices'],evaluate(g,d[-11])['indices'])
    def test_mixed_source_refused(self):
        f,d=fixture(self.p,self.p,mixed=True);self.addCleanup(f.unlink)
        with self.assertRaisesRegex(ValueError,'MIXED_SOURCE'):evaluate(f,d[-1])
    def test_short_history_refused(self):
        f,d=fixture(self.p[:270],self.p[:270]);self.addCleanup(f.unlink)
        with self.assertRaisesRegex(ValueError,'INSUFFICIENT_HISTORY'):evaluate(f,d[-1])
if __name__=='__main__':unittest.main()
