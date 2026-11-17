#!/usr/bin/env python3
"""Exactly six observed 2026 H1 issuer revision events: source-only prior guidance pairing.

Avoids demonstrably broken CNINFO blank-stock global pagination. No claim that
these six are a complete 2026 Jul-Aug market universe. No stock prices.
"""
import argparse
import hashlib
import html
import json
import re
from datetime import datetime,timezone,timedelta
from pathlib import Path
from v29_original_report_discovery_128 import _post

TZ=timezone(timedelta(hours=8))
EVENTS={
 "002977":"1225425185",
 "300670":"1225451215",
 "600889":"1225450112",
 "002933":"1225457917",
 "000096":"1225469212",
 "600187":"1225480593"}
START,END="2026-05-01","2026-08-31"
DOC=re.compile(r"finalpage/(20\d\d-\d\d-\d\d)/(\d+\.PDF)",re.I)

def clean(v):
    return re.sub(r"\s+","",re.sub(r"<[^>]*>","",html.unescape(str(v or ""))))

def is_prior(t):
    return "业绩预告" in t and ("半年" in t or "半年度" in t) and not any(w in t for w in ("修正","更正","修订","补充","调整"))

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    rows=[]
    for code,revision_id in EVENTS.items():
        prefix="SSE" if code.startswith(("600","601","603","605","688")) else "SZSE"
        row={"security_id":prefix+":"+code,"revision_id":revision_id,
             "prior_matching_pdfs":[],"status":"NOT_FOUND"}
        try:
            orgres,raw=_post("information/topSearch/query",{"keyWord":code,"maxNum":"10"})
            matches=orgres if isinstance(orgres,list) else (orgres.get("data") or orgres.get("stockList") or [])
            orgs={str(x["orgId"]) for x in matches if isinstance(x,dict)
                  and str(x.get("code"))==code and x.get("orgId")}
            if len(orgs)!=1:
                row["status"]="ORG_AMBIGUOUS"
            else:
                original=[];queries=[];finished=False
                for i in range(1,5):
                    res,bytes_=_post("hisAnnouncement/query",{
                        "stock":code+","+next(iter(orgs)),
                        "tabName":"fulltext","pageNum":str(i),"pageSize":"30",
                        "column":"sse" if prefix=="SSE" else "szse",
                        "plate":"","category":"","seDate":START+"~"+END,
                        "isHLtitle":"true","searchkey":""})
                    records=res.get("announcements")
                    if not isinstance(records,list):
                        if int(res.get("totalRecordNum") or 0)==0:records=[]
                        else:raise ValueError("INVALID_RECORDS")
                    queries.append({"page":i,"n":len(records),
                                    "sha256":hashlib.sha256(bytes_).hexdigest(),
                                    "hasMore":res.get("hasMore")})
                    original.extend(records)
                    if not res.get("hasMore"):
                        finished=True;break
                # A limited issuer query is not usable if pagination repeats or truncates.
                mapped={}
                for a in original:
                    if str(a.get("secCode"))!=code:continue
                    did=str(a.get("announcementId") or "")
                    if not did:continue
                    t=clean(a.get("announcementTitle"))
                    dt=datetime.fromtimestamp(int(a["announcementTime"])/1000,TZ).isoformat()
                    rel=str(a.get("adjunctUrl") or "")
                    mapped[did]={"announcement_id":did,"title":t,"local_time":dt,
                                  "pdf_url":"https://static.cninfo.com.cn/"+rel if DOC.fullmatch(rel) else None}
                target=mapped.get(revision_id)
                row["revision_in_same_issuer_query"]=target is not None
                if target:row["revision"]=target
                if target:
                    row["prior_matching_pdfs"]=sorted(
                      [m for m in mapped.values() if is_prior(m["title"]) and m["local_time"]<target["local_time"]],
                      key=lambda z:(z["local_time"],z["announcement_id"]))
                row["query_pages"]=queries
                row["distinct_announcement_ids"]=len(mapped)
                row["issuer_query_complete"]=finished and len(mapped)==len(original)
                row["status"]=("ONE_PRIOR_CANDIDATE" if row["issuer_query_complete"] and len(row["prior_matching_pdfs"])==1 else
                               "MULTIPLE_PRIOR_CANDIDATES" if row["prior_matching_pdfs"] else
                               "PRIOR_MISSING_OR_ISSUER_QUERY_INCOMPLETE")
        except (OSError,ValueError,TypeError,KeyError) as ex:
            row["status"]="QUERY_ERROR"
            row["error"]=type(ex).__name__+":"+str(ex)[:130]
        rows.append(row)
        print("ISSUER_REVISION_PAIR",code,row["status"],
              "prior",len(row["prior_matching_pdfs"]),flush=True)
    output={"schema":"V32_SIX_OBSERVED_GUIDANCE_REVISIONS_PRIOR_SOURCE_PAIR_V1",
      "source_of_six":"2026-07-01_to_2026-08-31 keyword-only CNINFO unique announcement IDs; not exhaustive",
      "issuer_pairs_queried":len(rows),
      "one_prior_metadata_candidate_count":sum(r["status"]=="ONE_PRIOR_CANDIDATE" for r in rows),
      "original_pdf_bytes_validated":False,
      "same_period_numeric_pairs_validated":False,
      "global_event_denominator_exhaustive":False,
      "future_stock_outcomes_accessed":False,
      "buy_authorized":False,"rows":rows}
    args.output.write_text(json.dumps(output,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    print("V32_SIX_PAIR_RESULT="+json.dumps({k:v for k,v in output.items() if k!="rows"},ensure_ascii=False),flush=True)

if __name__=="__main__":main()
