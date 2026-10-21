"""Independent downside-study boundary tests."""
import csv,sys,tempfile,unittest
from datetime import date,timedelta
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from ashare_downside_discrimination import max_drawdown,study

def fixture(switch=False):
    f=tempfile.NamedTemporaryFile('w',delete=False,newline='')
    w=csv.DictWriter(f,fieldnames=['index_id','date','close','source_id','retrieved_at_utc'])
    w.writeheader()
    for idx in ('000300.SH','000688.SH'):
        for i in range(600):
            v=100+i*.15+(i%12)*.08
            if switch and i>=590:v*=1.7
            w.writerow({'index_id':idx,'date':(date(2024,1,1)+timedelta(days=i)).isoformat(),
                          'close':v,'source_id':'CANDIDATE_ONLY','retrieved_at_utc':'2026-10-20T09:00:00+00:00'})
    f.close();return Path(f.name)

class DownsideTests(unittest.TestCase):
    def test_mdd_known_path(self):
        self.assertAlmostEqual(max_drawdown([100,110,88,95]),-.2)
    def test_nonoverlap_and_no_authorization(self):
        p=fixture();self.addCleanup(p.unlink)
        r=study(p);self.assertFalse(r['trading_authorized'])
        for v in r['indices'].values():
            self.assertEqual(v['count'],16)
            self.assertTrue(all(v['windows'][i]['end']<=v['windows'][i+1]['asof'] for i in range(15)))
    def test_future_changes_cannot_change_earlier_features(self):
        p=fixture();q=fixture(True);self.addCleanup(p.unlink);self.addCleanup(q.unlink)
        x=study(p)['indices']['000300.SH']['windows']
        y=study(q)['indices']['000300.SH']['windows']
        self.assertGreater(len(x),0)
        for a,b in zip(x,y):
            self.assertEqual(a['rv20_at_asof'],b['rv20_at_asof'])
            self.assertEqual(a['predicted_high_volatility'],b['predicted_high_volatility'])
    def test_mixed_sources_rejected(self):
        p=fixture();self.addCleanup(p.unlink)
        content=p.read_text().replace('000688.SH,','000688.SH,',1)
        p.write_text(content.replace('CANDIDATE_ONLY','OTHER',1))
        with self.assertRaisesRegex(ValueError,'MIXED_SOURCES'):study(p)

if __name__=='__main__':unittest.main()
