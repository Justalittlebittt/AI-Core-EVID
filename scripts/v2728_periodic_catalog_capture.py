from __future__ import annotations
import csv, gzip, hashlib, html, io, json, re, tarfile, time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from playwright.sync_api import sync_playwright

MAP=Path("evidence/V2.7.27_SECURITY_ISSUER_PIT_MAP.csv")
OUT=Path("v2728_catalog_capture")
RAW=OUT/"raw"
OUT.mkdir(exist_ok=True); RAW.mkdir(exist_ok=True)
START_DATE="2026-01-01"
CUTOFF_DATE="2026-09-16"
PIT_DATE="2026-09-17"
EXPECTED_MOTHER_COUNT=5221
BEIJING=ZoneInfo("Asia/Shanghai")
CATS={"ANNUAL":"category_ndbg_szsh","HALF_YEAR":"category_bndbg_szsh"}

def sha(b:bytes)->str: return hashlib.sha256(b).hexdigest()

def clean_title(s:str)->str:
    s=html.unescape(re.sub(r"<[^>]+>","",str(s or "")))
    return re.sub(r"\s+","",s)

def ann_date(ms):
    try:
        return datetime.fromtimestamp(int(ms)/1000,tz=timezone.utc).astimezone(BEIJING).date().isoformat()
    except Exception:
        return ""

def classify_title(title:str,kind:str):
    t=clean_title(title)
    years=re.findall(r"(20\d{2})年",t)
    year=int(years[0]) if years else None
    summary=("摘要" in t)
    revised=any(x in t for x in ("修订","更正","修正","更新","补充"))
    english=any(x in t for x in ("英文版","英文版本","English"))
    if year:
        period_end=f"{year}-12-31" if kind=="ANNUAL" else f"{year}-06-30"
    else:
        period_end=""
    return t,year,period_end,summary,revised,english

def post_page(page,payload):
    q=page.evaluate("""async (payload) => {
      const body=new URLSearchParams(payload).toString();
      const r=await fetch('/new/hisAnnouncement/query',{
        method:'POST',
        headers:{'Content-Type':'application/x-www-form-urlencoded; charset=UTF-8','X-Requested-With':'XMLHttpRequest'},
        body
      });
      return {status:r.status,text:await r.text()};
    }""",payload)
    if q["status"]!=200:
        raise RuntimeError(f"CNInfo HTTP {q['status']}")
    return q["text"]

