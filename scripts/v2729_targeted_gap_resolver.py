from __future__ import annotations
import csv, hashlib, html, json, re
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from playwright.sync_api import sync_playwright

GAPS=Path("evidence/V2.7.28_PERIODIC_COVERAGE_GAPS.csv")
MAP=Path("evidence/V2.7.27_SECURITY_ISSUER_PIT_MAP.csv")
OUT=Path("v2729_gap_resolver")
RAW=OUT/"raw"; PDF=OUT/"pdf"
RAW.mkdir(parents=True,exist_ok=True); PDF.mkdir(parents=True,exist_ok=True)
CUTOFF="2026-09-16"
HISTORY_START="2020-01-01"
IPO_START="2024-01-01"
BEIJING=ZoneInfo("Asia/Shanghai")
CATS={"ANNUAL":"category_ndbg_szsh","HALF_YEAR":"category_bndbg_szsh"}

def sha(b:bytes)->str: return hashlib.sha256(b).hexdigest()

def clean_title(s):
    s=html.unescape(re.sub(r"<[^>]+>","",str(s or "")))
    return re.sub(r"\s+","",s)

def ann_date(ms):
    try:
        return datetime.fromtimestamp(int(ms)/1000,tz=timezone.utc).astimezone(BEIJING).date().isoformat()
    except Exception:
        return ""

def period_from_title(title,kind):
    t=clean_title(title)
    years=re.findall(r"(20\d{2})年",t)
    y=int(years[0]) if years else None
    pe=(f"{y}-12-31" if kind=="ANNUAL" else f"{y}-06-30") if y else ""
    return y,pe

def is_full_periodic(title):
    t=clean_title(title)
    reject=("摘要","英文版","英文版本","审计报告","财务报告","审阅报告")
    return bool(t) and not any(x in t for x in reject)

def is_revision(title):
    t=clean_title(title)
    return any(x in t for x in ("修订","更正","修正","更新","补充"))

def is_ipo_prospectus(title):
    t=clean_title(title)
    if "招股说明书" not in t: return False
    reject=("提示性公告","摘要","声明","问询回复","审核问询","上市公告书")
    return not any(x in t for x in reject)

def post(page,payload):
    q=page.evaluate("""async (payload) => {
      const body=new URLSearchParams(payload).toString();
      const r=await fetch('/new/hisAnnouncement/query',{
        method:'POST',
        headers:{'Content-Type':'application/x-www-form-urlencoded; charset=UTF-8','X-Requested-With':'XMLHttpRequest'},
        body
      });
      return {status:r.status,text:await r.text()};
    }""",payload)
    if q["status"]!=200: raise RuntimeError(f"CNInfo HTTP {q['status']}")
    return q["text"]

def complete_query(page,base,outdir):
    outdir.mkdir(parents=True,exist_ok=True)
    first=post(page,{**base,"pageNum":"1","pageSize":"30"})
    obj=json.loads(first)
    total=int(obj.get("totalRecordNum") or obj.get("totalAnnouncement") or 0)
    page_size=int(obj.get("pageSize") or 30)
    if page_size<=0: page_size=30
    pages=(total+page_size-1)//page_size if total else 0
    rows=[]; ids=set(); manifest=[]
    for n in range(1,pages+1):
        txt=first if n==1 else post(page,{**base,"pageNum":str(n),"pageSize":"30"})
        b=txt.encode()
        p=outdir/f"page_{n:03d}.json"; p.write_bytes(b)
        o=json.loads(txt); anns=o.get("announcements") or []
        for a in anns:
            aid=str(a.get("announcementId") or "").strip()
            if aid:
                if aid in ids: raise RuntimeError(f"duplicate announcementId {aid}")
                ids.add(aid)
            rows.append(a)
        manifest.append({"page":n,"rows":len(anns),"sha256":sha(b),"bytes":len(b)})
    if len(rows)!=total:
        raise RuntimeError(f"query pagination incomplete {len(rows)} != {total}")
    if len(ids)!=total and total:
        raise RuntimeError(f"query unique IDs incomplete {len(ids)} != {total}")
    return rows,{"total":total,"pages":pages,"manifest":manifest}

def select_periodic(cands):
    if not cands: return None,None
    cands=sorted(cands,key=lambda x:(x["period_end"],x["disclosure_date"],x["announcement_id"]))
    latest_period=cands[-1]["period_end"]
    same=[x for x in cands if x["period_end"]==latest_period]
    revised=[x for x in same if x["revision"]]
    pool=revised or same
    maxdate=max(x["disclosure_date"] for x in pool)
    top=[x for x in pool if x["disclosure_date"]==maxdate]
    if len(top)!=1:
        return None,f"AMBIGUOUS_PERIODIC_{latest_period}_{maxdate}_{len(top)}"
    return top[0],None

