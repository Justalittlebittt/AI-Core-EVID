import csv,hashlib,json,tempfile,unittest
from pathlib import Path
from ashare_snapshot_provenance_audit import audit

class ProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name); self.csv=self.root/'sample.csv'; self.man=self.root/'sample.csv.manifest.json'
        self.rows=[{'index_id':i,'date':'2026-10-09','close':c,'source_id':'AKSHARE_INDEX_ZH_A_HIST_EASTMONEY','retrieved_at_utc':'2026-10-11T06:00:00+00:00'} for i,c in [('000300.SH','4317.25'),('000688.SH','1457.27')]]
        self.save()
    def save(self):
        with self.csv.open('w',newline='') as f:
            w=csv.DictWriter(f,fieldnames=self.rows[0]);w.writeheader();w.writerows(self.rows)
        self.m={'schema':'AI_CORE_EVID_ASHARE_INDEX_SOURCE_SNAPSHOT_V1','snapshot_sha256':hashlib.sha256(self.csv.read_bytes()).hexdigest(),'source':'AKShare.index_zh_a_hist/Eastmoney','historical_PIT_verified':False,'captured_at_utc':'2026-10-11T06:00:00+00:00','query_start_date':'2025-01-01','query_end_date':'2026-10-09','rows_per_index':{'000300.SH':1,'000688.SH':1}}
        self.man.write_text(json.dumps(self.m))
    def test_good(self): self.assertEqual(audit(self.csv,self.man)['status'],'PASS_PROVENANCE_BINDING_ONLY')
    def test_modified_csv(self):
        self.csv.write_bytes(self.csv.read_bytes()+b'\n')
        with self.assertRaisesRegex(ValueError,'HASH_MISMATCH'):audit(self.csv,self.man)
    def test_manifest_count_tamper(self):
        x=json.loads(self.man.read_text());x['rows_per_index']['000300.SH']=2;self.man.write_text(json.dumps(x))
        with self.assertRaisesRegex(ValueError,'ROW_COUNTS'):audit(self.csv,self.man)
    def test_capture_tamper(self):
        x=json.loads(self.man.read_text());x['captured_at_utc']='2026-10-12T06:00:00+00:00';self.man.write_text(json.dumps(x))
        with self.assertRaisesRegex(ValueError,'TIMESTAMP'):audit(self.csv,self.man)
    def test_source_tamper(self):
        x=json.loads(self.man.read_text());x['source']='unknown';self.man.write_text(json.dumps(x))
        with self.assertRaisesRegex(ValueError,'SOURCE_BLOCK'):audit(self.csv,self.man)
    def test_pit_claim(self):
        x=json.loads(self.man.read_text());x['historical_PIT_verified']=True;self.man.write_text(json.dumps(x))
        with self.assertRaisesRegex(ValueError,'PIT_CLAIM'):audit(self.csv,self.man)


    def test_malformed_date(self):
        self.rows[0]['date']='2026-02-30';self.save()
        with self.assertRaises(ValueError):audit(self.csv,self.man)
    def test_invalid_close(self):
        self.rows[0]['close']='nan';self.save()
        with self.assertRaisesRegex(ValueError,'SNAPSHOT_CLOSE_INVALID'):audit(self.csv,self.man)
    def test_naive_timestamp(self):
        self.rows[0]['retrieved_at_utc']='2026-10-11T06:00:00';self.save()
        with self.assertRaisesRegex(ValueError,'ROW_CAPTURE_NOT_UTC'):audit(self.csv,self.man)
    def test_duplicate_rows(self):
        self.rows.append(dict(self.rows[0]));self.save()
        with self.assertRaisesRegex(ValueError,'DUPLICATE_INDEX_DATE'):audit(self.csv,self.man)
    def test_bad_query_range(self):
        x=json.loads(self.man.read_text());x['query_start_date']='2027-01-01';self.man.write_text(json.dumps(x))
        with self.assertRaisesRegex(ValueError,'INVALID_QUERY_RANGE'):audit(self.csv,self.man)

if __name__=='__main__':unittest.main()
