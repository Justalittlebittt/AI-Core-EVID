from __future__ import annotations

import csv
import hashlib
import html
import json
import math
import re
import sys
import tarfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs
from zoneinfo import ZoneInfo

import pandas as pd
from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_real_mother_pool_v2724 as v24

EPOCH_ID="AI_CORE_EVID_FORWARD_EPOCH_001"
T0_UTC="2026-09-20T07:17:16Z"
T0_DT=datetime.fromisoformat(T0_UTC.replace("Z","+00:00"))
BEIJING=ZoneInfo("Asia/Shanghai")

BASELINE_ISSUER=Path("evidence/V2.7.27_SECURITY_ISSUER_PIT_MAP.csv")
BASELINE_ISSUER_SHA="769960860eaeb97f34780eca3b8cdb2618a4e3afd580e97f59fe6435da8b25a8"
BASELINE_LOCATOR=Path("evidence/V2.7.29_PRIMARY_LOCATOR_INVENTORY.csv")
BASELINE_LOCATOR_SHA="6f497c81f99344596ba19e7ef62c54a23d373c07f80877d79af6f70f19f4a4f4"
BASELINE_LOCATOR_ORIGINAL_OBSERVED="2026-09-20T06:36:51.251465+00:00"

OUT=Path("v2731_forward_bootstrap")
OFFICIAL=OUT/"official_capture"
RAW=OUT/"raw"
CNINFO_RAW=RAW/"cninfo_delta"
OUT.mkdir(exist_ok=True)
RAW.mkdir(exist_ok=True)
CNINFO_RAW.mkdir(parents=True,exist_ok=True)

CODE_RE=re.compile(r"^\d{6}$")
CATS={"ANNUAL":"category_ndbg_szsh","HALF_YEAR":"category_bndbg_szsh"}

def sha(b:bytes)->str:
    return hashlib.sha256(b).hexdigest()

def ensure_after_t0(ts:datetime,label:str):
    if ts <= T0_DT:
        raise RuntimeError(f"{label}={ts.isoformat()} is not after epoch T0={T0_UTC}")

def clean_title(s:str)->str:
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
    if not y:
        return None,""
    return y, f"{y}-12-31" if kind=="ANNUAL" else f"{y}-06-30"

def is_full_periodic(title):
    t=clean_title(title)
    return bool(t) and not any(x in t for x in ("摘要","英文版","英文版本","审计报告","财务报告","审阅报告"))

def is_revision(title):
    t=clean_title(title)
    return any(x in t for x in ("修订","更正","修正","更新","补充"))

def is_ipo_prospectus(title):
    t=clean_title(title)
    if "招股说明书" not in t:
        return False
    return not any(x in t for x in ("提示性公告","摘要","声明","问询回复","审核问询","上市公告书"))

def select_periodic(cands):
    if not cands:
        return None,None
    latest=max(x["period_end"] for x in cands)
    same=[x for x in cands if x["period_end"]==latest]
    revised=[x for x in same if x["revision"]]
    pool=revised or same
    maxdate=max(x["disclosure_date"] for x in pool)
    top={x["announcement_id"]:x for x in pool if x["disclosure_date"]==maxdate}
    if len(top)!=1:
        return None,f"AMBIGUOUS_PERIODIC_{latest}_{maxdate}_{len(top)}"
    return next(iter(top.values())),None

def select_ipo(cands):
    if not cands:
        return None,None
    final=[x for x in cands if "注册稿" not in x["title"]]
    pool=final or cands
    maxdate=max(x["disclosure_date"] for x in pool)
    top={x["announcement_id"]:x for x in pool if x["disclosure_date"]==maxdate}
    if len(top)!=1:
        return None,f"AMBIGUOUS_IPO_{maxdate}_{len(top)}"
    return next(iter(top.values())),None

def post_query(page,payload):
    q=page.evaluate("""async (payload) => {
      const body=new URLSearchParams(payload).toString();
      const r=await fetch('/new/hisAnnouncement/query',{
        method:'POST',
        headers:{
          'Content-Type':'application/x-www-form-urlencoded; charset=UTF-8',
          'X-Requested-With':'XMLHttpRequest'
        },
        body
      });
      return {status:r.status,text:await r.text()};
    }""",payload)
    if q["status"]!=200:
        raise RuntimeError(f"CNInfo HTTP {q['status']}")
    return q["text"]

