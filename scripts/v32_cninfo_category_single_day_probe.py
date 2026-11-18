#!/usr/bin/env python3
"""One-day official CNINFO earnings-guidance category filter admission.

Only tests 2026-07-15, which remains unbounded in generic full-text search.
No returns. A successful technical page traversal is not evidence that the
taxonomy contains every possible guidance correction.
"""
import argparse
import hashlib
import html
import json
import re
from datetime import datetime,timezone,timedelta
from pathlib import Path
from v29_original_report_discovery_128 import _post

BEIJING=timezone(timedelta(hours=8))
CATEGORY="category_yjygjxz_szsh"
DAY="2026-07-15"
MAX_PAGES=25
def main():
    a=argparse.ArgumentParser();a.add_argument("--output",type=Path,required=True)
    args=a.parse_args()
    page_rows=[];records={};status="PAGE_LIMIT"
    last=set()
    for p in range(1,MAX_PAGES+1):
        res,raw=_post("hisAnnouncement/query",{
         "stock":"","tabName":"fulltext","pageNum":str(p),"pageSize":"30",
         "column":"szse","plate":"","category":CATEGORY,"seDate":DAY+"~"+DAY,
         "isHLtitle":"true","searchkey":""})
        batch=res.get("announcements")
        if batch is None and int(res.get("totalRecordNum") or 0)==0:batch=[]
        if not isinstance(batch,list):raise ValueError("INVALID_CATEGORY_RESPONSE")
        ids=[str(x.get("announcementId") or "") for x in batch]
        state={"page":p,"n":len(ids),"total":res.get("totalRecordNum"),
               "has_more":res.get("hasMore"),
               "raw_sha256":hashlib.sha256(raw).hexdigest()}
        page_rows.append(state)
        if len(ids)!=len(set(ids)) or set(ids)&last or not all(ids):
            status="REPEATED_PAGE_IDS";break
        last=set(ids)
        for row in batch:
            dt=datetime.fromtimestamp(int(row["announcementTime"])/1000,BEIJING).date().isoformat()
            if dt!=DAY:status="OUT_OF_DAY_RESPONSE";break
            t=re.sub(r"\s+","",re.sub(r"<[^>]+>","",html.unescape(str(row.get("announcementTitle") or ""))))
            records[str(row["announcementId"])]={"announcement_id":str(row["announcementId"]),
                "ticker":str(row.get("secCode") or ""), "title":t,"day":dt,
                "pdf_relative_url":str(row.get("adjunctUrl") or "")}
        if status=="OUT_OF_DAY_RESPONSE":break
        print("CATEGORY_PAGE",p,len(batch),"total",res.get("totalRecordNum"),
              "has_more",res.get("hasMore"),flush=True)
        if res.get("hasMore") is False:
            status="PAGINATION_COMPLETE";break
    matching=[x for x in records.values() if "业绩预告" in x["title"]
              and any(w in x["title"] for w in ("修正","修订","更正","调整"))]
    out={"schema":"V32_CNINFO_20260715_EARNINGS_CATEGORY_SOURCE_ADMISSION_V1",
      "day":DAY,"category":CATEGORY,"status":status,
      "distinct_announcements":len(records),"revision_title_count":len(matching),
      "records":records,"revision_candidates":matching,"pages":page_rows,
      "all_market_event_recall_certified":False,
      "prices_opened":False,"buy_authorized":False}
    args.output.write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    print("V32_CATEGORY_DAY_RESULT="+json.dumps({k:v for k,v in out.items()
      if k not in ("records","revision_candidates","pages")},ensure_ascii=False),flush=True)
if __name__=="__main__":main()
