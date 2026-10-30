"""Deterministic 2025 post-disclosure two-issuer study, no real outcome literals."""
import copy
import json
import tempfile
import unittest
from datetime import date,timedelta
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
from v29_2025_filing_to_return_case import load_inputs,compute_report,capture

def dataset():
    inputs,_=load_inputs()
    cal=[]
    day=date(2025,4,1)
    while day<=date(2025,6,30):
        if day.weekday()<5:
            cal.append({"calendar_date":day.isoformat(),"is_trading_day":"1"})
        day+=timedelta(days=1)
    m={"index":[{"date":d["calendar_date"],"code":"sh.000300","close":"100"} for d in cal]}
    for x in inputs["issuers"]:
        sid=x["baostock"]
        m[sid]={
          "unadjusted":[{"date":d["calendar_date"],"code":sid,
            "close":str(100+i*.1),"tradestatus":"1","isST":"0",
            "adjustflag":"3"} for i,d in enumerate(cal)],
          "forward_adjusted_2026_vintage":[{"date":d["calendar_date"],"code":sid,
            "close":str(100+i*.1),"tradestatus":"1","isST":"0",
            "adjustflag":"2"} for i,d in enumerate(cal)]
        }
    return inputs,cal,m

class Tests(unittest.TestCase):
    def test_true_2025_notice_not_2024_period(self):
        inp,cal,m=dataset()
        result=compute_report(inp,cal,m)
        rows={r["security_id"]:r for r in result["observations"]}
        self.assertEqual(rows["SZSE:300408"]["entry_session"],"2025-04-25")
        self.assertEqual(rows["SSE:688002"]["entry_session"],"2025-04-14")
        self.assertNotEqual(rows["SZSE:300408"]["exit_session"],"2025-04-25")
        self.assertEqual(result["live_buy_eligibility"],"NOT_AUTHORIZED")
        self.assertFalse(result["strategy_validated"])

    def test_cost_and_revenue_signal_arithmetic(self):
        inp,cal,m=dataset()
        result=compute_report(inp,cal,m)
        for r in result["observations"]:
            self.assertGreater(r["fy2024_revenue_yoy_pct"],0)
            self.assertGreater(r["fy2024_deducted_parent_profit_yoy_pct"],0)
            self.assertAlmostEqual(r["price_only_net_excess_after_30bps"],
                                   r["raw_price_return"]-.003)
            self.assertTrue(r["not_an_unseen_oos_event"])
            self.assertFalse(r["cash_dividend_and_corporate_action_economic_return_certified"])

    def test_missing_exit_quote_blocks(self):
        inp,cal,m=dataset()
        m["sz.300408"]["unadjusted"]=m["sz.300408"]["unadjusted"][:3]
        with self.assertRaisesRegex(ValueError,"ENTRY_OR_EXIT_PRICE_MISSING"):
            compute_report(inp,cal,m)

    def test_wrong_identity_blocks(self):
        inp,cal,m=dataset()
        m["sz.300408"]["unadjusted"][0]["code"]="sz.300409"
        with self.assertRaisesRegex(ValueError,"IDENTITY_MISMATCH"):
            compute_report(inp,cal,m)

    def test_duplicate_bar_blocks(self):
        inp,cal,m=dataset()
        m["sz.300408"]["unadjusted"].append(copy.deepcopy(m["sz.300408"]["unadjusted"][-1]))
        with self.assertRaisesRegex(ValueError,"BAR_OFF_CALENDAR_OR_DUPLICATE"):
            compute_report(inp,cal,m)

    def test_st_and_halt_blocks(self):
        inp,cal,m=dataset()
        notice={x["baostock"]:x["published_on"] for x in inp["issuers"]}
        m["sz.300408"]["unadjusted"][18]["isST"]="1"
        with self.assertRaisesRegex(ValueError,"ENTRY_OR_EXIT_NOT_TRADEABLE"):
            compute_report(inp,cal,m)

    def test_market_benchmark_missing_blocks(self):
        inp,cal,m=dataset()
        m["index"]=[]
        with self.assertRaisesRegex(ValueError,"BENCHMARK_ENDPOINT_MISSING"):
            compute_report(inp,cal,m)

    def test_wrong_financial_signals_never_implicitly_promoted(self):
        inp,cal,m=dataset()
        inp["issuers"][0]["revenue_2024_yuan"]=inp["issuers"][0]["revenue_2023_yuan"]*.1
        result=compute_report(inp,cal,m)
        self.assertLess(result["observations"][0]["fy2024_revenue_yoy_pct"],0)
        self.assertFalse(result["strategy_validated"])

    def test_provenance_and_no_overwrite(self):
        class Rs:
            error_code="0"
            error_msg=""
            def __init__(self,fields,data):
                self.fields=fields.split(",")
                self._data=data
                self.i=0
            def next(self):
                self.i+=1
                return self.i<=len(self._data)
            def get_row_data(self):
                row=self._data[self.i-1]
                return [row.get(key,"") for key in self.fields]
        class FakeBS:
            def login(self):return Rs("date",[])
            def logout(self):pass
            def query_trade_dates(self,**kwargs):
                return Rs("calendar_date,is_trading_day",cal)
            def query_history_k_data_plus(self,code,fields,**kwargs):
                if code=="sh.000300":return Rs(fields,m["index"])
                key="forward_adjusted_2026_vintage" if kwargs["adjustflag"]=="2" else "unadjusted"
                return Rs(fields,m[code][key])
        inp,cal,m=dataset()
        with tempfile.TemporaryDirectory() as t:
            root=Path(t)/"saved"
            res=capture(FakeBS(),root)
            self.assertEqual(len(res["observations"]),2)
            self.assertTrue((root/"raw_2025_market_and_calendar.json").exists())
            with self.assertRaisesRegex(ValueError,"OUTPUT_ALREADY_EXISTS"):
                capture(FakeBS(),root)

if __name__=="__main__":
    unittest.main()
