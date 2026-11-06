"""Synthetic FY2026 post-disclosure 8-name paper entry/outcome integration only."""
import gzip
import json
import tempfile
import unittest
from datetime import date,datetime,timedelta
from pathlib import Path
from unittest.mock import patch

import v29_fy2026_forward_paper as f
from test_v29_fy2026_next_vintage_selector import fixture
from v29_fy2026_next_vintage_selector import select

ENTRY_NOW=datetime(2027,5,6,21,25,tzinfo=f.CN)
EXIT_NOW=datetime(2027,6,2,21,25,tzinfo=f.CN)

class Result:
    error_code="0"
    def __init__(self,fields,rows):
        self.fields=fields.split(",")
        self.rows=rows
        self.i=0
    def next(self):
        self.i+=1
        return self.i<=len(self.rows)
    def get_row_data(self):
        return [str(self.rows[self.i-1].get(k,"")) for k in self.fields]

class Bao:
    def __init__(self,missing=None):
        self.calls=[]
        self.missing=missing
    def login(self):return Result("code",[])
    def logout(self):pass
    def query_trade_dates(self,start_date,end_date):
        self.calls.append(("calendar",start_date,end_date))
        d=date.fromisoformat(start_date)
        end=date.fromisoformat(end_date)
        rows=[]
        while d<=end:
            active=d.weekday()<5 and not date(2027,5,1)<=d<=date(2027,5,5)
            rows.append({"calendar_date":d.isoformat(),"is_trading_day":"1" if active else "0"})
            d+=timedelta(days=1)
        return Result("calendar_date,is_trading_day",rows)
    def query_history_k_data_plus(self,code,fields,start_date,end_date,frequency,adjustflag):
        self.calls.append(("bar",code,start_date,end_date,adjustflag))
        if code==self.missing and adjustflag=="2":
            return Result(fields,[])
        begin=date.fromisoformat(start_date);end=date.fromisoformat(end_date)
        rows=[]
        while begin<=end:
            if begin.weekday()<5 and begin>=date(2027,5,6):
                close="120" if adjustflag=="2" and begin==date(2027,6,2) else (
                      "110" if adjustflag=="3" and begin==date(2027,6,2) else "100")
                rows.append({"date":begin.isoformat(),"code":code,
                    "close":close,"volume":"1000","tradestatus":"1","isST":"0",
                    "adjustflag":adjustflag})
            begin+=timedelta(days=1)
        return Result(fields,rows)

def official(start,end):
    rows=[{"indexCode":"H00300","tradeDate":start.replace("-",""),"close":"6000"}]
    if end!=start:
        rows.append({"indexCode":"H00300","tradeDate":end.replace("-",""),"close":"6300"})
    return json.dumps({"data":rows}).encode()

def candidate_frame():
    frame=fixture()
    frame["q3_original_source_vintage"]={
        "identity":"2026-10-30_DISCLOSURE_CUTOFF_2026-10-29_ORIGINAL_VENDOR",
        "source_vintage_date":"2026-10-30",
        "q3_2026_late_oct30_oct31_not_covered":True}
    selected=select(frame,datetime.fromisoformat("2027-05-01T10:05:00+08:00"))
    return frame,selected

def prepare(root):
    frame,selected=candidate_frame()
    path=root/f.SOURCE.relative_to(f.ROOT)
    path.mkdir(parents=True,exist_ok=True)
    (path/"NORMALIZED_ALL_A_FRAME.json").write_text(json.dumps(frame))
    (path/"FROZEN_EIGHT_RESEARCH_ONLY.json").write_text(json.dumps(selected))
    return frame,selected