def select_ipo(cands):
    if not cands: return None,None
    # Prefer final prospectus over registration draft when both exist.
    final=[x for x in cands if "注册稿" not in x["title"]]
    pool=final or cands
    maxdate=max(x["disclosure_date"] for x in pool)
    top=[x for x in pool if x["disclosure_date"]==maxdate]
    # Same-day multiple distinct prospectuses are ambiguous.
    uniq={x["announcement_id"]:x for x in top}
    if len(uniq)!=1:
        return None,f"AMBIGUOUS_IPO_{maxdate}_{len(uniq)}"
    return next(iter(uniq.values())),None

def download_pdf(ctx,row,cid):
    adj=row["adjunct_url"].lstrip("/")
    urls=[
      "https://static.cninfo.com.cn/"+adj,
      "https://disc.static.szse.cn/download/"+adj if cid.startswith("SZSE:") else None
    ]
    attempts=[]
    for url in [x for x in urls if x]:
        try:
            r=ctx.request.get(url,timeout=90000,headers={"Referer":"https://www.cninfo.com.cn/"})
            b=r.body()
            off=b[:1024].find(b"%PDF-")
            d={"url":url,"status":r.status,"content_type":r.headers.get("content-type"),
               "bytes":len(b),"sha256":sha(b),"pdf_header_offset":off}
            attempts.append(d)
            if r.status==200 and off>=0:
                p=PDF/(cid.replace(":","_")+".pdf"); p.write_bytes(b)
                return {**d,"path":str(p),"attempts":attempts}
        except Exception as e:
            attempts.append({"url":url,"error":repr(e)})
    raise RuntimeError(f"{cid}: official PDF download failed {attempts}")

