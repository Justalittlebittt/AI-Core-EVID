#!/usr/bin/env python3
"""Targeted sub-day completeness rescue for the ONE unresolved 2026-07-15..21 week.

Reuses the tested fetch_week() without changing global source rules or
reading any stock returns. The previously complete other eight weeks are not
requeried, avoiding redundant API load.
"""
import argparse
import json
from datetime import date,timedelta
from pathlib import Path
from v32_cninfo_weekly_denominator_feasibility import fetch_week

def main():
    a=argparse.ArgumentParser()
    a.add_argument("--output",type=Path,required=True)
    args=a.parse_args()
    start=date(2026,7,15)
    rows=[]
    for offset in range(7):
        d=start+timedelta(days=offset)
        try: rows.append(fetch_week(d,d))
        except (OSError,ValueError,TypeError) as e:
            rows.append({"start":d.isoformat(),"end":d.isoformat(),
                         "status":"QUERY_FAILED","detail":type(e).__name__+":"+str(e)[:140]})
    all_ids=set()
    revisions={}
    overlap=[]
    for row in rows:
        for i in row.get("all_ids",[]):
            if i in all_ids:overlap.append(i)
            all_ids.add(i)
        for r in row.get("revisions",[]):
            revisions[r["announcement_id"]]=r
    complete=(len(rows)==7 and all(r["status"]=="PAGES_COMPLETE" for r in rows)
              and not overlap)
    out={"schema":"V32_ONE_WEEK_SUBDAY_COMPLETENESS_RESOLUTION_V1",
         "window":"2026-07-15..2026-07-21",
         "each_day_source_pagination_complete":complete,
         "subday_unique_announcement_count":len(all_ids),
         "subday_title_revision_count":len(revisions),
         "subday_overlap_ids":overlap,
         "overall_nine_week_coverage_not_independently_recomputed":True,
         "all_market_title_or_keyword_recall_unproven":True,
         "source_only":True,"trade_authorized":False,
         "rows":rows}
    args.output.write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    print("V32_ONE_WEEK_SUBDAY_SUMMARY="+json.dumps({k:v for k,v in out.items() if k!="rows"},ensure_ascii=False),flush=True)
if __name__=="__main__":main()