class ForwardPaperTests(unittest.TestCase):
    def test_real_preregistered_eight_recomputed_before_entry(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            frame,selected=prepare(root)
            x=f.source_candidates(root)
            self.assertEqual(x[2],[
                r["security_id"] for r in selected["selected_in_frozen_ranking_order"]])
            self.assertEqual(len(x[2]),8)
            self.assertEqual(x[0]["first_trading_session_after_cutoff"],"2027-05-06")
            self.assertEqual(x[1]["live_buy_eligibility"],"NOT_AUTHORIZED")
            selected["selected_in_frozen_ranking_order"].reverse()
            (root/f.SOURCE.relative_to(f.ROOT)/"FROZEN_EIGHT_RESEARCH_ONLY.json").write_text(json.dumps(selected))
            with self.assertRaisesRegex(ValueError,"SELECTION_CHANGED"):
                f.source_candidates(root)

    def test_full_new_fy_eight_entry_and_exact_twentieth_close(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            prepare(root)
            loader=lambda:f.source_candidates(root)
            bs=Bao()
            entry,raw=f.capture_entry(bs,ENTRY_NOW,source_loader=loader,official_fetch=official)
            self.assertEqual(entry["status"],"PAPER_ENTRY_EIGHT_AND_H00300_COMPLETE")
            self.assertEqual(len(entry["quotes"]),8)
            self.assertEqual(entry["first_entry_session"],"2027-05-06")
            self.assertFalse(entry["trade_authorized"])
            self.assertEqual(len([x for x in bs.calls if x[0]=="bar"]),16)
            stored=root/f.ENTRY.relative_to(f.ROOT).parent
            f.store(stored,"entry",entry,raw)
            self.assertEqual(gzip.decompress((stored/"RAW_ENTRY_EIGHT.json.gz").read_bytes()),raw)
            entry_loader=lambda:f.load_entry(root,source_loader=loader)
            second,second_raw=f.capture_outcome(Bao(),EXIT_NOW,entry_loader=entry_loader,official_fetch=official)
            self.assertEqual(second["twentieth_session"],"2027-06-02")
            self.assertEqual(len(second["verified_vendor_sessions"]),20)
            self.assertEqual(second["price_eligible"],8)
            self.assertEqual(second["status"],"ONE_NEW_ANNUAL_REPORT_VINTAGE_PAPER_EPISODE_ONLY")
            self.assertAlmostEqual(second["metrics"]["equal_eight_net"],0.197)
            self.assertAlmostEqual(second["metrics"]["equal_eight_net_excess_vs_H00300"],0.147)
            self.assertAlmostEqual(second["metrics"]["minimum_lot_cash_weighted_net_posthoc_sensitivity"],0.197)
            self.assertEqual(second["benchmark"]["security_id"],"H00300.CSI")
            self.assertFalse(second["strategy_validated"])
            self.assertEqual(second["live_buy_eligibility"],"NOT_AUTHORIZED")
            outcome_dir=root/"result"
            f.store(outcome_dir,"outcome",second,second_raw)
            self.assertTrue((outcome_dir/"OUTCOME_EIGHT.json").is_file())

    def test_failed_price_keeps_all_eight_and_does_not_fabricate_return(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            prepare(root)
            loader=lambda:f.source_candidates(root)
            entry,raw=f.capture_entry(Bao(),ENTRY_NOW,source_loader=loader,official_fetch=official)
            stored=root/f.ENTRY.relative_to(f.ROOT).parent
            f.store(stored,"entry",entry,raw)
            missing=f.baostock_code(entry["selected_eight"][0])
            result,_=f.capture_outcome(
                Bao(missing=missing),EXIT_NOW,
                entry_loader=lambda:f.load_entry(root,source_loader=loader),
                official_fetch=official)
            self.assertEqual(result["price_eligible"],7)
            self.assertEqual(len(result["rows"]),8)
            self.assertEqual(result["status"],"INCOMPLETE_KEEP_ALL_EIGHT")
            self.assertIsNone(result["metrics"])
            self.assertFalse(result["trade_authorized"])

    def test_future_gate_rejects_early_or_late_entry_and_outcome(self):
        frame,selected=candidate_frame()
        x=lambda: (frame,selected,[r["security_id"] for r in selected["selected_in_frozen_ranking_order"]],
                   "a"*64,"b"*64)
        with self.assertRaisesRegex(ValueError,"ENTRY_ONLY_SAME_DAY_AFTER_CLOSE"):
            f.capture_entry(Bao(),datetime(2027,5,6,15,tzinfo=f.CN),x,official)
        with self.assertRaisesRegex(ValueError,"ENTRY_ONLY_SAME_DAY_AFTER_CLOSE"):
            f.capture_entry(Bao(),datetime(2027,5,7,21,tzinfo=f.CN),x,official)
        bs=Bao()
        cal=f.records(bs.query_trade_dates(start_date="2027-05-06",end_date="2027-06-01"))
        with self.assertRaisesRegex(ValueError,"OUTCOME_NOT_MATURE"):
            f.maturity(cal,date(2027,5,6),datetime(2027,6,1,21,tzinfo=f.CN))
        cal=f.records(bs.query_trade_dates(start_date="2027-05-06",end_date="2027-06-06"))
        with self.assertRaisesRegex(ValueError,"RETROSPECTIVE_WINDOW_EXPIRED"):
            f.maturity(cal,date(2027,5,6),datetime(2027,6,6,21,tzinfo=f.CN))
        damaged=cal[1:]
        with self.assertRaisesRegex(ValueError,"MISSING_DATE"):
            f.maturity(damaged,date(2027,5,6),datetime(2027,6,6,21,tzinfo=f.CN))

if __name__=="__main__":
    unittest.main()
