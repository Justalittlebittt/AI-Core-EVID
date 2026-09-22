from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import time
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlencode

from playwright.sync_api import sync_playwright

ENDPOINT="https://www.cninfo.com.cn/new/hisAnnouncement/query"
HOME="https://www.cninfo.com.cn/"
PAGE_SIZE=30
TERMS=[
    "人工智能","生成式人工智能","大模型","基础模型","机器学习","深度学习",
    "AI芯片","人工智能芯片","NPU","GPU","AI服务器","智算","算力",
    "机器视觉","AI算法","人工智能算法","自动驾驶","具身智能"
]
ROUTES={
    "SSE":{"column":"sse","plate":"sh","exchange":"SSE"},
    "SZSE":{"column":"","plate":"sz","exchange":"SZSE"},
}

def stable_sha256(obj)->str:
    b=json.dumps(obj,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()
    return hashlib.sha256(b).hexdigest()

def canonical_id(exchange:str, sec_code:str)->str:
    c=str(sec_code or "").strip()
    if not re.fullmatch(r"\d{6}",c):
        raise RuntimeError("UNMAPPED_SECURITY_CODE")
    return f"{exchange}:{c}"

def partitions(start:date,end:date,days:int=7)->list[tuple[date,date]]:
    if end<start:
        raise ValueError("end before start")
    out=[]
    cur=start
    while cur<=end:
        stop=min(end,cur+timedelta(days=days-1))
        out.append((cur,stop))
        cur=stop+timedelta(days=1)
    return out

def normalize_hit(stream:str,term:str,window:str,a:dict)->dict:
    route=ROUTES[stream]
    aid=str(a.get("announcementId") or "").strip()
    sec=str(a.get("secCode") or "").strip()
    adjunct=str(a.get("adjunctUrl") or "").strip()
    if not aid:
        raise RuntimeError("MISSING_ANNOUNCEMENT_ID")
    cid=canonical_id(route["exchange"],sec)
    m=re.fullmatch(r"finalpage/(\d{4}-\d{2}-\d{2})/(\d+)\.pdf",adjunct,re.I)
    if not m or m.group(2)!=aid:
        raise RuntimeError("INVALID_OFFICIAL_LOCATOR")
    return {
        "announcement_id":aid,
        "canonical_security_id":cid,
        "exchange":route["exchange"],
        "security_code":sec,
        "security_name":str(a.get("secName") or "").strip(),
        "announcement_title":re.sub(r"</?em>","",str(a.get("announcementTitle") or ""),flags=re.I),
        "announcement_time":a.get("announcementTime"),
        "adjunct_url":adjunct,
        "path_disclosure_date":m.group(1),
        "matched_term":term,
        "query_window":window,
        "stream":stream,
    }

def merge_hits(rows:list[dict])->list[dict]:
    by={}
    terms=defaultdict(set)
    windows=defaultdict(set)
    for r in rows:
        aid=r["announcement_id"]
        core={k:v for k,v in r.items() if k not in {"matched_term","query_window"}}
        if aid in by:
            for k in ("canonical_security_id","adjunct_url","announcement_time"):
                if by[aid].get(k)!=core.get(k):
                    raise RuntimeError(f"ANNOUNCEMENT_ID_CONFLICT:{aid}:{k}")
        else:
            by[aid]=core
        terms[aid].add(r["matched_term"])
        windows[aid].add(r["query_window"])
    out=[]
    for aid in sorted(by):
        x=dict(by[aid])
        x["matched_terms"]="|".join(sorted(terms[aid]))
        x["query_windows"]="|".join(sorted(windows[aid]))
        out.append(x)
    return out

def request_page(api,stream,term,start,end,page):
    route=ROUTES[stream]
    payload={
        "pageNum":str(page),"pageSize":str(PAGE_SIZE),"tabName":"fulltext",
        "column":route["column"],"stock":"","searchkey":term,"secid":"",
        "plate":route["plate"],"category":"","trade":"",
        "seDate":f"{start.isoformat()}~{end.isoformat()}",
        "sortName":"time","sortType":"desc","isHLtitle":"true",
    }
    last=None
    for attempt in range(3):
        r=api.post(
            ENDPOINT,data=urlencode(payload),
            headers={
                "Content-Type":"application/x-www-form-urlencoded; charset=UTF-8",
                "X-Requested-With":"XMLHttpRequest",
                "Referer":"https://www.cninfo.com.cn/new/fulltextSearch",
            },timeout=60000,
        )
        last=r.status
        if last==200: break
        if last not in (429,500,502,503,504):
            raise RuntimeError(f"CNINFO_HTTP_{last}")
        time.sleep(1.5*(attempt+1))
    if last!=200:
        raise RuntimeError(f"CNINFO_HTTP_{last}_AFTER_RETRIES")
    obj=r.json()
    total=int(obj.get("totalRecordNum") or obj.get("totalAnnouncement") or 0)
    raw=obj.get("announcements")
    if not (isinstance(raw,list) or (raw is None and total==0)):
        raise RuntimeError("CNINFO_RESPONSE_SHAPE_INVALID")
    return payload,total,(raw or [])

def collect(start:date,end:date,out_dir:Path):
    out_dir.mkdir(parents=True,exist_ok=True)
    raw_rows=[]
    page_receipts=[]
    with sync_playwright() as pw:
        api=pw.request.new_context(extra_http_headers={
            "User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/153 Safari/537.36"
        })
        home=api.get(HOME,timeout=30000)
        if home.status!=200:
            raise RuntimeError(f"CNINFO_HOME_HTTP_{home.status}")
        for stream in ("SSE","SZSE"):
            for term in TERMS:
                for a,b in partitions(start,end):
                    payload,total,anns=request_page(api,stream,term,a,b,1)
                    pages=max(1,math.ceil(total/PAGE_SIZE)) if total else 1
                    got=list(anns)
                    for page in range(2,pages+1):
                        _payload,t2,a2=request_page(api,stream,term,a,b,page)
                        if t2!=total:
                            raise RuntimeError("PAGINATION_TOTAL_DRIFT")
                        got.extend(a2)
                    if len(got)!=total:
                        raise RuntimeError(f"PAGINATION_NOT_CLOSED:{stream}:{term}:{a}:{len(got)}:{total}")
                    window=f"{a.isoformat()}~{b.isoformat()}"
                    for x in got:
                        raw_rows.append(normalize_hit(stream,term,window,x))
                    page_receipts.append({
                        "stream":stream,"term":term,"window":window,
                        "server_total":total,"pages":pages,
                        "query_sha256":stable_sha256(payload)
                    })
        api.dispose()

    merged=merge_hits(raw_rows)
    raw_path=out_dir/"V2.8.4_CNINFO_CANDIDATE_RAW_HITS.csv"
    merged_path=out_dir/"V2.8.4_CNINFO_CANDIDATE_DEDUPED.csv"
    fields_raw=[
        "announcement_id","canonical_security_id","exchange","security_code","security_name",
        "announcement_title","announcement_time","adjunct_url","path_disclosure_date",
        "matched_term","query_window","stream"
    ]
    with raw_path.open("w",encoding="utf-8",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields_raw,lineterminator="\n"); w.writeheader(); w.writerows(raw_rows)
    fields_merged=[
        "announcement_id","canonical_security_id","exchange","security_code","security_name",
        "announcement_title","announcement_time","adjunct_url","path_disclosure_date",
        "stream","matched_terms","query_windows"
    ]
    with merged_path.open("w",encoding="utf-8",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields_merged,lineterminator="\n"); w.writeheader(); w.writerows(merged)
    receipt={
        "schema":"AI_CORE_EVID_V2_8_4_CNINFO_CANDIDATE_COLLECTION_RECEIPT_V1",
        "window_start":start.isoformat(),"window_end":end.isoformat(),
        "terms":TERMS,"routes":ROUTES,
        "raw_hit_rows":len(raw_rows),"deduped_announcements":len(merged),
        "page_receipts":page_receipts,
        "real_security_classification_computed":False,
        "price_or_return_data_consumed":False,
        "eligibility_effect":"NONE_CANDIDATE_HINT_ONLY",
    }
    receipt["receipt_sha256"]=stable_sha256(receipt)
    (out_dir/"V2.8.4_CNINFO_CANDIDATE_COLLECTION_RECEIPT.json").write_text(
        json.dumps(receipt,ensure_ascii=False,indent=2)+"\n",encoding="utf-8"
    )
    print(json.dumps(receipt,ensure_ascii=False,indent=2))

def self_test():
    tests=[]
    def ck(name,cond): tests.append({"name":name,"pass":bool(cond)})
    p=partitions(date(2026,9,1),date(2026,9,22),7)
    ck("C01_partition_count",len(p)==4)
    ck("C02_partition_first",p[0]==(date(2026,9,1),date(2026,9,7)))
    ck("C03_partition_last",p[-1]==(date(2026,9,22),date(2026,9,22)))
    a={
      "announcementId":"123","secCode":"600001","secName":"A",
      "announcementTitle":"<em>人工智能</em>公告",
      "announcementTime":1,"adjunctUrl":"finalpage/2026-09-01/123.PDF"
    }
    r1=normalize_hit("SSE","人工智能","2026-09-01~2026-09-07",a)
    r2=normalize_hit("SSE","大模型","2026-09-01~2026-09-07",a)
    m=merge_hits([r1,r2])
    ck("C04_sse_identity",r1["canonical_security_id"]=="SSE:600001")
    ck("C05_title_highlight_removed",r1["announcement_title"]=="人工智能公告")
    ck("C06_dedupe_by_announcement_id",len(m)==1)
    ck("C07_terms_merged",m[0]["matched_terms"]=="人工智能|大模型")
    b=dict(a); b["secCode"]="300001"; b["announcementId"]="456"; b["adjunctUrl"]="finalpage/2026-09-02/456.PDF"
    r3=normalize_hit("SZSE","人工智能","2026-09-01~2026-09-07",b)
    ck("C08_szse_identity",r3["canonical_security_id"]=="SZSE:300001")
    bad=False
    try:
        normalize_hit("SSE","人工智能","x",{**a,"adjunctUrl":"finalpage/2026-09-01/999.PDF"})
    except RuntimeError:
        bad=True
    ck("C09_locator_mismatch_blocks",bad)
    conflict=False
    try:
        merge_hits([r1,{**r2,"adjunct_url":"finalpage/2026-09-01/999.PDF"}])
    except RuntimeError:
        conflict=True
    ck("C10_duplicate_conflict_blocks",conflict)
    ck("C11_term_registry_frozen",len(TERMS)==18 and len(set(TERMS))==18)
    result={"schema":"AI_CORE_EVID_V2_8_4_CANDIDATE_COLLECTOR_SELFTEST_V1",
            "tests":tests,"passed":sum(x["pass"] for x in tests),"total":len(tests),
            "all_pass":all(x["pass"] for x in tests)}
    result["receipt_sha256"]=stable_sha256(result)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    if not result["all_pass"]: raise SystemExit(2)

def main():
    ap=argparse.ArgumentParser()
    sub=ap.add_subparsers(dest="cmd",required=True)
    sub.add_parser("self-test")
    c=sub.add_parser("collect")
    c.add_argument("--start",required=True)
    c.add_argument("--end",required=True)
    c.add_argument("--out",default="v284_candidates")
    a=ap.parse_args()
    if a.cmd=="self-test":
        self_test()
    else:
        collect(date.fromisoformat(a.start),date.fromisoformat(a.end),Path(a.out))

if __name__=="__main__":
    main()
