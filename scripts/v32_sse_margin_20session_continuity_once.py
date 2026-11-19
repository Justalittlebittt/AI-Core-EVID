#!/usr/bin/env python3
"""20-session continuous retrospective SSE margin source acceptance (no returns).

Dates fixed here before execution: 2026-08-24 .. 2026-09-18, every weekday.
Require all source records, exactly matching exchange page totals; no omission,
replacement or calendar-day imputation. No stock quote, signal or buy advice.
"""
import json
from datetime import date,timedelta
from pathlib import Path
from v32_sse_margin_two_day_source_probe import day_report

START=date(2026,8,24)
END=date(2026,9,18)
DAYS=[]
d=START
while d<=END:
    if d.weekday()<5:DAYS.append(d.strftime("%Y%m%d"))
    d+=timedelta(days=1)
assert len(DAYS)==20
def is_a_share(code):
    return code.startswith(("600","601","603","605","688","689"))
def main():
    reports=[];elig=[]
    for d in DAYS:
        result,rows=day_report(d)
        codes={code for code in rows if is_a_share(code)}
        result["A_share_prefix_count"]=len(codes)
        result["non_A_share_prefix_count"]=len(rows)-len(codes)
        reports.append(result)
        elig.append(codes)
        print("SSE_MARGIN_CONTIGUOUS_DATE",d,result["status"],
          "full_rows",result["unique_securities"],
          "A_prefix_count",len(codes),flush=True)
    full=all(r["status"]=="SOURCE_PAGINATION_EXHAUSTIVE" for r in reports)
    out={
      "schema":"V32_SSE_MARGIN_TWENTY_CONSECUTIVE_SESSIONS_SOURCE_FEASIBILITY_V1",
      "date_range":[DAYS[0],DAYS[-1]],
      "assumed_weekday_sessions_not_independently_checked_holiday_calendar":True,
      "requested_weekdays":len(DAYS),"fully_paginated_weekdays":sum(
          r["status"]=="SOURCE_PAGINATION_EXHAUSTIVE" for r in reports),
      "all_source_days_complete":full,
      "A_share_prefix_common_20_dates":(len(set.intersection(*elig)) if full else None),
      "A_share_identity_is_unverified_prefix_classification":True,
      "stock_outcome_or_return_used":False,"trade_authorized":False,
      "rows":reports}
    Path("/tmp/v32_sse_margin_twenty_dates_source.json").write_text(
        json.dumps(out,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    print("SSE_MARGIN_TWENTY_DAY_CONCLUSION",json.dumps(
        {k:v for k,v in out.items() if k!="rows"},ensure_ascii=False),flush=True)

if __name__=="__main__":main()
