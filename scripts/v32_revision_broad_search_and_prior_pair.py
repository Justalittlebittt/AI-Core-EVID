#!/usr/bin/env python3
"""V3.2 bounded source-only global revision denominator correction and original pairing.

CNINFO 'column' with blank 'stock' is demonstrably ignored; count distinct
announcement IDs and derive exchange from ticker instead of query column.
Compare broader guidance search; original pairs are metadata candidates,
not certified field values, original PDF binaries, or predictive returns.
"""
import argparse
import hashlib
import html
import json
import re
import time
from collections import Counter
from datetime import datetime,timezone,timedelta
from pathlib import Path
from v29_original_report_discovery_128 import _post

TZ=timezone(timedelta(hours=8))
START="2026-07-01"
END="2026-08-31"
LOOKBACK_START="2026-05-01"
WORD="业绩预告"
REV=re.compile(r"(修正|更正|修订|调整)")
DOC=re.compile(r"finalpage/(20\d\d-\d\d-\d\d)/(\d+\.PDF)",re.I)
MAX_PAGE=15
SIZE=100

def title(s):
    return re.sub(r"\s+","",re.sub(r"<[^>]+>","",html.unescape(str(s or ""))))

def exchange(code):
    if code.startswith(("600","601","603","605","688","689","900")):return "SSE"
    if code.startswith(("000","001","002","003","300","301","200")):return "SZSE"
    return "UNKNOWN"

def search(query,word,pagecap=MAX_PAGE):
    rows=[];pages=[];finished=False
    for page in range(1,pagecap+1):
        raw,res=_post("hisAnnouncement/query",{
            "stock":query,"tabName":"fulltext","pageNum":str(page),
            "pageSize":str(SIZE),"column":"szse","plate":"",
            "category":"","seDate":f"{START}~{END}" if not query else f"{LOOKBACK_START}~{END}",
            "isHLtitle":"true","searchkey":word})
        if not isinstance(raw,dict):raise ValueError("INVALID_RESPONSE")
        batch=raw.get("announcements")
        if batch is None and int(raw.get("totalRecordNum") or 0)==0:batch=[]
        if not isinstance(batch,list):raise ValueError("MALFORMED_ANNOUNCEMENTS")
        pages.append({"page":page,"n":len(batch),"total":raw.get("totalRecordNum"),
                      "hasMore":raw.get("hasMore"),"source_sha256":hashlib.sha256(res).hexdigest()})
        rows.extend(batch)
        print("SOURCE_QUERY",query or "GLOBAL",word,page,len(batch),"MORE",raw.get("hasMore"),flush=True)
        if not raw.get("hasMore"):finished=True;break
        time.sleep(.08)
    return rows,{"complete":finished,"pages":pages}

def maprow(row):
    code=str(row.get("secCode") or "")
    if not re.fullmatch(r"\d{6}",code):return None
    try:
        moment=datetime.fromtimestamp(int(row["announcementTime"])/1000,TZ).isoformat()
    except (ValueError,TypeError,KeyError,OverflowError):return None
    t=title(row.get("announcementTitle"))
    url=str(row.get("adjunctUrl") or "")
    return {"security_id":exchange(code)+":"+code,
        "announcement_id":str(row.get("announcementId") or ""),
        "title":t,"publication_local":moment,
        "original_pdf_url":"https://static.cninfo.com.cn/"+url if DOC.fullmatch(url) else None}

def main():
    p=argparse.ArgumentParser();p.add_argument("--output",type=Path,required=True)
    args=p.parse_args()
    global_list,global_meta=search("",WORD)
    broad={}
    for a in global_list:
        row=maprow(a)
        if not row or not row["announcement_id"]:continue
        broad[row["announcement_id"]]=row
    revision=[r for r in broad.values() if REV.search(r["title"]) and WORD in r["title"]]
    revision.sort(key=lambda r:(r["publication_local"],r["security_id"]))
    paired=[]
    for event in revision:
        code=event["security_id"].split(":")[1]
        originals=[];error=None;org_info={}
        try:
            tops,topbytes=_post("information/topSearch/query",{"keyWord":code,"maxNum":"10"})
            hits=tops if isinstance(tops,list) else (tops.get("data") or tops.get("stockList") or [])
            orgs={str(x.get("orgId")) for x in hits if isinstance(x,dict)
                  and str(x.get("code"))==code and x.get("orgId")}
            org_info={"org_candidate_count":len(orgs),"org_query_sha256":hashlib.sha256(topbytes).hexdigest()}
            if len(orgs)!=1:
                error="ORG_AMBIGUOUS"
            else:
                orig,ometa=search(code+","+next(iter(orgs)),WORD,pagecap=5)
                org_info["query_meta"]=ometa
                for x in orig:
                    row=maprow(x)
                    if row is None or row["security_id"]!=event["security_id"]:continue
                    if not row["publication_local"]<event["publication_local"]:continue
                    if WORD not in row["title"] or REV.search(row["title"]):continue
                    if not ("半年度" in row["title"] or "半年" in row["title"]):continue
                    originals.append(row)
        except (OSError,ValueError,TypeError) as e:
            error=type(e).__name__+":"+str(e)[:120]
        originals.sort(key=lambda x:(x["publication_local"],x["announcement_id"]))
        paired.append({**event,
            "original_candidates":originals,
            "same_issuer_earlier_half_year_announcement_count":len(originals),
            "original_source_status":"PRIOR_METADATA_CANDIDATE" if len(originals)==1
                else "MULTIPLE_PRIOR_ANNOUNCEMENTS_VERSION_DISAMBIGUATION" if originals
                else "NO_PRIOR_ORIGINAL_DISCOVERED",
            "query_error":error,"source_meta":org_info})
        print("EVENT_PAIR",event["security_id"],event["announcement_id"],len(originals),error,flush=True)
    result={"schema":"V32_2026_H1_GUIDANCE_REVISION_BROAD_SEARCH_AND_PRIOR_VERSION_PAIR_V1",
        "search_window":[START,END],
        "broad_query_total":len(global_list),
        "broad_query_unique_announcement_ids":len(broad),
        "broad_source_query_complete":global_meta["complete"],
        "broad_source_meta":global_meta,
        "unique_guidance_revision_title_hits":len(revision),
        "matched_prior_metadata_one":sum(r["original_source_status"]=="PRIOR_METADATA_CANDIDATE" for r in paired),
        "prior_unresolved_count":sum(r["original_source_status"]!="PRIOR_METADATA_CANDIDATE" for r in paired),
        "global_announcement_feed_full_market_completeness_proven":False,
        "title_variants_outside_revision_regex_may_be_missing":True,
        "original_pdf_bytes_verified":0,"period_and_field_semantics_verified":0,
        "stocks_and_benchmark_outcomes_opened":False,"trade_authorized":False,
        "rows":paired}
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("V32_REVISION_PAIR_SUMMARY="+json.dumps({k:v for k,v in result.items()
      if k not in ("rows","broad_source_meta")},ensure_ascii=False),flush=True)
if __name__=="__main__":main()