def main():
    run_started=datetime.now(timezone.utc)
    map_rows=list(csv.DictReader(MAP.open(encoding="utf-8")))
    if len(map_rows)!=EXPECTED_MOTHER_COUNT:
        raise RuntimeError(f"V2.7.27 map row count {len(map_rows)} != {EXPECTED_MOTHER_COUNT}")
    by_ex_code={(r["exchange"],r["security_code"]):r for r in map_rows}
    if len(by_ex_code)!=EXPECTED_MOTHER_COUNT: raise RuntimeError("duplicate map identities")

    manifest=[]
    catalog=[]
    stream_stats=[]
    unmapped=[]
    seen_ann_ids=set()

    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True)
        page=browser.new_page(
          user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/153 Safari/537.36",
          locale="zh-CN")
        page.goto("https://www.cninfo.com.cn/",wait_until="domcontentloaded",timeout=90000)
        page.wait_for_timeout(2500)

        for exchange,column,plate in [("SSE","sse","sh"),("SZSE","szse","sz")]:
          for kind,category in CATS.items():
            stream_dir=RAW/exchange/kind
            stream_dir.mkdir(parents=True,exist_ok=True)
            def payload(n):
                return {
                  "pageNum":str(n),"pageSize":"30","column":column,"tabName":"fulltext",
                  "plate":plate,"stock":"","searchkey":"","secid":"","category":category,
                  "trade":"","seDate":f"{START_DATE}~{CUTOFF_DATE}",
                  "sortName":"","sortType":"","isHLtitle":"true"
                }

            first_text=post_page(page,payload(1))
            obj=json.loads(first_text)
            totalpages=int(obj.get("totalpages") or 0)
            totalrecords=int(obj.get("totalRecordNum") or obj.get("totalAnnouncement") or 0)
            if totalpages<=0: raise RuntimeError(f"{exchange}/{kind}: invalid totalpages={totalpages}")

            fetched_rows=0
            mapped_rows=0
            page_failures=[]
            for n in range(1,totalpages+1):
                text=first_text if n==1 else None
                if text is None:
                    last=None
                    for attempt in range(1,4):
                        try:
                            text=post_page(page,payload(n)); break
                        except Exception as e:
                            last=e
                            page.wait_for_timeout(350*attempt)
                    if text is None:
                        page_failures.append({"page":n,"error":repr(last)})
                        break
                b=text.encode("utf-8")
                p=stream_dir/f"page_{n:04d}.json"
                p.write_bytes(b)
                ph=sha(b)
                o=json.loads(text)
                anns=o.get("announcements") or []
                fetched_rows += len(anns)
                manifest.append({
                  "exchange":exchange,"kind":kind,"page":n,"path":str(p),
                  "sha256":ph,"bytes":len(b),"rows":len(anns),
                  "reported_totalpages":o.get("totalpages"),"reported_totalRecordNum":o.get("totalRecordNum")
                })
                for a in anns:
                    code=str(a.get("secCode") or "").strip()
                    cid=(exchange,code)
                    m=by_ex_code.get(cid)
                    if not m:
                        unmapped.append({
                          "exchange_stream":exchange,"kind":kind,"secCode":code,
                          "secName":a.get("secName"),"announcementId":a.get("announcementId"),
                          "announcementTitle":clean_title(a.get("announcementTitle"))
                        })
                        continue
                    d=ann_date(a.get("announcementTime"))
                    if not d or d>CUTOFF_DATE:
                        continue
                    title,year,period_end,is_summary,is_revised,is_english=classify_title(a.get("announcementTitle"),kind)
                    ann_id=str(a.get("announcementId") or "").strip()
                    unique=(exchange,ann_id)
                    # Same announcement can only belong to one stream/kind; duplicates are retained only once.
                    if ann_id and unique in seen_ann_ids:
                        continue
                    if ann_id: seen_ann_ids.add(unique)
                    mapped_rows += 1
                    catalog.append({
                      "pit_date":PIT_DATE,
                      "catalog_start_date":START_DATE,
                      "catalog_cutoff_date":CUTOFF_DATE,
                      "first_system_observed_at_utc":run_started.isoformat(),
                      "prospective_eligible_for_pit":"false",
                      "canonical_security_id":m["canonical_security_id"],
                      "exchange":exchange,
                      "security_code":code,
                      "issuer_legal_name":m["issuer_legal_name"],
                      "kind":kind,
                      "category":category,
                      "report_year":year if year is not None else "",
                      "report_period_end":period_end,
                      "announcement_id":ann_id,
                      "announcement_title":title,
                      "announcement_date_beijing":d,
                      "org_id":str(a.get("orgId") or ""),
                      "adjunct_url":str(a.get("adjunctUrl") or ""),
                      "adjunct_type":str(a.get("adjunctType") or ""),
                      "announcement_type":str(a.get("announcementType") or ""),
                      "page_column":str(a.get("pageColumn") or ""),
                      "is_summary":"true" if is_summary else "false",
                      "is_revised_or_corrected":"true" if is_revised else "false",
                      "is_english":"true" if is_english else "false",
                      "source_stream":f"{exchange}/{kind}",
                    })
                if n%50==0:
                    print(f"PROGRESS {exchange}/{kind} {n}/{totalpages}",flush=True)
            if page_failures:
                raise RuntimeError(f"{exchange}/{kind} page capture failed: {page_failures}")
            # The server may include rows outside current Mother Pool, but page completeness must match server total.
            if fetched_rows != totalrecords:
                raise RuntimeError(f"{exchange}/{kind}: fetched_rows {fetched_rows} != server total {totalrecords}")
            stream_stats.append({
              "exchange":exchange,"kind":kind,"totalpages":totalpages,
              "server_total_records":totalrecords,"fetched_rows":fetched_rows,
              "mapped_mother_pool_rows":mapped_rows
            })
        browser.close()

    # Write raw manifest.
    man_path=OUT/"V2.7.28_RAW_QUERY_MANIFEST.csv"
    mf=["exchange","kind","page","path","sha256","bytes","rows","reported_totalpages","reported_totalRecordNum"]
    with man_path.open("w",encoding="utf-8",newline="") as f:
        w=csv.DictWriter(f,fieldnames=mf,lineterminator="\n");w.writeheader();w.writerows(manifest)

    # Stable catalog ordering.
    catalog.sort(key=lambda r:(r["canonical_security_id"],r["report_period_end"],r["announcement_date_beijing"],r["announcement_id"],r["kind"]))
    cat_path=OUT/"V2.7.28_PERIODIC_CATALOG.csv"
    fields=list(catalog[0].keys()) if catalog else []
    with cat_path.open("w",encoding="utf-8",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,lineterminator="\n");w.writeheader();w.writerows(catalog)

    # Coverage: only non-summary, non-English, parseable period docs count as full periodic primary candidates.
    full_by_cid={}
    summary_only=set()
    for r in catalog:
        cid=r["canonical_security_id"]
        if r["is_summary"]=="true": summary_only.add(cid); continue
        if r["is_english"]=="true" or not r["report_period_end"]: continue
        full_by_cid.setdefault(cid,[]).append(r)
    all_ids={r["canonical_security_id"] for r in map_rows}
    full_ids=set(full_by_cid)
    missing_ids=sorted(all_ids-full_ids)
    summary_only_ids=sorted((summary_only-full_ids)&all_ids)

    cov_path=OUT/"V2.7.28_PERIODIC_COVERAGE_GAPS.csv"
    with cov_path.open("w",encoding="utf-8",newline="") as f:
        fs=["canonical_security_id","exchange","security_code","issuer_legal_name","status"]
        w=csv.DictWriter(f,fieldnames=fs,lineterminator="\n");w.writeheader()
        for cid in missing_ids:
            m=next(x for x in map_rows if x["canonical_security_id"]==cid)
            w.writerow({
              "canonical_security_id":cid,"exchange":m["exchange"],"security_code":m["security_code"],
              "issuer_legal_name":m["issuer_legal_name"],
              "status":"SUMMARY_ONLY" if cid in summary_only_ids else "NO_FULL_PERIODIC_IN_WINDOW"
            })

    # Preserve raw query-result bytes as a compressed bundle.
    bundle=OUT/"V2.7.28_RAW_QUERY_RESPONSES.tar.gz"
    with tarfile.open(bundle,"w:gz",compresslevel=9) as tf:
        for p in sorted(RAW.rglob("*.json")):
            tf.add(p,arcname=str(p.relative_to(OUT)))

    receipt={
      "schema":"AI_CORE_EVID_V2_7_28_PERIODIC_CATALOG_CAPTURE_V1",
      "pit_date":PIT_DATE,
      "capture_role":"SHADOW_DIAGNOSTIC_RECONSTRUCTION_ONLY",
      "first_system_observed_at_utc":run_started.isoformat(),
      "prospective_backfill_allowed":False,
      "catalog_window":{"start":START_DATE,"cutoff_inclusive":CUTOFF_DATE},
      "source":"CNInfo official disclosure platform",
      "endpoint":"https://www.cninfo.com.cn/new/hisAnnouncement/query",
      "categories":CATS,
      "mother_pool_count":EXPECTED_MOTHER_COUNT,
      "stream_stats":stream_stats,
      "raw_query_pages":len(manifest),
      "raw_query_manifest_sha256":sha(man_path.read_bytes()),
      "raw_query_bundle_sha256":sha(bundle.read_bytes()),
      "raw_query_bundle_bytes":bundle.stat().st_size,
      "catalog_rows":len(catalog),
      "catalog_sha256":sha(cat_path.read_bytes()),
      "full_periodic_candidate_security_count":len(full_ids),
      "periodic_gap_security_count":len(missing_ids),
      "summary_only_security_count":len(summary_only_ids),
      "unmapped_catalog_rows":len(unmapped),
      "gate":{
        "raw_pagination_complete":True,
        "status":"PERIODIC_CATALOG_PASS" if len(missing_ids)==0 else "PERIODIC_CATALOG_PASS_WITH_EXPLICIT_GAPS",
        "next_stage":"TARGETED_PERIODIC_HISTORY_OR_IPO_FALLBACK_FOR_GAPS"
      }
    }
    canonical=json.dumps(receipt,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()
    receipt["receipt_sha256"]=sha(canonical)
    (OUT/"V2.7.28_PERIODIC_CATALOG_RECEIPT.json").write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    # Keep unmapped only as audit counts/samples, not evidence membership.
    (OUT/"V2.7.28_UNMAPPED_CATALOG_SAMPLE.json").write_text(json.dumps(unmapped[:200],ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(receipt,ensure_ascii=False,indent=2))

if __name__=="__main__": main()
