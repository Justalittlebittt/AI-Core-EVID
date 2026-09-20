from __future__ import annotations
import csv, hashlib, html, json, re
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from playwright.sync_api import sync_playwright

PIT="2026-09-17"
CUTOFF="2026-09-16"
MAP=Path("evidence/V2.7.27_SECURITY_ISSUER_PIT_MAP.csv")
CAT=Path("evidence/V2.7.28_PERIODIC_CATALOG.csv")
GAPS=Path("evidence/V2.7.28_PERIODIC_COVERAGE_GAPS.csv")
AMB=Path("evidence/V2.7.29_TARGETED_AMBIGUITY_RESOLUTION.json")
OUT=Path("v2729_locator_inventory")
RAW=OUT/"raw_gap_queries"
OUT.mkdir(exist_ok=True); RAW.mkdir(parents=True,exist_ok=True)
BEIJING=ZoneInfo("Asia/Shanghai")
CATS={"ANNUAL":"category_ndbg_szsh","HALF_YEAR":"category_bndbg_szsh"}

def sha(b:bytes)->str: return hashlib.sha256(b).hexdigest()

def clean_title(s:str)->str:
    return re.sub(r"\s+","",html.unescape(re.sub(r"<[^>]+>","",str(s or ""))))

def ann_date(ms):
    try:
        return datetime.fromtimestamp(int(ms)/1000,tz=timezone.utc).astimezone(BEIJING).date().isoformat()
    except Exception:
        return ""

def period_from_title(title,kind):
    t=clean_title(title)
    years=re.findall(r"(20\d{2})年",t)
    y=int(years[0]) if years else None
    if not y: return None,""
    return y, f"{y}-12-31" if kind=="ANNUAL" else f"{y}-06-30"

def is_full_periodic(title):
    t=clean_title(title)
    return bool(t) and not any(x in t for x in ("摘要","英文版","英文版本","审计报告","财务报告","审阅报告"))

def is_revision(title):
    t=clean_title(title)
    return any(x in t for x in ("修订","更正","修正","更新","补充"))

def is_ipo_prospectus(title):
    t=clean_title(title)
    if "招股说明书" not in t: return False
    return not any(x in t for x in ("提示性公告","摘要","声明","问询回复","审核问询","上市公告书"))

def select_periodic(cands):
    if not cands: return None,None
    latest=max(x["period_end"] for x in cands)
    same=[x for x in cands if x["period_end"]==latest]
    revised=[x for x in same if x["revision"]]
    pool=revised or same
    maxdate=max(x["disclosure_date"] for x in pool)
    top=[x for x in pool if x["disclosure_date"]==maxdate]
    uniq={x["announcement_id"]:x for x in top}
    if len(uniq)!=1:
        return None,f"AMBIGUOUS_PERIODIC_{latest}_{maxdate}_{len(uniq)}"
    return next(iter(uniq.values())),None

def select_ipo(cands):
    if not cands: return None,None
    final=[x for x in cands if "注册稿" not in x["title"]]
    pool=final or cands
    maxdate=max(x["disclosure_date"] for x in pool)
    top={x["announcement_id"]:x for x in pool if x["disclosure_date"]==maxdate}
    if len(top)!=1:
        return None,f"AMBIGUOUS_IPO_{maxdate}_{len(top)}"
    return next(iter(top.values())),None

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
    rows=[]; ids=set(); page=1
    # Do NOT trust CNInfo totalpages; fetch until exact total is closed.
    while len(rows)<total:
        txt=first if page==1 else post(page_obj,{**base,"pageNum":str(page),"pageSize":"30"})
        b=txt.encode("utf-8")
        (outdir/f"page_{page:03d}.json").write_bytes(b)
        o=json.loads(txt); anns=o.get("announcements") or []
        if not anns and len(rows)<total:
            raise RuntimeError(f"pagination stopped early {len(rows)} / {total}")
        for a in anns:
            aid=str(a.get("announcementId") or "").strip()
            if aid:
                if aid in ids: continue
                ids.add(aid)
            rows.append(a)
        page += 1
        if page>1000: raise RuntimeError("pagination runaway")
    if len(rows)!=total:
        raise RuntimeError(f"pagination count mismatch {len(rows)} != {total}")
    return rows,{"total":total,"pages_fetched":page-1}

