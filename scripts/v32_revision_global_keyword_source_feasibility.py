#!/usr/bin/env python3
"""Bounded source-only discovery of all keyword-matching earnings guidance revisions.

Crucial: this tests whether CNINFO global issuer search is an exhaustive event
enumerator. It NEVER assumes that a 200 response or keyword search is complete.
No price, trading outcome, ranking, benchmark or frozen research reads.
"""
import argparse
import hashlib
import html
import json
import re
import time
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path
from v29_original_report_discovery_128 import _post

TZ=timezone(timedelta(hours=8))
START="2026-07-01"
END="2026-08-31"
SEARCHES=("业绩预告修正","业绩预告更正","业绩预告修订")
COLUMNS=("szse","sse")
MAX_PAGES=15
PAGE_SIZE=100
TITLE_EVENT=re.compile(r"业绩预告.{0,12}(修正|更正|修订)|(?:修正|更正|修订).{0,12}业绩预告")
PDF=re.compile(r"finalpage/(20\d\d-\d\d-\d\d)/(\d+\.PDF)",re.I)

def clean(s):
    return re.sub(r"\s+","",re.sub(r"<[^>]*>","",html.unescape(str(s or ""))))

def scan(column,keyword):
    records=[]; page_meta=[]; complete=False
    for page in range(1,MAX_PAGES+1):
        response,raw=_post("hisAnnouncement/query",{
            "stock":"","tabName":"fulltext","pageNum":str(page),
            "pageSize":str(PAGE_SIZE),"column":column,"plate":"",
            "category":"","seDate":f"{START}~{END}",
            "isHLtitle":"true","searchkey":keyword})
        if not isinstance(response,dict):
            raise ValueError("GLOBAL_QUERY_RESPONSE_NOT_OBJECT")
        arr=response.get("announcements")
        if not isinstance(arr,list):
            if int(response.get("totalRecordNum") or 0)==0:arr=[]
            else:raise ValueError("GLOBAL_QUERY_ROWS_NOT_LIST")
        page_meta.append({"page":page,"rows":len(arr),
                          "totalRecordNum":response.get("totalRecordNum"),
                          "hasMore":response.get("hasMore"),
                          "sha256":hashlib.sha256(raw).hexdigest()})
        records.extend(arr)
        print("EVENT_SEARCH_PAGE",column,keyword,page,len(arr),
              "TOTAL",response.get("totalRecordNum"),
              "HAS_MORE",response.get("hasMore"),flush=True)
        if not response.get("hasMore"):
            complete=True;break
        time.sleep(.12)
    return records,{"column":column,"keyword":keyword,
                    "source_pagination_complete":complete,
                    "pages":page_meta,"retrieved_records":len(records)}

def extract(raw,column,keyword):
    rows=[]
    for x in raw:
        title=clean(x.get("announcementTitle"))
        if not TITLE_EVENT.search(title):continue
        code=str(x.get("secCode") or "")
        if not re.fullmatch(r"\d{6}",code):continue
        try:
            ts=int(x["announcementTime"])
            local=datetime.fromtimestamp(ts/1000,tz=TZ).isoformat()
        except (KeyError,ValueError,OverflowError,TypeError):continue
        if local[:10]<START or local[:10]>END:continue
        rel=str(x.get("adjunctUrl") or "")
        pdf=PDF.fullmatch(rel)
        rows.append({
          "security_id":("SSE:" if column=="sse" else "SZSE:")+code,
          "title":title,"publication_local":local,
          "announcement_id":str(x.get("announcementId") or ""),
          "pdf_url":"https://static.cninfo.com.cn/"+rel if pdf else None,
          "found_by_keyword":keyword,
          "source_column":column
        })
    return rows

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--output",type=Path,required=True)
    args=p.parse_args()
    sources=[];allrows=[];errors=[]
    for col in COLUMNS:
        for word in SEARCHES:
            try:
                raw,meta=scan(col,word)
                sources.append(meta)
                allrows.extend(extract(raw,col,word))
            except (OSError,ValueError,TypeError) as e:
                errors.append({"column":col,"keyword":word,
                               "type":type(e).__name__,"detail":str(e)[:140]})
                sources.append({"column":col,"keyword":word,
                                "source_pagination_complete":False,"error":type(e).__name__})
    uniq={}
    for row in allrows:
        key=(row["security_id"],row["publication_local"],
             row["announcement_id"],row["title"])
        if key not in uniq:
            uniq[key]=dict(row,matched_keywords=[row["found_by_keyword"]])
        else:
            uniq[key]["matched_keywords"].append(row["found_by_keyword"])
    rows=sorted(uniq.values(),key=lambda r:(r["publication_local"],r["security_id"],r["title"]))
    coverage=all(x.get("source_pagination_complete") is True for x in sources) and not errors
    # Keyword matching alone NEVER proves completeness of the entire revision universe.
    outcome={
      "schema":"V32_2026JUL_AUG_EARNINGS_REVISION_GLOBAL_KEYWORD_FEASIBILITY_V1",
      "window_start":START,"window_end":END,"queries":sources,"errors":errors,
      "source_query_complete":coverage,
      "universe_of_all_earnings_revisions_exhaustively_covered":False,
      "keyword_revision_candidates":len(rows),
      "distinct_issuers":len(set(r["security_id"] for r in rows)),
      "count_pdf_urls":sum(bool(r["pdf_url"]) for r in rows),
      "all_revision_original_pairs_checked":False,
      "issuer_period_numeric_changes_verified":0,
      "status":("KEYWORD_DISCOVERY_PAGINATED_BUT_UNIVERSE_NOT_PROVEN"
                if coverage else "INCOMPLETE_GLOBAL_QUERY_DO_NOT_ASSUME_ZERO_EVENTS"),
      "post_announcement_stock_returns_accessed":False,
      "trading_authorized":False,"rows":rows}
    args.output.write_text(json.dumps(outcome,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    print("V32_GLOBAL_REVISION_DISCOVERY="+json.dumps({
      "status":outcome["status"],"keyword_candidates":len(rows),
      "distinct_issuers":outcome["distinct_issuers"],
      "pdf_urls":outcome["count_pdf_urls"],
      "query_complete":coverage,"errors":errors,
      "complete_universe":False,"stocks_prices_read":False},ensure_ascii=False),flush=True)

if __name__=="__main__":main()
