"""Offline verification of entry-only ranking and strict outcome missingness."""
import unittest
from datetime import date, timedelta
from v31_cross_year_growth_roe_replication import evaluate, code


def fixture():
    days=[]
    d=date(2026,3,2)
    while d<=date(2026,6,12):
        if d.weekday()<5:days.append(d)
        d+=timedelta(days=1)
    cal=[{"calendar_date":d.isoformat(),"is_trading_day":"1"} for d in days]
    idx=[{"date":d.isoformat(),"code":"sh.000300","close":"100"} for d in days]
    financial=[]
    quotes={}
    for k in range(1,7):
        sid="SZSE:"+str(k).zfill(6)
        financial.append({"security_id":sid,"status":"FINANCIAL_COMPLETE",
                          "report_notice_day":"2026-04-23",
                          "revenue_growth_yoy_pct":float(k*10),
                          "weighted_roe_pct":float(k*2)})
        rows=[]
        for n,day in enumerate(days):
            rows.append({"date":day.isoformat(),"code":code(sid),
                         "close":str(10+k+n*.05),
                         "adjustflag":"3","tradestatus":"1","isST":"0","volume":"1000"})
        quotes[sid]=rows
    return {},financial,cal,idx,quotes


class CrossYearResearchTests(unittest.TestCase):
    def test_2025_frozen_rank_reapplied_as_entry_only_2026_descriptive(self):
        out=evaluate(*fixture())
        self.assertEqual(out["selected_count"],2)
        self.assertEqual(out["entry_eligible_count"],6)
        self.assertEqual(out["selected_outcome_coverage"],2)
        self.assertEqual(out["primary"]["status"],"COMPLETE_RETROSPECTIVE_2026_NONPRISTINE")
        self.assertEqual([r["security_id"] for r in out["rows"] if r["selected_by_fixed_rule"]],
                         ["SZSE:000005","SZSE:000006"])
        self.assertFalse(out["independent_untouched_oos"])
        self.assertFalse(out["strategy_validated"])
        self.assertEqual(out["live_buy_eligibility"],"NOT_AUTHORIZED")

    def test_exit_missing_does_not_erase_bad_name_or_change_selection(self):
        frame,fin,cal,idx,quotes=fixture()
        # Delete later exit quote from one unselected eligible stock. The
        # matched cohort cannot silently shrink its denominator.
        target="SZSE:000001"
        # Compute the twentieth session from the synthetic calendar.
        days=[date.fromisoformat(x["calendar_date"]) for x in cal]
        end=[d for d in days if d>date(2026,4,23)][19].isoformat()
        quotes[target]=[r for r in quotes[target] if r["date"]!=end]
        out=evaluate(frame,fin,cal,idx,quotes)
        self.assertEqual(out["selected_count"],2)
        self.assertEqual(out["entry_eligible_count"],6)
        self.assertEqual(out["complete_comparison_day_group_count"],0)
        self.assertEqual(out["primary"]["status"],"INSUFFICIENT_FULL_SELECTED_OR_MATCHED_OUTCOMES")
        self.assertEqual(len(out["rows"]),6)

    def test_exit_st_not_used_to_remove_selected_winner(self):
        frame,fin,cal,idx,quotes=fixture()
        selected="SZSE:000006"
        days=[date.fromisoformat(x["calendar_date"]) for x in cal]
        end=[d for d in days if d>date(2026,4,23)][19].isoformat()
        for q in quotes[selected]:
            if q["date"]==end:q["isST"]="1"
        out=evaluate(frame,fin,cal,idx,quotes)
        one=next(x for x in out["rows"] if x["security_id"]==selected)
        self.assertTrue(one["selected_by_fixed_rule"])
        self.assertFalse(one["outcome_complete"])
        self.assertEqual(out["primary"]["status"],"INSUFFICIENT_FULL_SELECTED_OR_MATCHED_OUTCOMES")


if __name__=="__main__":
    unittest.main()