def main():
    started=datetime.now(timezone.utc)
    gaps=list(csv.DictReader(GAPS.open(encoding="utf-8")))
    maps={r["canonical_security_id"]:r for r in csv.DictReader(MAP.open(encoding="utf-8"))}
    if len(gaps)!=14: raise RuntimeError(f"expected 14 gaps, got {len(gaps)}")

    receipt={"schema":"AI_CORE_EVID_V2_7_29_TARGETED_GAP_RESOLVER_V1",
             "pit_date":"2026-09-17","cutoff_inclusive":CUTOFF,
             "started_at_utc":started.isoformat(),"records":[]}

    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True)
        ctx=browser.new_context(
          user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/153 Safari/537.36",
          locale="zh-CN")
        page=ctx.new_page()
        page.goto("https://www.cninfo.com.cn/",wait_until="domcontentloaded",timeout=90000)
        page.wait_for_timeout(2000)

        stocks={}
        for ex,path in (("SSE","/new/data/sse_stock.json"),("SZSE","/new/data/szse_stock.json")):
            q=page.evaluate("""async (path) => {
              const r=await fetch(path,{credentials:'same-origin'});
              return {status:r.status,text:await r.text()};
            }""",path)
            if q["status"]!=200: raise RuntimeError(f"{ex} stock dictionary HTTP {q['status']}")
            b=q["text"].encode(); (RAW/f"{ex}_stock.json").write_bytes(b)
            obj=json.loads(q["text"])
            for x in obj.get("stockList") or []:
                code=str(x.get("code") or "").strip()
                org=str(x.get("orgId") or "").strip()
                if code and org: stocks[(ex,code)]=org

        for g in gaps:
            cid=g["canonical_security_id"]; ex=g["exchange"]; code=g["security_code"]
            m=maps[cid]; org=stocks.get((ex,code))
            if not org: raise RuntimeError(f"{cid}: CNInfo orgId unresolved")
            column="sse" if ex=="SSE" else "szse"
            plate="sh" if ex=="SSE" else "sz"
            rec={"canonical_security_id":cid,"exchange":ex,"security_code":code,
                 "issuer_legal_name":m["issuer_legal_name"],"official_list_date":m["official_list_date"],
                 "cninfo_org_id":org}

            periodic=[]
            qmeta={}
            for kind,cat in CATS.items():
                base={"column":column,"tabName":"fulltext","plate":plate,
                      "stock":f"{code},{org}","searchkey":"","secid":"","category":cat,
                      "trade":"","seDate":f"{HISTORY_START}~{CUTOFF}",
                      "sortName":"","sortType":"","isHLtitle":"true"}
                rows,meta=complete_query(page,base,RAW/cid.replace(":","_")/kind)
                qmeta[kind]=meta
                for a in rows:
                    d=ann_date(a.get("announcementTime"))
                    title=clean_title(a.get("announcementTitle"))
                    y,pe=period_from_title(title,kind)
                    if d and d<=CUTOFF and pe and is_full_periodic(title):
                        periodic.append({
                          "document_type":"ANNUAL_REPORT" if kind=="ANNUAL" else "SEMIANNUAL_REPORT",
                          "kind":kind,"title":title,"disclosure_date":d,"report_year":y,
                          "period_end":pe,"revision":is_revision(title),
                          "announcement_id":str(a.get("announcementId") or ""),
                          "adjunct_url":str(a.get("adjunctUrl") or "")
                        })
            selected,err=select_periodic(periodic)
            rec["periodic_queries"]=qmeta
            rec["periodic_candidate_count"]=len(periodic)
            rec["periodic_selector_error"]=err

            if err: raise RuntimeError(f"{cid}: {err}")
            if selected:
                rec["resolution"]="HISTORICAL_PERIODIC"
                rec["selected"]=selected
            else:
                base={"column":column,"tabName":"fulltext","plate":plate,
                      "stock":f"{code},{org}","searchkey":"招股说明书","secid":"","category":"",
                      "trade":"","seDate":f"{IPO_START}~{CUTOFF}",
                      "sortName":"","sortType":"","isHLtitle":"true"}
                rows,meta=complete_query(page,base,RAW/cid.replace(":","_")/"IPO")
                ipo=[]
                for a in rows:
                    d=ann_date(a.get("announcementTime")); title=clean_title(a.get("announcementTitle"))
                    if d and d<=CUTOFF and is_ipo_prospectus(title):
                        ipo.append({
                          "document_type":"IPO_PROSPECTUS","title":title,"disclosure_date":d,
                          "period_end":"","revision":is_revision(title),
                          "announcement_id":str(a.get("announcementId") or ""),
                          "adjunct_url":str(a.get("adjunctUrl") or "")
                        })
                selected,err=select_ipo(ipo)
                rec["ipo_query"]=meta
                rec["ipo_candidate_count"]=len(ipo)
                rec["ipo_selector_error"]=err
                if err: raise RuntimeError(f"{cid}: {err}")
                if selected:
                    rec["resolution"]="IPO_FALLBACK"
                    rec["selected"]=selected
                else:
                    rec["resolution"]="NONE"
                    rec["taxonomy_code"]="NA"

            if rec["resolution"]!="NONE":
                rec["pdf"]=download_pdf(ctx,rec["selected"],cid)
            receipt["records"].append(rec)
            print(f"RESOLVED {cid} -> {rec['resolution']}",flush=True)
        browser.close()

    counts={}
    for r in receipt["records"]: counts[r["resolution"]]=counts.get(r["resolution"],0)+1
    receipt["resolution_counts"]=counts
    receipt["resolved_with_primary_count"]=sum(1 for r in receipt["records"] if r["resolution"]!="NONE")
    receipt["none_count"]=counts.get("NONE",0)
    receipt["gate"]={
      "query_complete":len(receipt["records"])==14,
      "all_selected_pdfs_valid":all(
        r["resolution"]=="NONE" or r.get("pdf",{}).get("pdf_header_offset",-1)>=0 for r in receipt["records"]
      ),
      "status":"TARGETED_GAP_RESOLUTION_PASS"
    }
    receipt["finished_at_utc"]=datetime.now(timezone.utc).isoformat()
    canon=json.dumps(receipt,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()
    receipt["receipt_sha256"]=sha(canon)
    p=OUT/"V2.7.29_TARGETED_GAP_RESOLUTION_RECEIPT.json"
    p.write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")

    fields=["canonical_security_id","exchange","security_code","issuer_legal_name","official_list_date",
            "resolution","document_type","title","disclosure_date","period_end","announcement_id",
            "pdf_bytes","pdf_sha256"]
    with (OUT/"V2.7.29_TARGETED_GAP_SELECTION.csv").open("w",encoding="utf-8",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,lineterminator="\n"); w.writeheader()
        for r in receipt["records"]:
            s=r.get("selected") or {}; p=r.get("pdf") or {}
            w.writerow({
              "canonical_security_id":r["canonical_security_id"],"exchange":r["exchange"],
              "security_code":r["security_code"],"issuer_legal_name":r["issuer_legal_name"],
              "official_list_date":r["official_list_date"],"resolution":r["resolution"],
              "document_type":s.get("document_type",""),"title":s.get("title",""),
              "disclosure_date":s.get("disclosure_date",""),"period_end":s.get("period_end",""),
              "announcement_id":s.get("announcement_id",""),"pdf_bytes":p.get("bytes",""),
              "pdf_sha256":p.get("sha256","")
            })
    print(json.dumps(receipt,ensure_ascii=False,indent=2))

if __name__=="__main__": main()
