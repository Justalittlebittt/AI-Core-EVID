from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import re
import tarfile
import time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import requests

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
RAW=OUT/"raw"
SSE_RAW=RAW/"sse"
SZSE_RAW=RAW/"szse"
OUT.mkdir(exist_ok=True)
SSE_RAW.mkdir(parents=True,exist_ok=True)
SZSE_RAW.mkdir(parents=True,exist_ok=True)

SSE_ENDPOINT="https://query.sse.com.cn/sseQuery/commonQuery.do"
SSE_REFERER="https://www.sse.com.cn/assortment/stock/list/share/"
SZSE_ENDPOINT="https://www.szse.cn/api/report/ShowReport"
SZSE_REFERER="https://www.szse.cn/market/product/stock/list/index.html"
CODE_RE=re.compile(r"^\d{6}$")

def sha(b:bytes)->str:
    return hashlib.sha256(b).hexdigest()

def ensure_after_t0(ts:datetime,label:str):
    if ts <= T0_DT:
        raise RuntimeError(f"{label}={ts.isoformat()} is not after T0={T0_UTC}")

def decode_json_or_jsonp(b:bytes):
    s=b.decode("utf-8","ignore").strip()
    try:
        return json.loads(s)
    except Exception:
        m=re.match(r"^[A-Za-z_$][\w$]*\((.*)\)\s*;?\s*$",s,re.S)
        if not m:
            raise
        return json.loads(m.group(1))

def load_csv_exact(path:Path,expected_sha:str):
    b=path.read_bytes()
    actual=sha(b)
    if actual!=expected_sha:
        raise RuntimeError(f"{path}: SHA mismatch {actual} != {expected_sha}")
    return list(csv.DictReader(b.decode("utf-8").splitlines()))