def complete_query(page,base,outdir):
    outdir.mkdir(parents=True,exist_ok=True)
    first=post_query(page,{**base,"pageNum":"1","pageSize":"30"})
    first_obj=json.loads(first)
    total=int(first_obj.get("totalRecordNum") or first_obj.get("totalAnnouncement") or 0)
    rows=[]
    ids=set()
    page_no=1
    while len(rows)<total:
        text=first if page_no==1 else post_query(page,{**base,"pageNum":str(page_no),"pageSize":"30"})
        b=text.encode("utf-8")
        (outdir/f"page_{page_no:03d}.json").write_bytes(b)
        obj=json.loads(text)
        anns=obj.get("announcements") or []
        if not anns and len(rows)<total:
            raise RuntimeError(f"CNInfo pagination stopped early {len(rows)} / {total}")
        for a in anns:
            aid=str(a.get("announcementId") or "").strip()
            if aid:
                if aid in ids:
                    continue
                ids.add(aid)
            rows.append(a)
        page_no += 1
        if page_no>1000:
            raise RuntimeError("CNInfo pagination runaway")
    if len(rows)!=total:
        raise RuntimeError(f"CNInfo pagination mismatch {len(rows)} != {total}")
    return rows

def resolve_cninfo_org_id(page,code,audit_path):
    matches=[]
    def on_req(req):
        try:
            if "/new/hisAnnouncement/query" not in req.url or req.method!="POST":
                return
            q=parse_qs(req.post_data or "")
            stock=(q.get("stock") or [""])[0]
            if stock.startswith(code+","):
                org=stock.split(",",1)[1].strip()
                if org:
                    matches.append({"stock":stock,"org_id":org})
        except Exception:
            pass
    page.on("request",on_req)
    try:
        page.goto(f"https://www.cninfo.com.cn/new/fulltextSearch?keyWord={code}",
                  wait_until="domcontentloaded",timeout=60000)
        page.wait_for_timeout(1800)
        inputs=page.locator("input")
        for i in range(min(inputs.count(),12)):
            try:
                el=inputs.nth(i)
                if not el.is_visible():
                    continue
                ph=el.get_attribute("placeholder") or ""
                if any(x in ph for x in ("代码","简称","关键")):
                    el.fill(code)
                    el.press("Enter")
                    page.wait_for_timeout(2200)
                    break
            except Exception:
                pass
    finally:
        page.remove_listener("request",on_req)
    uniq=sorted({x["org_id"] for x in matches})
    audit_path.parent.mkdir(parents=True,exist_ok=True)
    audit_path.write_text(json.dumps({"code":code,"matches":matches,"unique_org_ids":uniq},
                                     ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    if len(uniq)!=1:
        raise RuntimeError(f"{code}: CNInfo orgId unresolved/ambiguous {uniq}")
    return uniq[0]

def load_csv_exact(path:Path,expected_sha:str):
    b=path.read_bytes()
    actual=sha(b)
    if actual!=expected_sha:
        raise RuntimeError(f"{path}: SHA mismatch {actual} != {expected_sha}")
    return list(csv.DictReader(b.decode("utf-8").splitlines()))

def configure_v24(asof_date:date):
    v24.PIT_DATE=pd.Timestamp(asof_date)
    v24.OUT=OFFICIAL
    v24.RAW=OFFICIAL/"raw"
    v24.NORM=OFFICIAL/"normalized"
    v24.RAW.mkdir(parents=True,exist_ok=True)
    v24.NORM.mkdir(parents=True,exist_ok=True)

def capture_current_official(asof_date:date):
    configure_v24(asof_date)
    captures=[]
    errors=[]
    for url,ex in ((v24.SSE_PAGE,"SSE"),(v24.SZSE_PAGE,"SZSE")):
        try:
            captures.extend(v24.capture_page(url,ex))
        except Exception as e:
            errors.append({"exchange":ex,"error":repr(e)})
    if errors:
        raise RuntimeError(f"official capture errors: {errors}")
    captures=v24.expand_complete_official_sources(captures)
    ids,meta=v24.normalize_official(captures)
    if meta.get("status")!="PASS":
        raise RuntimeError(f"official normalization blocked: {meta}")
    (OUT/"V2.7.31_OFFICIAL_CAPTURE_MANIFEST.json").write_text(
        json.dumps({"captures":captures,"normalization":meta},ensure_ascii=False,indent=2)+"\n",
        encoding="utf-8"
    )
    return ids,captures,meta

def build_current_issuer_map(captures,asof_date:date):
    candidates={}
    for cap in captures:
        ex=cap.get("exchange")
        if ex=="SSE" and not cap.get("pagination_expansion"):
            continue
        if ex=="SZSE" and not cap.get("full_export"):
            continue
        if not cap.get("path"):
            continue
        for r in v24.read_candidate_rows(Path(cap["path"])):
            if ex=="SSE":
                code=str(r.get("A_STOCK_CODE") or "").strip()
                st=str(r.get("STOCK_TYPE") or "").strip()
                if not CODE_RE.fullmatch(code) or st not in {"1","8"}:
                    continue
                ld=pd.to_datetime(r.get("LIST_DATE"),errors="coerce")
                if pd.isna(ld) or pd.Timestamp(ld).date()>asof_date:
                    continue
                qkey=str(r.get("COMPANY_CODE") or "").strip()
                name=str(r.get("FULL_NAME") or "").strip()
                if not CODE_RE.fullmatch(qkey) or not name:
                    raise RuntimeError(f"SSE issuer identity missing {code}")
                rec={
                  "canonical_security_id":f"SSE:{code}",
                  "exchange":"SSE",
                  "security_code":code,
                  "official_issuer_query_key":qkey,
                  "official_issuer_query_key_type":"SSE_COMPANY_CODE",
                  "issuer_legal_name":name,
                  "security_short_name":str(r.get("COMPANY_ABBR") or "").strip(),
                  "official_list_date":pd.Timestamp(ld).date().isoformat(),
                  "official_board_code":str(r.get("LIST_BOARD") or "").strip(),
                  "source_path":str(cap["path"]),
                  "source_sha256":str(cap.get("sha256") or "")
                }
            else:
                code=str(r.get("A股代码") or "").strip()
                board=str(r.get("板块") or "").strip()
                if not CODE_RE.fullmatch(code) or board not in {"主板","创业板"}:
                    continue
                ld=pd.to_datetime(r.get("A股上市日期"),errors="coerce")
                if pd.isna(ld) or pd.Timestamp(ld).date()>asof_date:
                    continue
                name=str(r.get("公司全称") or "").strip()
                if not name:
                    raise RuntimeError(f"SZSE issuer identity missing {code}")
                rec={
                  "canonical_security_id":f"SZSE:{code}",
                  "exchange":"SZSE",
                  "security_code":code,
                  "official_issuer_query_key":code,
                  "official_issuer_query_key_type":"SZSE_A_STOCK_CODE",
                  "issuer_legal_name":name,
                  "security_short_name":str(r.get("A股简称") or "").strip(),
                  "official_list_date":pd.Timestamp(ld).date().isoformat(),
                  "official_board_code":board,
                  "source_path":str(cap["path"]),
                  "source_sha256":str(cap.get("sha256") or "")
                }
            candidates.setdefault(rec["canonical_security_id"],[]).append(rec)
    out={}
    for cid,recs in candidates.items():
        stable={(r["official_issuer_query_key"],r["issuer_legal_name"],r["official_list_date"],r["official_board_code"]) for r in recs}
        if len(stable)!=1:
            raise RuntimeError(f"issuer conflict {cid}: {stable}")
        out[cid]=sorted(recs,key=lambda r:(r["source_path"],r["source_sha256"]))[0]
    return out

def targeted_locator_for_added(added,current_issuer,cutoff_date:date):
    if not added:
        return {}
    out={}
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True)
        page=browser.new_page(
          user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/153 Safari/537.36",
          locale="zh-CN")
        page.goto("https://www.cninfo.com.cn/",wait_until="domcontentloaded",timeout=90000)
        page.wait_for_timeout(1500)
        for cid in sorted(added):
            m=current_issuer[cid]
            ex=m["exchange"]; code=m["security_code"]
            org=resolve_cninfo_org_id(page,code,CNINFO_RAW/cid.replace(":","_")/"ORG_ID.json")
            column="sse" if ex=="SSE" else "szse"
            plate="sh" if ex=="SSE" else "sz"
            cutoff=cutoff_date.isoformat()
            periodic=[]
            for kind,cat in CATS.items():
                base={
                  "column":column,"tabName":"fulltext","plate":plate,
                  "stock":f"{code},{org}","searchkey":"","secid":"","category":cat,
                  "trade":"","seDate":f"2020-01-01~{cutoff}",
                  "sortName":"","sortType":"","isHLtitle":"true"
                }
                rows=complete_query(page,base,CNINFO_RAW/cid.replace(":","_")/kind)
                for a in rows:
                    d=ann_date(a.get("announcementTime"))
                    title=clean_title(a.get("announcementTitle"))
                    _,pe=period_from_title(title,kind)
                    if d and d<=cutoff and pe and is_full_periodic(title):
                        periodic.append({
                          "document_type":"ANNUAL_REPORT" if kind=="ANNUAL" else "SEMIANNUAL_REPORT",
                          "title":title,"disclosure_date":d,"period_end":pe,
                          "revision":is_revision(title),
                          "announcement_id":str(a.get("announcementId") or ""),
                          "adjunct_url":str(a.get("adjunctUrl") or ""),
                          "org_id":org,
                          "locator_source":"V2.7.31_FORWARD_TARGETED_PERIODIC"
                        })
            selected,err=select_periodic(periodic)
            if err:
                raise RuntimeError(f"{cid}: {err}")
            resolution="FORWARD_PERIODIC"
            if not selected:
                base={
                  "column":column,"tabName":"fulltext","plate":plate,
                  "stock":f"{code},{org}","searchkey":"招股说明书","secid":"","category":"",
                  "trade":"","seDate":f"2024-01-01~{cutoff}",
                  "sortName":"","sortType":"","isHLtitle":"true"
                }
                rows=complete_query(page,base,CNINFO_RAW/cid.replace(":","_")/"IPO")
                ipo=[]
                for a in rows:
                    d=ann_date(a.get("announcementTime"))
                    title=clean_title(a.get("announcementTitle"))
                    if d and d<=cutoff and is_ipo_prospectus(title):
                        ipo.append({
                          "document_type":"IPO_PROSPECTUS","title":title,
                          "disclosure_date":d,"period_end":"","revision":is_revision(title),
                          "announcement_id":str(a.get("announcementId") or ""),
                          "adjunct_url":str(a.get("adjunctUrl") or ""),
                          "org_id":org,
                          "locator_source":"V2.7.31_FORWARD_TARGETED_IPO"
                        })
                selected,err=select_ipo(ipo)
                if err:
                    raise RuntimeError(f"{cid}: {err}")
                resolution="FORWARD_IPO_FALLBACK"
            if not selected:
                raise RuntimeError(f"{cid}: no terminal Primary Locator found after T0 bootstrap")
            selected["resolution"]=resolution
            out[cid]=selected
            print(f"ADDED_LOCATOR {cid} -> {resolution}",flush=True)
        browser.close()
    return out

def write_csv(path,rows,fields):
    with path.open("w",encoding="utf-8",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow({k:r.get(k,"") for k in fields})

def build_raw_manifest():
    rows=[]
    for p in sorted(OUT.rglob("*")):
        if not p.is_file():
            continue
        if p.name in {
          "V2.7.31_FORWARD_RAW_EVIDENCE.tar.gz",
          "V2.7.31_FORWARD_RAW_MANIFEST.csv",
          "V2.7.31_FORWARD_CERTIFIED_UNIVERSE.csv",
          "V2.7.31_FORWARD_CERTIFIED_UNIVERSE_RECEIPT.json",
          "V2.7.31_FORWARD_CURRENT_ISSUER_MAP.csv"
        }:
            continue
        b=p.read_bytes()
        rows.append({
          "path":str(p.relative_to(OUT)),
          "bytes":len(b),
          "sha256":sha(b)
        })
    manifest=OUT/"V2.7.31_FORWARD_RAW_MANIFEST.csv"
    write_csv(manifest,rows,["path","bytes","sha256"])
    bundle=OUT/"V2.7.31_FORWARD_RAW_EVIDENCE.tar.gz"
    with tarfile.open(bundle,"w:gz",compresslevel=9) as tf:
        for r in rows:
            p=OUT/r["path"]
            tf.add(p,arcname=r["path"])
    return manifest,bundle,rows

def main():
    run_started=datetime.now(timezone.utc)
    ensure_after_t0(run_started,"run_started_at_utc")
    local_now=run_started.astimezone(BEIJING)
    asof_date=local_now.date()
    # Conservative date-only causal cutoff: exclude same-calendar-day disclosures.
    locator_cutoff=asof_date-timedelta(days=1)

    baseline_issuer_rows=load_csv_exact(BASELINE_ISSUER,BASELINE_ISSUER_SHA)
    baseline_locator_rows=load_csv_exact(BASELINE_LOCATOR,BASELINE_LOCATOR_SHA)
    baseline_issuer={r["canonical_security_id"]:r for r in baseline_issuer_rows}
    baseline_locator={r["canonical_security_id"]:r for r in baseline_locator_rows}
    if set(baseline_issuer)!=set(baseline_locator):
        raise RuntimeError("baseline issuer/locator identity sets differ")

    current_ids,captures,norm_meta=capture_current_official(asof_date)
    observed_membership_at=datetime.now(timezone.utc)
    ensure_after_t0(observed_membership_at,"official_membership_observed_at_utc")

    current_issuer=build_current_issuer_map(captures,asof_date)
    if set(current_issuer)!=set(current_ids):
        missing=sorted(set(current_ids)-set(current_issuer))
        extra=sorted(set(current_issuer)-set(current_ids))
        raise RuntimeError(f"current issuer map != official membership missing={missing[:10]} extra={extra[:10]}")

    baseline_ids=set(baseline_issuer)
    added=sorted(current_ids-baseline_ids)
    removed=sorted(baseline_ids-current_ids)
    unchanged=sorted(current_ids&baseline_ids)

    print(f"CURRENT count={len(current_ids)} unchanged={len(unchanged)} added={len(added)} removed={len(removed)}",flush=True)
    if added:
        print(f"ADDED {added}",flush=True)
    if removed:
        print(f"REMOVED {removed}",flush=True)

    added_locators=targeted_locator_for_added(added,current_issuer,locator_cutoff)
    if set(added_locators)!=set(added):
        raise RuntimeError("added locator resolution incomplete")

    certified_at=datetime.now(timezone.utc)
    ensure_after_t0(certified_at,"certified_at_utc")

    universe=[]
    for cid in sorted(current_ids):
        issuer=current_issuer[cid]
        if cid in baseline_locator:
            loc=baseline_locator[cid]
            locator_provenance="BASELINE_ADOPTED_AT_T0"
            locator_original_observed=BASELINE_LOCATOR_ORIGINAL_OBSERVED
            resolution=loc.get("resolution","")
            doc_type=loc.get("document_type","")
            title=loc.get("title","")
            disclosure=loc.get("disclosure_date","")
            period_end=loc.get("period_end","")
            revision=loc.get("revision","")
            ann_id=loc.get("announcement_id","")
            adjunct=loc.get("adjunct_url","")
            org_id=loc.get("org_id","")
            locator_source=loc.get("source","")
        else:
            loc=added_locators[cid]
            locator_provenance="FORWARD_OBSERVED_AFTER_T0"
            locator_original_observed=certified_at.isoformat()
            resolution=loc["resolution"]
            doc_type=loc["document_type"]
            title=loc["title"]
            disclosure=loc["disclosure_date"]
            period_end=loc["period_end"]
            revision=loc["revision"]
            ann_id=loc["announcement_id"]
            adjunct=loc["adjunct_url"]
            org_id=loc["org_id"]
            locator_source=loc["locator_source"]
        if not ann_id or not adjunct:
            raise RuntimeError(f"{cid}: terminal locator incomplete")
        universe.append({
          "epoch_id":EPOCH_ID,
          "epoch_t0_utc":T0_UTC,
          "certified_at_utc":certified_at.isoformat(),
          "canonical_security_id":cid,
          "exchange":issuer["exchange"],
          "security_code":issuer["security_code"],
          "official_issuer_query_key":issuer["official_issuer_query_key"],
          "official_issuer_query_key_type":issuer["official_issuer_query_key_type"],
          "issuer_legal_name":issuer["issuer_legal_name"],
          "security_short_name":issuer["security_short_name"],
          "official_list_date":issuer["official_list_date"],
          "official_board_code":issuer["official_board_code"],
          "membership_provenance":"FORWARD_OBSERVED_AFTER_T0",
          "membership_observed_at_utc":observed_membership_at.isoformat(),
          "locator_provenance":locator_provenance,
          "locator_original_first_observed_at_utc":locator_original_observed,
          "resolution":resolution,
          "document_type":doc_type,
          "title":title,
          "disclosure_date":disclosure,
          "period_end":period_end,
          "revision":revision,
          "announcement_id":ann_id,
          "adjunct_url":adjunct,
          "org_id":org_id,
          "locator_source":locator_source,
          "pdf_materialization_status":"ON_DEMAND_NOT_REQUIRED_FOR_UNIVERSE_ENTRY",
          "universe_entry_status":"CERTIFIED"
        })

    universe_fields=list(universe[0].keys()) if universe else []
    universe_path=OUT/"V2.7.31_FORWARD_CERTIFIED_UNIVERSE.csv"
    write_csv(universe_path,universe,universe_fields)

    issuer_rows=[current_issuer[cid] for cid in sorted(current_issuer)]
    issuer_path=OUT/"V2.7.31_FORWARD_CURRENT_ISSUER_MAP.csv"
    issuer_fields=[
      "canonical_security_id","exchange","security_code","official_issuer_query_key",
      "official_issuer_query_key_type","issuer_legal_name","security_short_name",
      "official_list_date","official_board_code","source_path","source_sha256"
    ]
    write_csv(issuer_path,issuer_rows,issuer_fields)

    set_hash=sha(("\n".join(sorted(current_ids))+"\n").encode())
    sse_count=sum(1 for x in current_ids if x.startswith("SSE:"))
    szse_count=sum(1 for x in current_ids if x.startswith("SZSE:"))

    manifest,bundle,raw_rows=build_raw_manifest()

    receipt={
      "schema":"AI_CORE_EVID_V2_7_31_FORWARD_CERTIFIED_UNIVERSE_RECEIPT_V1",
      "epoch_id":EPOCH_ID,
      "epoch_t0_utc":T0_UTC,
      "run_started_at_utc":run_started.isoformat(),
      "official_membership_observed_at_utc":observed_membership_at.isoformat(),
      "certified_at_utc":certified_at.isoformat(),
      "asof_date_asia_shanghai":asof_date.isoformat(),
      "same_day_filing_disclosures_excluded":True,
      "targeted_locator_cutoff_date":locator_cutoff.isoformat(),
      "baseline":{
        "issuer_map_sha256":BASELINE_ISSUER_SHA,
        "primary_locator_inventory_sha256":BASELINE_LOCATOR_SHA,
        "baseline_count":len(baseline_ids),
        "adoption_semantics":"BASELINE_ADOPTED_AT_T0_FOR_POST_T0_DECISIONS_ONLY"
      },
      "current_official_membership":{
        "count":len(current_ids),
        "sse_count":sse_count,
        "szse_count":szse_count,
        "canonical_sorted_newline_sha256":set_hash,
        "normalization_status":norm_meta.get("status")
      },
      "delta":{
        "unchanged_count":len(unchanged),
        "added_count":len(added),
        "removed_count":len(removed),
        "added_ids":added,
        "removed_ids":removed
      },
      "issuer_identity":{
        "row_count":len(current_issuer),
        "exact_current_membership_coverage":set(current_issuer)==set(current_ids),
        "provenance":"FORWARD_OBSERVED_AFTER_T0"
      },
      "primary_locator":{
        "terminal_locator_count":len(universe),
        "baseline_adopted_count":len(unchanged),
        "forward_targeted_resolution_count":len(added),
        "missing_count":0
      },
      "outputs":{
        "certified_universe_sha256":sha(universe_path.read_bytes()),
        "current_issuer_map_sha256":sha(issuer_path.read_bytes()),
        "raw_manifest_sha256":sha(manifest.read_bytes()),
        "raw_bundle_sha256":sha(bundle.read_bytes()),
        "raw_bundle_bytes":bundle.stat().st_size,
        "raw_file_count":len(raw_rows)
      },
      "temporal_governance":{
        "pre_t0_decisions_authorized":False,
        "post_certified_at_decisions_may_use_universe":True,
        "historical_2026_09_17_prospective_relabeling":"FORBIDDEN"
      },
      "downstream":{
        "certified_v2_universe":"PASS",
        "first60":"READY_FOR_DETERMINISTIC_EPISODE_START_NOT_STARTED",
        "filing_content_materialization":"ON_DEMAND_V2.7.30",
        "vendor_price_coverage":"SEPARATE_PER_SECURITY_EXECUTION_GATE",
        "s4_s5_s6":"BLOCKED_PENDING_FIRST60_AND_LATER_GATES",
        "live":"BLOCKED"
      },
      "gate":{
        "status":"FORWARD_CERTIFIED_UNIVERSE_BOOTSTRAP_PASS",
        "current_membership_exact":True,
        "issuer_identity_exact":True,
        "terminal_locator_exact":True,
        "all_forward_timestamps_after_t0":True
      }
    }
    canon=json.dumps(receipt,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()
    receipt["receipt_sha256"]=sha(canon)
    receipt_path=OUT/"V2.7.31_FORWARD_CERTIFIED_UNIVERSE_RECEIPT.json"
    receipt_path.write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(receipt,ensure_ascii=False,indent=2))

if __name__=="__main__":
    main()