def main():
    global page_obj
    started=datetime.now(timezone.utc)
    map_rows=list(csv.DictReader(MAP.open(encoding="utf-8")))
    if len(map_rows)!=5221: raise RuntimeError(f"mother map count {len(map_rows)} != 5221")
    map_by={r["canonical_security_id"]:r for r in map_rows}
    cat=list(csv.DictReader(CAT.open(encoding="utf-8")))
    gaps=list(csv.DictReader(GAPS.open(encoding="utf-8")))
    amb_doc=json.loads(AMB.read_text(encoding="utf-8"))
    amb=amb_doc.get("resolutions") or {}
    gap_ids={r["canonical_security_id"] for r in gaps}
    if len(gap_ids)!=14: raise RuntimeError(f"expected 14 gaps, got {len(gap_ids)}")

    by_cid={}
    for r in cat:
        cid=r["canonical_security_id"]
        if cid not in map_by: continue
        if r.get("is_summary")=="true" or r.get("is_english")=="true" or not r.get("report_period_end"): continue
        if not str(r.get("announcement_date_beijing","")) < PIT: continue
        by_cid.setdefault(cid,[]).append({
          "document_type":"ANNUAL_REPORT" if r["kind"]=="ANNUAL" else "SEMIANNUAL_REPORT",
          "title":r["announcement_title"],"disclosure_date":r["announcement_date_beijing"],
          "period_end":r["report_period_end"],"revision":r["is_revised_or_corrected"]=="true",
          "announcement_id":r["announcement_id"],"adjunct_url":r["adjunct_url"],
          "org_id":r["org_id"],"source":"V2.7.28_CNINFO_PERIODIC_CATALOG"
        })

    records=[]; unresolved=[]
    # Resolve the already-covered 5207 from frozen catalog, offline.
    for cid in sorted(set(map_by)-gap_ids):
        cands=by_cid.get(cid,[])
        resolution_source="STANDARD_SELECTOR"
        if cid in amb:
            selected_id=str(amb[cid].get("selected_announcement_id") or "")
            hits=[x for x in cands if x.get("announcement_id")==selected_id]
            if len(hits)!=1:
                unresolved.append({"canonical_security_id":cid,"error":f"TARGETED_LEDGER_SELECTED_ID_NOT_UNIQUE:{selected_id}:{len(hits)}"})
                continue
            selected,err=hits[0],None
            resolution_source="TARGETED_AMBIGUITY_LEDGER"
        else:
            selected,err=select_periodic(cands)
        if err or not selected:
            unresolved.append({"canonical_security_id":cid,"error":err or "NO_PRIMARY_IN_FROZEN_CATALOG"})
            continue
        m=map_by[cid]
        records.append({"canonical_security_id":cid,"exchange":m["exchange"],"security_code":m["security_code"],
          "issuer_legal_name":m["issuer_legal_name"],"resolution":"PERIODIC","taxonomy_code":"",
          "resolution_source":resolution_source,**selected})

    if unresolved:
        raise RuntimeError(f"unexpected non-gap unresolved count={len(unresolved)} sample={unresolved[:10]}")

    # Only the 14 explicit gaps require online targeted discovery.
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True)
        ctx=browser.new_context(
          user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/153 Safari/537.36",
          locale="zh-CN")
        page_obj=ctx.new_page()
        page_obj.goto("https://www.cninfo.com.cn/",wait_until="domcontentloaded",timeout=90000)
        page_obj.wait_for_timeout(1500)

        stocks={}
        for ex,path in (("SSE","/new/data/sse_stock.json"),("SZSE","/new/data/szse_stock.json")):
            q=page_obj.evaluate("""async (path)=>{const r=await fetch(path);return {status:r.status,text:await r.text()}}""",path)
            if q["status"]!=200: raise RuntimeError(f"{ex} stock dictionary HTTP {q['status']}")
            b=q["text"].encode("utf-8"); (RAW/f"{ex}_stock.json").write_bytes(b)
            obj=json.loads(q["text"])
            for x in obj.get("stockList") or []:
                code=str(x.get("code") or "").strip(); org=str(x.get("orgId") or "").strip()
                if code and org: stocks[(ex,code)]=org

        for g in sorted(gaps,key=lambda x:x["canonical_security_id"]):
            cid=g["canonical_security_id"]; ex=g["exchange"]; code=g["security_code"]; m=map_by[cid]
            org=stocks.get((ex,code))
            if not org: raise RuntimeError(f"{cid}: CNInfo orgId unresolved")
            column="sse" if ex=="SSE" else "szse"; plate="sh" if ex=="SSE" else "sz"
            periodic=[]
            for kind,catcode in CATS.items():
                base={"column":column,"tabName":"fulltext","plate":plate,"stock":f"{code},{org}",
                      "searchkey":"","secid":"","category":catcode,"trade":"","seDate":f"2020-01-01~{CUTOFF}",
                      "sortName":"","sortType":"","isHLtitle":"true"}
                rows,_=complete_query(page_obj,base,RAW/cid.replace(":","_")/kind)
                for a in rows:
                    d=ann_date(a.get("announcementTime")); title=clean_title(a.get("announcementTitle"))
                    y,pe=period_from_title(title,kind)
                    if d and d<PIT and pe and is_full_periodic(title):
                        periodic.append({"document_type":"ANNUAL_REPORT" if kind=="ANNUAL" else "SEMIANNUAL_REPORT",
                          "title":title,"disclosure_date":d,"period_end":pe,"revision":is_revision(title),
                          "announcement_id":str(a.get("announcementId") or ""),"adjunct_url":str(a.get("adjunctUrl") or ""),
                          "org_id":org,"source":"V2.7.29_CNINFO_TARGETED_HISTORY"})
            selected,err=select_periodic(periodic)
            resolution="HISTORICAL_PERIODIC"
            taxonomy=""
            if err: raise RuntimeError(f"{cid}: {err}")
            if not selected:
                base={"column":column,"tabName":"fulltext","plate":plate,"stock":f"{code},{org}",
                      "searchkey":"招股说明书","secid":"","category":"","trade":"","seDate":f"2024-01-01~{CUTOFF}",
                      "sortName":"","sortType":"","isHLtitle":"true"}
                rows,_=complete_query(page_obj,base,RAW/cid.replace(":","_")/"IPO")
                ipo=[]
                for a in rows:
                    d=ann_date(a.get("announcementTime")); title=clean_title(a.get("announcementTitle"))
                    if d and d<PIT and is_ipo_prospectus(title):
                        ipo.append({"document_type":"IPO_PROSPECTUS","title":title,"disclosure_date":d,"period_end":"",
                          "revision":is_revision(title),"announcement_id":str(a.get("announcementId") or ""),
                          "adjunct_url":str(a.get("adjunctUrl") or ""),"org_id":org,
                          "source":"V2.7.29_CNINFO_TARGETED_IPO"})
                selected,err=select_ipo(ipo)
                if err: raise RuntimeError(f"{cid}: {err}")
                resolution="IPO_FALLBACK" if selected else "NONE"
                taxonomy="" if selected else "NA"
            base_rec={"canonical_security_id":cid,"exchange":ex,"security_code":code,
                      "issuer_legal_name":m["issuer_legal_name"],"resolution":resolution,"taxonomy_code":taxonomy,
                      "resolution_source":"TARGETED_GAP_QUERY"}
            if selected: base_rec.update(selected)
            else: base_rec.update({"document_type":"","title":"","disclosure_date":"","period_end":"",
                                   "revision":False,"announcement_id":"","adjunct_url":"","org_id":org,
                                   "source":"V2.7.29_EXHAUSTIVE_QUERY_NONE"})
            records.append(base_rec)
            print(f"LOCATOR {cid} -> {resolution}",flush=True)
        browser.close()

    records.sort(key=lambda r:r["canonical_security_id"])
    ids=[r["canonical_security_id"] for r in records]
    if len(records)!=5221 or len(set(ids))!=5221:
        raise RuntimeError(f"terminal inventory identity failure rows={len(records)} unique={len(set(ids))}")
    if set(ids)!=set(map_by):
        raise RuntimeError("terminal inventory set != official mother pool")

    locator_count=sum(1 for r in records if r["resolution"]!="NONE")
    none_count=sum(1 for r in records if r["resolution"]=="NONE")
    for r in records:
        if r["resolution"]!="NONE":
            if not r["announcement_id"] or not r["adjunct_url"] or not r["disclosure_date"]:
                raise RuntimeError(f"incomplete locator {r['canonical_security_id']}")
            if not r["disclosure_date"] < PIT:
                raise RuntimeError(f"future locator {r['canonical_security_id']}")
        else:
            if r["taxonomy_code"]!="NA":
                raise RuntimeError(f"NONE without NA {r['canonical_security_id']}")

    fields=["canonical_security_id","exchange","security_code","issuer_legal_name","resolution","taxonomy_code","resolution_source",
            "document_type","title","disclosure_date","period_end","revision","announcement_id","adjunct_url","org_id","source"]
    inv=OUT/"V2.7.29_PRIMARY_LOCATOR_INVENTORY.csv"
    with inv.open("w",encoding="utf-8",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,lineterminator="\n"); w.writeheader()
        for r in records: w.writerow({k:r.get(k,"") for k in fields})

    receipt={
      "schema":"AI_CORE_EVID_V2_7_29_PRIMARY_LOCATOR_INVENTORY_V1",
      "pit_date":PIT,
      "capture_role":"SHADOW_DIAGNOSTIC_RECONSTRUCTION_ONLY",
      "first_system_observed_at_utc":started.isoformat(),
      "prospective_backfill_allowed":False,
      "official_mother_pool_count":5221,
      "terminal_record_count":len(records),
      "unique_security_count":len(set(ids)),
      "primary_locator_count":locator_count,
      "none_na_count":none_count,
      "inventory_sha256":sha(inv.read_bytes()),
      "targeted_ambiguity_resolution_count":len(amb),
      "targeted_ambiguity_ledger_sha256":sha(AMB.read_bytes()),
      "pdf_bytes_downloaded":0,
      "pdf_materialization_gate":"SEPARATE_ON_DEMAND",
      "gate":{
        "status":"PRIMARY_LOCATOR_INVENTORY_EXACT_PASS",
        "mother_pool_exact_coverage":True,
        "selector_ambiguity_count":0,
        "pdf_required_for_this_gate":False
      },
      "downstream":{
        "historical_2026_09_17_prospective_certification":"BLOCKED_FIRST_OBSERVED_AFTER_PIT",
        "future_evidence_materialization":"READY_ON_DEMAND"
      }
    }
    canon=json.dumps(receipt,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()
    receipt["receipt_sha256"]=sha(canon)
    (OUT/"V2.7.29_PRIMARY_LOCATOR_INVENTORY_RECEIPT.json").write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(receipt,ensure_ascii=False,indent=2))

if __name__=="__main__": main()
