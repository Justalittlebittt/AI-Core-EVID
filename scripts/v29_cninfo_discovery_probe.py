#!/usr/bin/env python3
"""Bounded diagnosis of original CNINFO annual-report discovery for known FY2024 issuers.

This is source-shape troubleshooting, not a backtest or an executable trading signal.
"""
import json
from urllib.request import Request,urlopen
from urllib.error import HTTPError,URLError
from urllib.parse import urlencode

HEADERS={
"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
"Referer":"https://www.cninfo.com.cn/",
"Origin":"https://www.cninfo.com.cn",
"X-Requested-With":"XMLHttpRequest",
"Accept":"application/json,text/plain,*/*",
"Content-Type":"application/x-www-form-urlencoded; charset=UTF-8",
}
BASE="https://www.cninfo.com.cn/new/"
CASES=[("SSE","601009"),("SZSE","002493"),("SZSE","300978")]

def request(url,fields):
    req=Request(BASE+url, urlencode(fields).encode(),headers=HEADERS)
    with urlopen(req,timeout=12) as resp:
        return json.loads(resp.read(250000))

def main():
    for exchange,code in CASES:
        try:
            result=request("information/topSearch/query",{"keyWord":code,"maxNum":"10"})
            records=result if isinstance(result,list) else result.get("data") or result.get("stockList") or []
            entries=[{"name":x.get("zwjc"),"code":x.get("code"),
                      "orgId":x.get("orgId"),"pcode":x.get("pcode"),
                      "other_keys":sorted(x)[:14]}
                     for x in records if isinstance(x,dict)]
            print("RESOLVE",code,json.dumps(entries[:5],ensure_ascii=False),flush=True)
        except (HTTPError,URLError,TimeoutError,OSError,ValueError) as ex:
            entries=[]
            print("RESOLVE_ERROR",code,type(ex).__name__,str(ex)[:150],flush=True)
        guessed=("gssh0" if exchange=="SSE" else "gssz0")+code
        resolved=[]
        for item in entries:
            for name in ("code","orgId"):
                value=item.get(name)
                if isinstance(value,str) and value!=code and value not in resolved:
                    resolved.append(value)
        candidates=[guessed]+[x for x in resolved if x!=guessed]
        # Compare (A) legacy guess / category, (B) resolved orgId, (C) no category.
        tests=[(candidates[0],"category_ndbg_szsh", "legacy_guess")]
        if len(candidates)>1:
            tests.append((candidates[1],"category_ndbg_szsh","resolved_org"))
        tests.append((candidates[-1],"","without_category"))
        for org,category,label in tests:
            try:
                result=request("hisAnnouncement/query",{
                    "stock":code+","+org,"tabName":"fulltext","pageNum":"1",
                    "pageSize":"30","column":"sse" if exchange=="SSE" else "szse",
                    "category":category,"seDate":"2025-01-01~2025-12-31",
                    "isHLtitle":"true","plate":"","searchkey":""})
                items=result.get("announcements") or []
                print("DISCOVERY",code,label,"org",org,"count",result.get("totalRecordNum"),
                      "pages",result.get("totalpages"),"hasMore",result.get("hasMore"),
                      "items",len(items),"sample",json.dumps([
                          {"secCode":x.get("secCode"),"title":x.get("announcementTitle"),"url":x.get("adjunctUrl")}
                          for x in items[:4]],ensure_ascii=False),flush=True)
            except (HTTPError,URLError,TimeoutError,OSError,ValueError) as ex:
                print("DISCOVERY_ERROR",code,label,type(ex).__name__,str(ex)[:150],flush=True)

if __name__=="__main__":
    main()
