#!/usr/bin/env python3
"""One-shot fixed historical SSE margin coverage, reuse admitted exact page reader.

Historical dates preselected before any quote/return query. No stock outcome is
downloaded; quote comparison, buy rule and 20-session targets forbidden here.
"""
import json
from datetime import datetime,timezone
from pathlib import Path
from v32_sse_margin_two_day_source_probe import day_report

DAYS=("20251117","20260316","20260615","20260915")
def share(code):
    return code.startswith(("600","601","603","605","688","689","900"))
def main():
    reports=[]
    sets=[]
    for day in DAYS:
        result,data=day_report(day)
        codes={code for code in data if share(code)}
        unknown=len(data)-len(codes)
        result["stock_prefix_count"]=len(codes)
        result["other_security_codes_count"]=unknown
        result["prefix_classification_not_exchange_proven_equity_registry"]=True
        reports.append(result)
        sets.append(codes)
        print("HISTORIC_SSE_MARGIN",day,result["status"],"all",result["unique_securities"],
              "prefix_stock",len(codes),"others",unknown,flush=True)
    allok=all(r["status"]=="SOURCE_PAGINATION_EXHAUSTIVE" for r in reports)
    out={"schema":"V32_SSE_MARGIN_FOUR_PREDATED_SESSIONS_SOURCE_COVERAGE_V1",
         "fixed_days":list(DAYS),"historical_source_census_all_four":allok,
         "source_time_of_original_publication_not_certified":True,
         "stock_category_is_prefix_approximation_not_verified_membership":True,
         "complete_four_day_common_prefix_ids":len(set.intersection(*sets)) if allok else None,
         "date_range_daily_continuity_certified":False,
         "stock_ohlc_or_future_outcome_queried":False,"buy_authorized":False,
         "reports":reports}
    Path("/tmp/v32_sse_historical_margin_coverage.json").write_text(
       json.dumps(out,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    print("HISTORICAL_MARGIN_ADMISSION",json.dumps({k:v for k,v in out.items() if k!="reports"},ensure_ascii=False),flush=True)
if __name__=="__main__":main()
