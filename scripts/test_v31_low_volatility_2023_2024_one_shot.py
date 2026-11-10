"""Bounded offline tests for nonleaking signal/outcome separation (no broker)."""
import math
import unittest
from datetime import date,timedelta

from v31_low_volatility_2023_2024_one_shot import compute,at_signal,realized,sid_to_bs


def synthetic():
    start,end=date(2022,8,1),date(2025,1,31)
    days=[]
    d=start
    while d<=end:
        if d.weekday()<5:days.append(d)
        d+=timedelta(days=1)
    calendar=[{"calendar_date":d.isoformat(),"is_trading_day":"1"} for d in days]
    index=[{"date":d.isoformat(),"code":"sh.000300","open":"100","close":"100"} for d in days]
    ids=["SZSE:"+str(100000+i) for i in range(48)]
    frames={str(y):{"selected_ids":ids,
                      "frame_date":f"{y}-01-03",
                      "population_count":1000,"selected_ids_sha256":"synthetic"}
            for y in (2023,2024)}
    quotes={}
    for i,sid in enumerate(ids):
        rows=[]
        code=sid_to_bs(sid)
        for j,day in enumerate(days):
            # First 12 have small but nonzero past volatility.
            noise=.002 if i<12 else .045
            close=math.exp(2.5+.0001*j+noise*math.sin(j*.7+i*.13))
            rows.append({"date":day.isoformat(),"code":code,
                         "open":str(close*.9999),"close":str(close),
                         "adjustflag":"2","tradestatus":"1","isST":"0","volume":"2000"})
        quotes[sid]=rows
    spec={"decision":{"minimum_evaluated_months":15}}
    return spec,frames,calendar,index,quotes


class LowVolHistorySafetyTests(unittest.TestCase):
    def test_low_absolute_volatility_chooses_dated_past_only(self):
        spec,frames,cal,index,prices=synthetic()
        result,opportunities=compute(spec,frames,cal,index,prices)
        self.assertEqual(result["requested_signal_months"],20)
        self.assertEqual(result["valid_descriptive_months"],20)
        self.assertEqual(result["selected_event_count"],240)
        self.assertFalse(result["trade_authorized"])
        self.assertEqual(result["live_buy_eligibility"],"NOT_AUTHORIZED")
        self.assertEqual(result["hypothesis"],"LOW_ABSOLUTE_60_SESSION_VOLATILITY")
        self.assertEqual(result["months"][0]["selected_count"],12)
        self.assertEqual(result["months"][0]["portfolio_entry_date"],
                         cal[[x["calendar_date"] for x in cal].index(
                         result["months"][0]["signal_date"])+1]["calendar_date"])
        chosen=result["months"][0]["selected_identities"]
        self.assertEqual(set(chosen),set(frames["2023"]["selected_ids"][:12]))

    def test_exit_loss_or_missing_does_not_replace_original_selection(self):
        spec,frames,cal,index,prices=synthetic()
        initial,_=compute(spec,frames,cal,index,prices)
        row=initial["months"][0]
        chosen=row["selected_identities"][0]
        exit_day=row["portfolio_exit_date"]
        prices[chosen]=[x for x in prices[chosen] if x["date"]!=exit_day]
        later,_=compute(spec,frames,cal,index,prices)
        assert later["months"][0]["selected_identities"]==row["selected_identities"]
        self.assertIn(chosen,later["months"][0]["selected_unresolved_ids"])
        self.assertFalse(later["months"][0]["admissible_descriptive_month"])
        self.assertTrue(later["months"][0]["selected_resolved_fraction"]<.95)

    def test_only_retro_adjusted_price_proxy_and_ST_exit_kept(self):
        row={"date":"2023-04-04","code":"sz.100000","open":"10","close":"10",
             "adjustflag":"2","tradestatus":"1","isST":"0","volume":"100"}
        final={**row,"date":"2023-05-05","close":"11","isST":"1"}
        price,state=realized({date(2023,4,4):row,date(2023,5,5):final},
                             date(2023,4,4),date(2023,5,5))
        self.assertIsNone(price)
        self.assertEqual(state,"EXIT_STATUS_NOT_CERTIFIED_AS_NORMAL")
        invalid,status=at_signal({date(2023,4,4):row},
                                 [date(2023,4,4)]*62,61)
        self.assertIsNone(invalid)


if __name__=="__main__":
    unittest.main()
