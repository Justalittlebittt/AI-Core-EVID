#!/usr/bin/env python3
"""Bounded official CNINFO weekly-window and pagination source integrity test.

Checks whether date partitioning removes the earlier global-query 30-record
pagination repetition. Does not fetch forward returns, build factors or
modify any frozen sample. An incomplete window is a hard evidence gap.
"""
import argparse
import hashlib
import html
import json
import re
from datetime import date,datetime,timedelta,timezone
from pathlib import Path
from v29_original_report_discovery_128 import _post

START=date(2026,7,1)
END=date(2026,8,31)
TIMEZONE=timezone(timedelta(hours=8))
MAX_PAGES_PER_WINDOW=18
KEYWORD="业绩预告"
TITLE_REVISION=re.compile(r"(修正|更正|修订|调整)")
PDF=re.compile(r"finalpage/20\d\d-\d\d-\d\d/\d+\.PDF",re.I)

def windows():
    start=START
    while start<=END:
        end=min(start+timedelta(days=6),END)
        yield start,end
        start=end+timedelta(days=1)

def fetch_week(start,end):
    allrows={}
    pages=[]
    previous_ids=None
    status="PAGE_CAP_INCOMPLETE"
    for page in range(1,MAX_PAGES_PER_WINDOW+1):
        obj,raw=_post("hisAnnouncement/query",{
          "stock":"","tabName":"fulltext","pageNum":str(page),
          "pageSize":"30","column":"szse","plate":"",
          "category":"","seDate":start.isoformat()+"~"+end.isoformat(),
          "isHLtitle":"true","searchkey":KEYWORD})
        if not isinstance(obj,dict):raise ValueError("INVALID_QUERY_JSON")
        batch=obj.get("announcements")
        if batch is None and int(obj.get("totalRecordNum") or 0)==0:batch=[]
        if not isinstance(batch,list):raise ValueError("INVALID_ANNOUNCEMENT_ARRAY")
        ids=[str(row.get("announcementId") or "") for row in batch]
        page_record={"page":page,"n":len(ids),"unique_ids":len(set(ids)),
          "raw_sha256":hashlib.sha256(raw).hexdigest(),
          "total":obj.get("totalRecordNum"),
          "has_more":obj.get("hasMore"),
          "id_sha256":hashlib.sha256("|".join(ids).encode()).hexdigest()}
        pages.append(page_record)
        if not all(ids) or len(ids)!=len(set(ids)):
            status="PAGE_DUPLICATE_OR_EMPTY_ID";break
        if previous_ids is not None and set(ids)&previous_ids:
            status="CROSS_PAGE_OVERLAP";break
        previous_ids=set(ids)
        for row in batch:
            i=str(row["announcementId"])
            try: announcement_date=datetime.fromtimestamp(int(row["announcementTime"])/1000,TIMEZONE).date()
            except (TypeError,ValueError,KeyError,OverflowError):raise ValueError("BAD_PUBLICATION_TIME")
            if not start<=announcement_date<=end:
                status="RECORD_OUTSIDE_DATE_WINDOW";break
            title=re.sub(r"\s+","",re.sub(r"<[^>]*>","",html.unescape(str(row.get("announcementTitle") or ""))))
            allrows[i]={"announcement_id":i,
              "code":str(row.get("secCode") or ""),
              "date":announcement_date.isoformat(),
              "title":title,
              "original_pdf_url":"https://static.cninfo.com.cn/"+str(row.get("adjunctUrl"))
                   if PDF.fullmatch(str(row.get("adjunctUrl") or "")) else None}
        else:
            if obj.get("hasMore") is False:
                status="PAGES_COMPLETE";break
            continue
        break
    revisions=[v for v in allrows.values() if KEYWORD in v["title"] and TITLE_REVISION.search(v["title"])]
    print("WEEK_WINDOW",start,end,status,"pages",len(pages),"unique",len(allrows),
          "revisions",len(revisions),flush=True)
    return {"start":start.isoformat(),"end":end.isoformat(),
      "status":status,"pages":pages,"unique_announcements":len(allrows),
      "revision_title_count":len(revisions),
      "revisions":revisions,"all_ids":sorted(allrows)}

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    result=[]
    for start,end in windows():
        try: result.append(fetch_week(start,end))
        except (OSError,ValueError,TypeError) as e:
            result.append({"start":start.isoformat(),"end":end.isoformat(),
                           "status":"REQUEST_FAILED","error":type(e).__name__+":"+str(e)[:150]})
    revisions={}
    for r in result:
        for row in r.get("revisions",[]):
            revisions[row["announcement_id"]]=row
    complete=all(r["status"]=="PAGES_COMPLETE" for r in result)
    out={"schema":"V32_WEEKLY_PARTITION_CNINFO_2026JUL_AUG_SOURCE_FEASIBILITY_V1",
      "source":"CNINFO_HISTORIC_ANNOUNCEMENTS_FORM_POST",
      "window_count":len(result),"fully_paginated_window_count":sum(r["status"]=="PAGES_COMPLETE" for r in result),
      "all_windows_complete":complete,
      "revision_title_events_in_returned_rows":len(revisions),
      "distinct_issuers_in_revisions":len(set(r["code"] for r in revisions.values())),
      "complete_revision_market_universe_proven":False,
      "scope_note":"keyword searched indexed announcements only; cannot assert total market events without independent coverage checks",
      "2021_2022_and_2026_prospective_returns_opened":False,
      "stock_outcome_prices_opened":False,"live_buy_authorized":False,
      "windows":result,"unique_revision_records":sorted(revisions.values(),
                     key=lambda z:(z["date"],z["code"],z["announcement_id"]))}
    args.output.write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    print("V32_WEEKLY_PAGINATION_SUMMARY="+json.dumps({k:v for k,v in out.items()
      if k not in ("windows","unique_revision_records")},ensure_ascii=False),flush=True)

if __name__=="__main__":main()
