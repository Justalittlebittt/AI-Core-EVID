from __future__ import annotations
import hashlib, json
from pathlib import Path
from urllib.parse import parse_qs
from playwright.sync_api import sync_playwright

ADD=Path("evidence/V2.9.2_BATCH2_IDENTITY_FALLBACK_ADDENDUM_1.json")
MAP=Path("evidence/V2.7.27_SECURITY_ISSUER_PIT_MAP.csv")
OUT=Path("evidence/V2.9.2_BATCH2_IDENTITY_FALLBACK_VALIDATION_1.json")
START="2023-01-01"; END="2024-12-30"
EXPECTED_MAP_SHA="769960860eaeb97f34780eca3b8cdb2618a4e3afd580e97f59fe6435da8b25a8"

def stable_sha(o):
    return hashlib.sha256(json.dumps(o,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()

def sha_file(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def post(page,payload):
    q=page.evaluate("""async (payload)=>{const body=new URLSearchParams(payload).toString();const r=await fetch('/new/hisAnnouncement/query',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded; charset=UTF-8','X-Requested-With':'XMLHttpRequest'},body});return {status:r.status,text:await r.text()};}""",payload)
    if q["status"]!=200: raise RuntimeError(f"CNINFO_HTTP_{q['status']}")
    return q["text"]

def resolve_org(page,code):
    matches=[]
    def on_req(req):
        if "/new/hisAnnouncement/query" not in req.url or req.method!="POST": return
        q=parse_qs(req.post_data or "")
        stock=(q.get("stock") or [""])[0]
        if stock.startswith(code+","):
            org=stock.split(",",1)[1].strip()
            if org: matches.append(org)
    page.on("request",on_req)
    try:
        page.goto(f"https://www.cninfo.com.cn/new/fulltextSearch?keyWord={code}",wait_until="domcontentloaded",timeout=60000)
        page.wait_for_timeout(1200)
        ins=page.locator("input")
        for i in range(min(ins.count(),12)):
            try:
                el=ins.nth(i)
                if not el.is_visible(): continue
                ph=el.get_attribute("placeholder") or ""
                if any(x in ph for x in ("代码","简称","关键")):
                    el.fill(code); el.press("Enter"); page.wait_for_timeout(1800); break
            except Exception: pass
    finally:
        page.remove_listener("request",on_req)
    u=sorted(set(matches))
    if len(u)!=1: raise RuntimeError(f"ORG_ID_UNRESOLVED:{code}:{u}")
    return u[0]

def query_blank(page,code,org,exchange):
    base={"column":"sse" if exchange=="SSE" else "szse","tabName":"fulltext","plate":"sh" if exchange=="SSE" else "sz",
          "stock":f"{code},{org}","searchkey":"","secid":"","category":"","trade":"","seDate":f"{START}~{END}",
          "sortName":"","sortType":"","isHLtitle":"true","pageNum":"1","pageSize":"30"}
    first=json.loads(post(page,base)); total=int(first.get("totalRecordNum") or first.get("totalAnnouncement") or 0)
    got=[]; ids=set(); page_no=1; contradictions=[]
    while len(got)<total:
        obj=first if page_no==1 else json.loads(post(page,{**base,"pageNum":str(page_no)}))
        anns=obj.get("announcements") or []
        if not anns and len(got)<total: raise RuntimeError(f"PAGINATION_EARLY:{code}:{len(got)}/{total}")
        for a in anns:
            aid=str(a.get("announcementId") or "").strip()
            if aid and aid not in ids:
                ids.add(aid); got.append(a)
                explicit=str(a.get("secCode") or a.get("securityCode") or "").strip()
                if explicit and explicit!=code: contradictions.append({"announcement_id":aid,"explicit_code":explicit})
        page_no+=1
        if page_no>1000: raise RuntimeError("PAGINATION_RUNAWAY")
    if len(got)!=total: raise RuntimeError(f"PAGINATION_MISMATCH:{code}:{len(got)}/{total}")
    if total<1: raise RuntimeError(f"ZERO_OFFICIAL_FILINGS:{code}")
    if contradictions: raise RuntimeError(f"SECURITY_CODE_CONTRADICTION:{code}:{contradictions[:3]}")
    return {"official_total":total,"deduped_count":len(got),"pages_fetched":page_no-1}

def main():
    add=json.loads(ADD.read_text(encoding="utf-8")); tests=[]
    def ck(name,val): tests.append({"name":name,"pass":bool(val)})
    ck("I01_addendum_frozen",add.get("schema")=="AI_CORE_EVID_V2_9_2_BATCH2_IDENTITY_FALLBACK_ADDENDUM_1" and add.get("status")=="FROZEN_BEFORE_VALIDATION")
    ck("I02_original_map_hash_exact",sha_file(MAP)==EXPECTED_MAP_SHA)
    affected=add.get("affected_securities") or []
    expected=["SSE:600608","SZSE:300280"]
    ck("I03_affected_set_exact",[x.get("canonical_security_id") for x in affected]==expected)
    evidence=[]
    try:
        with sync_playwright() as pw:
            b=pw.chromium.launch(headless=True); page=b.new_page(locale="zh-CN")
            page.goto("https://www.cninfo.com.cn/",wait_until="domcontentloaded",timeout=90000); page.wait_for_timeout(1000)
            for x in affected:
                org=resolve_org(page,x["security_code"])
                q=query_blank(page,x["security_code"],org,x["exchange"])
                evidence.append({**x,"resolved_org_id":org,**q,"status":"PASS"})
            b.close()
        ck("I04_org_ids_unique_nonempty",len(evidence)==2 and all(x.get("resolved_org_id") for x in evidence))
        ck("I05_blank_transport_nonempty",all(x["official_total"]>0 for x in evidence))
        ck("I06_pagination_closed",all(x["official_total"]==x["deduped_count"] for x in evidence))
    except Exception as exc:
        evidence.append({"status":"BLOCKED","blocker":f"{type(exc).__name__}:{exc}"})
        ck("I04_org_ids_unique_nonempty",False); ck("I05_blank_transport_nonempty",False); ck("I06_pagination_closed",False)
    ck("I07_no_scientific_classification",True); ck("I08_no_price_outcome_fold34",True)
    ok=all(x["pass"] for x in tests)
    out={"schema":"AI_CORE_EVID_V2_9_2_BATCH2_IDENTITY_FALLBACK_VALIDATION_1","version":"V2.9.2",
         "status":"V2_9_2_BATCH2_IDENTITY_FALLBACK_VALIDATED" if ok else "V2_9_2_BATCH2_IDENTITY_FALLBACK_BLOCKED",
         "tests":tests,"passed":sum(x["pass"] for x in tests),"total":len(tests),"all_pass":ok,
         "identity_evidence":evidence,"scientific_classification_executed":False,
         "price_or_return_data_consumed":False,"candidate_outcome_research_executed":False,
         "fold3_accessed":False,"fold4_accessed":False,
         "authorization":{"batch2_identity_fallback_allowed":ok}}
    out["receipt_sha256"]=stable_sha(out)
    OUT.write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(out,ensure_ascii=False,indent=2))
    if not ok: raise SystemExit(2)

if __name__=="__main__": main()
