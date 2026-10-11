"""Synthetic negative/positive tests of public-close validation, not market-data verification."""
from __future__ import annotations

import csv
import json
import math
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ashare_market_risk_real_snapshot_acceptance import accept

REFDATE = date(2026, 10, 9)
CLOSES = {"000300.SH": 4317.25, "000688.SH": 1457.27}


def rows(n=272):
    day=REFDATE
    sessions=[]
    while len(sessions)<n:
        if day.weekday()<5:
            sessions.append(day)
        day-=timedelta(days=1)
    sessions.reverse()
    items=[]
    for idx,close in CLOSES.items():
        for i,day in enumerate(sessions):
            items.append({
              "index_id":idx,"date":day.isoformat(),
              "close":f"{close*math.exp((i-n+1)*0.0001+0.00001*math.sin(i)):.8f}",
              "source_id":"AKSHARE_INDEX_ZH_A_HIST_EASTMONEY",
              "retrieved_at_utc":"2026-10-11T06:00:00+00:00"})
    return items


def write(path, records):
    with path.open("w", encoding="utf-8", newline="") as f:
        writer=csv.DictWriter(f,fieldnames=[
          "index_id","date","close","source_id","retrieved_at_utc"])
        writer.writeheader()
        writer.writerows(records)


def blocked(path,reference,expected):
    try:
        accept(path,reference,REFDATE)
        raise AssertionError("expected rejection "+expected)
    except ValueError as exc:
        assert expected in str(exc),str(exc)


def main():
    with tempfile.TemporaryDirectory() as td:
        folder=Path(td)
        ref=folder/"ref.json"
        ref.write_text(json.dumps({
           "schema":"AI_CORE_EVID_ASHARE_INDEX_CLOSE_REFERENCE_V1",
           "reference_date":REFDATE.isoformat(),
           "close_points":CLOSES,
           "allowed_absolute_difference_points":0.02,
           "source_url":"https://www.csindex.com.cn/"
        }),encoding="utf-8")
        p=folder/"snapshot.csv"
        base=rows()
        write(p,base)
        result=accept(p,ref,REFDATE)
        assert result["status"]=="PASS_INDEPENDENT_CLOSE_AND_WINDOW_ONLY"
        assert result["forecasting_skill_or_alpha_verified"] is False
        assert result["historical_point_in_time_verified"] is False
        for idx in CLOSES:
            assert result["risk_descriptive_report"]["indices"][idx]["rv20_percentile_252"] is not None
            assert result["index_checks"][idx]["sessions"]==272
        try:
            accept(p,ref,REFDATE+timedelta(days=2))
            raise AssertionError("reference date drift must fail")
        except ValueError as e:
            assert "REFERENCE_DATE_ONLY" in str(e)

        changed=[dict(x) for x in base]
        changed[-1]["close"]="1500"
        write(p,changed)
        blocked(p,ref,"INDEPENDENT_CLOSE_MISMATCH")

        changed=[dict(x) for x in base if x["index_id"]=="000300.SH"]
        write(p,changed)
        blocked(p,ref,"INCOMPLETE_INDEX_SET")

        changed=[dict(x) for x in base if x["date"]>base[0]["date"]]
        write(p,changed)
        blocked(p,ref,"INSUFFICIENT_RV_HISTORY")

        changed=[dict(x) for x in base]
        changed[-1]["source_id"]="OTHER_VENDOR"
        write(p,changed)
        blocked(p,ref,"UNAPPROVED_SNAPSHOT_PROVIDER")

        changed=[dict(x) for x in base]
        changed[-1]["retrieved_at_utc"]="2026-10-09T05:00:00+00:00"
        write(p,changed)
        blocked(p,ref,"CAPTURE_PRECEDES_OFFICIAL_CLOSE")

        changed=[dict(x) for x in base]
        # Same count, both pass official close, but one calendar differs.
        changed[-3]["date"]="2026-10-03"  # weekend only in second index, not a duplicate
        write(p,changed)
        blocked(p,ref,"INDEX_TRADING_DATES_DISAGREE")
    print("ASHARE_PUBLIC_CLOSE_ACCEPTANCE_SYNTHETIC: PASS (NOT REAL DATA)")


if __name__=="__main__":
    main()