def write_csv(path:Path,rows:list[dict],fields:list[str]):
    with path.open("w",encoding="utf-8",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow({k:r.get(k,"") for k in fields})

def fetch_sse(asof_date):
    sess=requests.Session()
    sess.headers.update({
      "User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/153 Safari/537.36",
      "Referer":SSE_REFERER
    })
    captures=[]
    issuer={}
    callback="jsonpCallback27310001"
    for stock_type,label in (("1","main_a"),("8","star")):
        base={
          "jsonCallBack":callback,
          "STOCK_TYPE":stock_type,
          "REG_PROVINCE":"",
          "CSRC_CODE":"",
          "STOCK_CODE":"",
          "sqlId":"COMMON_SSE_CP_GPJCTPZ_GPLB_GP_L",
          "COMPANY_STATUS":"2,4,5,7,8",
          "type":"inParams",
          "isPagination":"true",
          "pageHelp.cacheSize":"1",
          "pageHelp.pageSize":"25",
          "_":str(int(time.time()*1000))
        }
        q={**base,"pageHelp.beginPage":"1","pageHelp.pageNo":"1","pageHelp.endPage":"1"}
        r=sess.get(SSE_ENDPOINT,params=q,timeout=30)
        if r.status_code!=200:
            raise RuntimeError(f"SSE {label} first page HTTP {r.status_code}")
        first_obj=decode_json_or_jsonp(r.content)
        ph=first_obj.get("pageHelp",{}) if isinstance(first_obj,dict) else {}
        total=int(ph.get("total") or 0)
        page_size=int(ph.get("pageSize") or 25)
        if total<=0:
            raise RuntimeError(f"SSE {label} returned total={total}")
        pages=max(1,math.ceil(total/page_size))
        for n in range(1,pages+1):
            qq={**base,"pageHelp.beginPage":str(n),"pageHelp.pageNo":str(n),"pageHelp.endPage":str(n)}
            rr=r if n==1 else sess.get(SSE_ENDPOINT,params=qq,timeout=30)
            if rr.status_code!=200:
                raise RuntimeError(f"SSE {label} page {n} HTTP {rr.status_code}")
            p=SSE_RAW/f"{label}_{n:04d}.json"
            p.write_bytes(rr.content)
            captures.append({
              "exchange":"SSE","board":label,"page":n,"url":rr.url,
              "status":rr.status_code,"bytes":len(rr.content),"sha256":sha(rr.content),
              "captured_at_utc":datetime.now(timezone.utc).isoformat()
            })
            obj=decode_json_or_jsonp(rr.content)
            rows=(obj.get("result") or []) if isinstance(obj,dict) else []
            if not rows and isinstance(obj,dict):
                # Some SSE responses nest rows elsewhere; search common list values.
                for v in obj.values():
                    if isinstance(v,list) and v and isinstance(v[0],dict) and "A_STOCK_CODE" in v[0]:
                        rows=v; break
            for x in rows:
                code=str(x.get("A_STOCK_CODE") or "").strip()
                st=str(x.get("STOCK_TYPE") or "").strip()
                if not CODE_RE.fullmatch(code) or st not in {"1","8"}:
                    continue
                ld=pd.to_datetime(x.get("LIST_DATE"),errors="coerce")
                if pd.isna(ld) or pd.Timestamp(ld).date()>asof_date:
                    continue
                qkey=str(x.get("COMPANY_CODE") or "").strip()
                name=str(x.get("FULL_NAME") or "").strip()
                if not CODE_RE.fullmatch(qkey) or not name:
                    raise RuntimeError(f"SSE issuer identity missing {code}")
                rec={
                  "canonical_security_id":f"SSE:{code}",
                  "exchange":"SSE","security_code":code,
                  "official_issuer_query_key":qkey,
                  "official_issuer_query_key_type":"SSE_COMPANY_CODE",
                  "issuer_legal_name":name,
                  "security_short_name":str(x.get("COMPANY_ABBR") or "").strip(),
                  "official_list_date":pd.Timestamp(ld).date().isoformat(),
                  "official_board_code":str(x.get("LIST_BOARD") or "").strip(),
                  "source_path":str(p.relative_to(OUT)),
                  "source_sha256":sha(rr.content)
                }
                if rec["canonical_security_id"] in issuer:
                    old=issuer[rec["canonical_security_id"]]
                    stable=("official_issuer_query_key","issuer_legal_name","official_list_date","official_board_code")
                    if any(old[k]!=rec[k] for k in stable):
                        raise RuntimeError(f"SSE identity conflict {rec['canonical_security_id']}")
                else:
                    issuer[rec["canonical_security_id"]]=rec
    if len(issuer)<=1000:
        raise RuntimeError(f"SSE normalized count implausible {len(issuer)}")
    return issuer,captures

def fetch_szse(asof_date):
    r=requests.get(
      SZSE_ENDPOINT,
      params={"SHOWTYPE":"xlsx","CATALOGID":"1110","TABKEY":"tab1"},
      headers={
        "User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/153 Safari/537.36",
        "Referer":SZSE_REFERER
      },
      timeout=60)
    if r.status_code!=200:
        raise RuntimeError(f"SZSE A-share XLSX HTTP {r.status_code}")
    p=SZSE_RAW/"A_SHARE_LIST_FULL.xlsx"
    p.write_bytes(r.content)
    df=pd.read_excel(io.BytesIO(r.content),dtype=str).fillna("")
    required={"板块","公司全称","A股代码","A股简称","A股上市日期"}
    if not required.issubset(df.columns):
        raise RuntimeError(f"SZSE XLSX missing columns {sorted(required-set(df.columns))}")
    issuer={}
    for _,x in df.iterrows():
        board=str(x["板块"]).strip()
        code=str(x["A股代码"]).strip()
        if board not in {"主板","创业板"} or not CODE_RE.fullmatch(code):
            continue
        ld=pd.to_datetime(x["A股上市日期"],errors="coerce")
        if pd.isna(ld) or pd.Timestamp(ld).date()>asof_date:
            continue
        name=str(x["公司全称"]).strip()
        if not name:
            raise RuntimeError(f"SZSE issuer identity missing {code}")
        issuer[f"SZSE:{code}"]={
          "canonical_security_id":f"SZSE:{code}",
          "exchange":"SZSE","security_code":code,
          "official_issuer_query_key":code,
          "official_issuer_query_key_type":"SZSE_A_STOCK_CODE",
          "issuer_legal_name":name,
          "security_short_name":str(x["A股简称"]).strip(),
          "official_list_date":pd.Timestamp(ld).date().isoformat(),
          "official_board_code":board,
          "source_path":str(p.relative_to(OUT)),
          "source_sha256":sha(r.content)
        }
    if len(issuer)<=1000:
        raise RuntimeError(f"SZSE normalized count implausible {len(issuer)}")
    capture={
      "exchange":"SZSE","url":r.url,"status":r.status_code,
      "bytes":len(r.content),"sha256":sha(r.content),
      "captured_at_utc":datetime.now(timezone.utc).isoformat()
    }
    return issuer,[capture]

def build_raw_manifest():
    excluded={
      "V2.7.31_FORWARD_RAW_EVIDENCE.tar.gz","V2.7.31_FORWARD_RAW_MANIFEST.csv",
      "V2.7.31_FORWARD_CERTIFIED_UNIVERSE.csv","V2.7.31_FORWARD_CERTIFIED_UNIVERSE_RECEIPT.json",
      "V2.7.31_FORWARD_CURRENT_ISSUER_MAP.csv","V2.7.31_FORWARD_MEMBERSHIP_DELTA.csv"
    }
    rows=[]
    for p in sorted(OUT.rglob("*")):
        if not p.is_file() or p.name in excluded:
            continue
        b=p.read_bytes()
        rows.append({"path":str(p.relative_to(OUT)),"bytes":len(b),"sha256":sha(b)})
    manifest=OUT/"V2.7.31_FORWARD_RAW_MANIFEST.csv"
    write_csv(manifest,rows,["path","bytes","sha256"])
    bundle=OUT/"V2.7.31_FORWARD_RAW_EVIDENCE.tar.gz"
    with tarfile.open(bundle,"w:gz",compresslevel=9) as tf:
        for row in rows:
            tf.add(OUT/row["path"],arcname=row["path"])
    return manifest,bundle,rows

def main():
    started=datetime.now(timezone.utc)
    ensure_after_t0(started,"run_started_at_utc")
    asof_date=started.astimezone(BEIJING).date()

    baseline_issuer_rows=load_csv_exact(BASELINE_ISSUER,BASELINE_ISSUER_SHA)
    baseline_locator_rows=load_csv_exact(BASELINE_LOCATOR,BASELINE_LOCATOR_SHA)
    baseline_issuer={r["canonical_security_id"]:r for r in baseline_issuer_rows}
    baseline_locator={r["canonical_security_id"]:r for r in baseline_locator_rows}
    if set(baseline_issuer)!=set(baseline_locator):
        raise RuntimeError("baseline issuer/locator sets differ")
    baseline_ids=set(baseline_issuer)

    sse,sse_caps=fetch_sse(asof_date)
    szse,sz_caps=fetch_szse(asof_date)
    current_issuer={**sse,**szse}
    current_ids=set(current_issuer)
    observed_at=datetime.now(timezone.utc)
    ensure_after_t0(observed_at,"official_membership_observed_at_utc")

    added=sorted(current_ids-baseline_ids)
    removed=sorted(baseline_ids-current_ids)
    unchanged=sorted(current_ids&baseline_ids)
    print(f"CURRENT count={len(current_ids)} SSE={len(sse)} SZSE={len(szse)} unchanged={len(unchanged)} added={len(added)} removed={len(removed)}",flush=True)
    if added: print("ADDED "+json.dumps(added,ensure_ascii=False),flush=True)
    if removed: print("REMOVED "+json.dumps(removed,ensure_ascii=False),flush=True)

    issuer_path=OUT/"V2.7.31_FORWARD_CURRENT_ISSUER_MAP.csv"
    issuer_fields=[
      "canonical_security_id","exchange","security_code","official_issuer_query_key",
      "official_issuer_query_key_type","issuer_legal_name","security_short_name",
      "official_list_date","official_board_code","source_path","source_sha256"
    ]
    issuer_rows=[current_issuer[cid] for cid in sorted(current_issuer)]
    write_csv(issuer_path,issuer_rows,issuer_fields)

    delta_rows=[]
    for cid in added:
        delta_rows.append({"canonical_security_id":cid,"delta":"ADDED",**current_issuer[cid]})
    for cid in removed:
        delta_rows.append({"canonical_security_id":cid,"delta":"REMOVED",**baseline_issuer[cid]})
    delta_path=OUT/"V2.7.31_FORWARD_MEMBERSHIP_DELTA.csv"
    delta_fields=["canonical_security_id","delta"]+issuer_fields[1:]
    write_csv(delta_path,delta_rows,delta_fields)

    capture_manifest=OUT/"V2.7.31_OFFICIAL_DIRECT_CAPTURE_MANIFEST.json"
    capture_manifest.write_text(
      json.dumps({"sse":sse_caps,"szse":sz_caps},ensure_ascii=False,indent=2)+"\n",
      encoding="utf-8")

    certified_at=None
    universe_path=OUT/"V2.7.31_FORWARD_CERTIFIED_UNIVERSE.csv"
    if not added:
        certified_at=datetime.now(timezone.utc)
        universe=[]
        for cid in sorted(current_ids):
            issuer=current_issuer[cid]
            loc=baseline_locator[cid]
            if not loc.get("announcement_id") or not loc.get("adjunct_url"):
                raise RuntimeError(f"{cid}: baseline locator incomplete")
            universe.append({
              "epoch_id":EPOCH_ID,"epoch_t0_utc":T0_UTC,"certified_at_utc":certified_at.isoformat(),
              "canonical_security_id":cid,"exchange":issuer["exchange"],"security_code":issuer["security_code"],
              "official_issuer_query_key":issuer["official_issuer_query_key"],
              "official_issuer_query_key_type":issuer["official_issuer_query_key_type"],
              "issuer_legal_name":issuer["issuer_legal_name"],"security_short_name":issuer["security_short_name"],
              "official_list_date":issuer["official_list_date"],"official_board_code":issuer["official_board_code"],
              "membership_provenance":"FORWARD_OBSERVED_AFTER_T0",
              "membership_observed_at_utc":observed_at.isoformat(),
              "locator_provenance":"BASELINE_ADOPTED_AT_T0",
              "locator_original_first_observed_at_utc":BASELINE_LOCATOR_ORIGINAL_OBSERVED,
              "resolution":loc.get("resolution",""),"document_type":loc.get("document_type",""),
              "title":loc.get("title",""),"disclosure_date":loc.get("disclosure_date",""),
              "period_end":loc.get("period_end",""),"revision":loc.get("revision",""),
              "announcement_id":loc.get("announcement_id",""),"adjunct_url":loc.get("adjunct_url",""),
              "org_id":loc.get("org_id",""),"locator_source":loc.get("source",""),
              "pdf_materialization_status":"ON_DEMAND_NOT_REQUIRED_FOR_UNIVERSE_ENTRY",
              "universe_entry_status":"CERTIFIED"
            })
        write_csv(universe_path,universe,list(universe[0].keys()))

    manifest,bundle,raw_rows=build_raw_manifest()
    set_hash=sha(("\n".join(sorted(current_ids))+"\n").encode())
    gate_status="FORWARD_CERTIFIED_UNIVERSE_BOOTSTRAP_PASS" if not added else "FORWARD_MEMBERSHIP_DELTA_PASS_NEEDS_TARGETED_ADDITION_RESOLUTION"
    downstream_cert="PASS" if not added else "BLOCKED_ADDED_MEMBERS_NEED_LOCATOR"
    first60="READY_FOR_DETERMINISTIC_EPISODE_START_NOT_STARTED" if not added else "BLOCKED_PENDING_ADDED_MEMBER_LOCATORS"

    receipt={
      "schema":"AI_CORE_EVID_V2_7_31_FORWARD_MEMBERSHIP_BOOTSTRAP_RECEIPT_V1",
      "epoch_id":EPOCH_ID,"epoch_t0_utc":T0_UTC,
      "run_started_at_utc":started.isoformat(),
      "official_membership_observed_at_utc":observed_at.isoformat(),
      "asof_date_asia_shanghai":asof_date.isoformat(),
      "transport":{
        "sse":"DIRECT_REUSED_OFFICIAL_API_CONTRACT",
        "szse":"DIRECT_OFFICIAL_XLSX_EXPORT",
        "webpage_navigation":False,
        "chromium_required":False
      },
      "baseline":{
        "count":len(baseline_ids),"issuer_map_sha256":BASELINE_ISSUER_SHA,
        "primary_locator_inventory_sha256":BASELINE_LOCATOR_SHA,
        "adoption_semantics":"BASELINE_ADOPTED_AT_T0_FOR_POST_T0_DECISIONS_ONLY"
      },
      "current_official_membership":{
        "count":len(current_ids),"sse_count":len(sse),"szse_count":len(szse),
        "canonical_sorted_newline_sha256":set_hash
      },
      "delta":{
        "unchanged_count":len(unchanged),"added_count":len(added),"removed_count":len(removed),
        "added_ids":added,"removed_ids":removed
      },
      "current_issuer_identity":{
        "row_count":len(current_issuer),"exact_current_membership_coverage":True,
        "observed_after_t0":True
      },
      "outputs":{
        "current_issuer_map_sha256":sha(issuer_path.read_bytes()),
        "membership_delta_sha256":sha(delta_path.read_bytes()),
        "raw_manifest_sha256":sha(manifest.read_bytes()),
        "raw_bundle_sha256":sha(bundle.read_bytes()),
        "raw_bundle_bytes":bundle.stat().st_size,"raw_file_count":len(raw_rows)
      },
      "temporal_governance":{
        "pre_t0_decisions_authorized":False,
        "historical_2026_09_17_prospective_relabeling":"FORBIDDEN"
      },
      "downstream":{
        "certified_v2_universe":downstream_cert,
        "first60":first60,
        "filing_content_materialization":"ON_DEMAND_V2.7.30",
        "s4_s5_s6":"BLOCKED_PENDING_FIRST60_AND_LATER_GATES","live":"BLOCKED"
      },
      "gate":{
        "status":gate_status,
        "current_membership_exact":True,
        "issuer_identity_exact":True,
        "targeted_added_member_resolution_required":bool(added)
      }
    }
    if certified_at is not None:
        receipt["certified_at_utc"]=certified_at.isoformat()
        receipt["primary_locator"]={
          "terminal_locator_count":len(current_ids),
          "baseline_adopted_count":len(current_ids),
          "forward_targeted_resolution_count":0,"missing_count":0
        }
        receipt["outputs"]["certified_universe_sha256"]=sha(universe_path.read_bytes())

    canonical=json.dumps(receipt,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()
    receipt["receipt_sha256"]=sha(canonical)
    (OUT/"V2.7.31_FORWARD_CERTIFIED_UNIVERSE_RECEIPT.json").write_text(
      json.dumps(receipt,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(receipt,ensure_ascii=False,indent=2))

if __name__=="__main__":
    main()
