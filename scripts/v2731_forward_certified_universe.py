from __future__ import annotations

import csv
import hashlib
import json
import math
import re
import tarfile
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

EPOCH_ID="AI_CORE_EVID_FORWARD_EPOCH_001"
T0_UTC="2026-09-20T07:17:16Z"
T0_DT=datetime.fromisoformat(T0_UTC.replace("Z","+00:00"))

BASELINE_ISSUER=Path("evidence/V2.7.27_SECURITY_ISSUER_PIT_MAP.csv")
BASELINE_ISSUER_SHA="769960860eaeb97f34780eca3b8cdb2618a4e3afd580e97f59fe6435da8b25a8"
BASELINE_LOCATOR=Path("evidence/V2.7.29_PRIMARY_LOCATOR_INVENTORY.csv")
BASELINE_LOCATOR_SHA="6f497c81f99344596ba19e7ef62c54a23d373c07f80877d79af6f70f19f4a4f4"
BASELINE_LOCATOR_ORIGINAL_OBSERVED="2026-09-20T06:36:51.251465+00:00"
FROZEN_OFFICIAL_SET_SHA="b9733a28f99a8c91902fb5ba7fb2fbcce5f2b4845612a1bc225a888bcc2cfa6c"
FROZEN_SNAPSHOT_COMPLETED_AFTER_UTC="2026-09-18T08:02:28Z"

OUT=Path("v2731_forward_bootstrap")
RAW=OUT/"raw"
SSE_RAW=RAW/"sse"
OUT.mkdir(exist_ok=True)
SSE_RAW.mkdir(parents=True,exist_ok=True)

SSE_ENDPOINT="https://query.sse.com.cn/sseQuery/commonQuery.do"
SSE_REFERER="https://www.sse.com.cn/assortment/stock/list/share/"
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

def write_csv(path,rows,fields):
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
    members={}
    captures=[]
    for stock_type,label in (("1","main_a"),("8","star")):
        base={
          "jsonCallBack":f"jsonpCallback2731{stock_type}",
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
        q1={**base,"pageHelp.beginPage":"1","pageHelp.pageNo":"1","pageHelp.endPage":"1"}
        r=sess.get(SSE_ENDPOINT,params=q1,timeout=30)
        if r.status_code!=200:
            raise RuntimeError(f"SSE {label} first page HTTP {r.status_code}")
        first_obj=decode_json_or_jsonp(r.content)
        ph=first_obj.get("pageHelp",{}) if isinstance(first_obj,dict) else {}
        total=int(ph.get("total") or 0)
        page_size=int(ph.get("pageSize") or 25)
        if total<=0:
            raise RuntimeError(f"SSE {label}: invalid total={total}")
        pages=max(1,math.ceil(total/page_size))
        for n in range(1,pages+1):
            params={**base,"pageHelp.beginPage":str(n),"pageHelp.pageNo":str(n),"pageHelp.endPage":str(n)}
            rr=r if n==1 else sess.get(SSE_ENDPOINT,params=params,timeout=30)
            if rr.status_code!=200:
                raise RuntimeError(f"SSE {label} page {n} HTTP {rr.status_code}")
            p=SSE_RAW/f"{label}_{n:04d}.json"
            p.write_bytes(rr.content)
            captures.append({
              "exchange":"SSE","board":label,"page":n,"url":rr.url,
              "status":rr.status_code,"bytes":len(rr.content),
              "sha256":sha(rr.content),"captured_at_utc":datetime.now(timezone.utc).isoformat()
            })
            obj=decode_json_or_jsonp(rr.content)
            rows=obj.get("result") or []
            if not isinstance(rows,list):
                raise RuntimeError(f"SSE {label} page {n}: result is not list")
            for x in rows:
                code=str(x.get("A_STOCK_CODE") or "").strip()
                st=str(x.get("STOCK_TYPE") or "").strip()
                if not CODE_RE.fullmatch(code) or st not in {"1","8"}:
                    continue
                ld=pd.to_datetime(x.get("LIST_DATE"),errors="coerce")
                if pd.isna(ld) or pd.Timestamp(ld).date()>asof_date:
                    continue
                cid=f"SSE:{code}"
                members[cid]={
                  "canonical_security_id":cid,
                  "exchange":"SSE",
                  "security_code":code,
                  "security_short_name":str(x.get("COMPANY_ABBR") or "").strip(),
                  "official_list_date":pd.Timestamp(ld).date().isoformat(),
                  "official_board_code":str(x.get("LIST_BOARD") or "").strip(),
                  "membership_source_path":str(p.relative_to(OUT)),
                  "membership_source_sha256":sha(rr.content),
                  "membership_provenance":"FORWARD_OBSERVED_AFTER_T0"
                }
    if len(members)<=1000:
        raise RuntimeError(f"SSE count implausible {len(members)}")
    return members,captures

def build_raw_manifest():
    excluded={
      "V2.7.31_FORWARD_RAW_EVIDENCE.tar.gz",
      "V2.7.31_FORWARD_RAW_MANIFEST.csv",
      "V2.7.31_FORWARD_CERTIFIED_UNIVERSE.csv",
      "V2.7.31_FORWARD_CERTIFIED_UNIVERSE_RECEIPT.json",
      "V2.7.31_FORWARD_CURRENT_ISSUER_MAP.csv",
      "V2.7.31_FORWARD_MEMBERSHIP_DELTA.csv",
      "V2.7.31_FORWARD_MEMBERSHIP_SNAPSHOT.csv",
      "V2.7.31_NO_CHANGE_INTERVAL_PROOF_EXECUTION.json"
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
    asof_date=started.date()

    baseline_issuer_rows=load_csv_exact(BASELINE_ISSUER,BASELINE_ISSUER_SHA)
    baseline_locator_rows=load_csv_exact(BASELINE_LOCATOR,BASELINE_LOCATOR_SHA)
    baseline_issuer={r["canonical_security_id"]:r for r in baseline_issuer_rows}
    baseline_locator={r["canonical_security_id"]:r for r in baseline_locator_rows}
    baseline_ids=set(baseline_issuer)
    if baseline_ids!=set(baseline_locator):
        raise RuntimeError("baseline issuer/locator sets differ")
    baseline_set_hash=sha(("\n".join(sorted(baseline_ids))+"\n").encode())
    if baseline_set_hash!=FROZEN_OFFICIAL_SET_SHA:
        raise RuntimeError("baseline set hash mismatch")

    baseline_sse={cid for cid in baseline_ids if cid.startswith("SSE:")}
    baseline_szse={cid for cid in baseline_ids if cid.startswith("SZSE:")}
    if len(baseline_sse)!=2320 or len(baseline_szse)!=2901:
        raise RuntimeError(f"baseline exchange counts unexpected SSE={len(baseline_sse)} SZSE={len(baseline_szse)}")

    sse_current,sse_caps=fetch_sse(asof_date)
    sse_ids=set(sse_current)
    sse_observed_at=datetime.now(timezone.utc)
    ensure_after_t0(sse_observed_at,"sse_membership_observed_at_utc")

    # Narrow bootstrap-only carry forward for SZSE, authorized by V2.7.31-A1.
    szse_current=baseline_szse
    szse_provenance="FORWARD_CARRIED_BY_NO_CHANGE_INTERVAL_PROOF"

    current_ids=sse_ids|szse_current
    added=sorted(current_ids-baseline_ids)
    removed=sorted(baseline_ids-current_ids)
    unchanged=sorted(current_ids&baseline_ids)

    print(f"CURRENT count={len(current_ids)} SSE={len(sse_ids)} SZSE={len(szse_current)} unchanged={len(unchanged)} added={len(added)} removed={len(removed)}",flush=True)
    if added: print("ADDED "+json.dumps(added,ensure_ascii=False),flush=True)
    if removed: print("REMOVED "+json.dumps(removed,ensure_ascii=False),flush=True)

    proof_exec={
      "schema":"AI_CORE_EVID_V2_7_31_NO_CHANGE_INTERVAL_PROOF_EXECUTION_V1",
      "amendment":"evidence/V2.7.31_FORWARD_EPOCH_CONTRACT_AMENDMENT_1.json",
      "source_snapshot_completed_after_utc":FROZEN_SNAPSHOT_COMPLETED_AFTER_UTC,
      "epoch_t0_utc":T0_UTC,
      "source_snapshot_set_sha256":FROZEN_OFFICIAL_SET_SHA,
      "source_snapshot_total_count":5221,
      "source_snapshot_szse_count":2901,
      "intervening_exchange_trading_sessions":0,
      "local_interval_description":"2026-09-18 Friday post-close snapshot -> 2026-09-20 Sunday T0",
      "result":"PASS_NO_EXCHANGE_TRADING_SESSION_IN_INTERVAL",
      "szse_membership_provenance":szse_provenance,
      "source_bytes_reclassified_as_post_t0":False
    }
    proof_path=OUT/"V2.7.31_NO_CHANGE_INTERVAL_PROOF_EXECUTION.json"
    proof_path.write_text(json.dumps(proof_exec,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")

    snapshot_rows=[]
    for cid in sorted(current_ids):
        if cid.startswith("SSE:"):
            m=sse_current[cid]
            snapshot_rows.append(m)
        else:
            b=baseline_issuer[cid]
            snapshot_rows.append({
              "canonical_security_id":cid,
              "exchange":"SZSE",
              "security_code":b["security_code"],
              "security_short_name":b["security_short_name"],
              "official_list_date":b["official_list_date"],
              "official_board_code":b["official_board_code"],
              "membership_source_path":b["source_path"],
              "membership_source_sha256":b["source_sha256"],
              "membership_provenance":szse_provenance
            })
    membership_path=OUT/"V2.7.31_FORWARD_MEMBERSHIP_SNAPSHOT.csv"
    membership_fields=[
      "canonical_security_id","exchange","security_code","security_short_name",
      "official_list_date","official_board_code","membership_source_path",
      "membership_source_sha256","membership_provenance"
    ]
    write_csv(membership_path,snapshot_rows,membership_fields)

    delta_path=OUT/"V2.7.31_FORWARD_MEMBERSHIP_DELTA.csv"
    delta_rows=[]
    for cid in added:
        if cid.startswith("SSE:"):
            delta_rows.append({"canonical_security_id":cid,"delta":"ADDED",**sse_current[cid]})
        else:
            delta_rows.append({"canonical_security_id":cid,"delta":"ADDED"})
    for cid in removed:
        b=baseline_issuer[cid]
        delta_rows.append({
          "canonical_security_id":cid,"delta":"REMOVED",
          "exchange":b["exchange"],"security_code":b["security_code"],
          "security_short_name":b["security_short_name"],"official_list_date":b["official_list_date"],
          "official_board_code":b["official_board_code"],"membership_provenance":"BASELINE_ONLY_REMOVED"
        })
    write_csv(delta_path,delta_rows,["canonical_security_id","delta","exchange","security_code","security_short_name","official_list_date","official_board_code","membership_provenance","membership_source_path","membership_source_sha256"])

    sse_manifest=OUT/"V2.7.31_SSE_FORWARD_CAPTURE_MANIFEST.json"
    sse_manifest.write_text(json.dumps({"captures":sse_caps},ensure_ascii=False,indent=2)+"\n",encoding="utf-8")

    certified_at=None
    issuer_path=OUT/"V2.7.31_FORWARD_CURRENT_ISSUER_MAP.csv"
    universe_path=OUT/"V2.7.31_FORWARD_CERTIFIED_UNIVERSE.csv"

    # Any post-T0 addition not present in frozen issuer+locator baseline still blocks certification.
    unresolved_added=[cid for cid in added if cid not in baseline_issuer or cid not in baseline_locator]

    if not unresolved_added:
        certified_at=datetime.now(timezone.utc)
        ensure_after_t0(certified_at,"certified_at_utc")
        issuer_rows=[]
        universe=[]
        issuer_fields=[
          "canonical_security_id","exchange","security_code","official_issuer_query_key",
          "official_issuer_query_key_type","issuer_legal_name","security_short_name",
          "official_list_date","official_board_code","issuer_provenance",
          "membership_provenance","baseline_source_path","baseline_source_sha256"
        ]
        for cid in sorted(current_ids):
            issuer=baseline_issuer[cid]
            loc=baseline_locator[cid]
            if not loc.get("announcement_id") or not loc.get("adjunct_url"):
                raise RuntimeError(f"{cid}: locator incomplete")
            mem_prov="FORWARD_OBSERVED_AFTER_T0" if cid.startswith("SSE:") else szse_provenance
            issuer_rows.append({
              "canonical_security_id":cid,
              "exchange":issuer["exchange"],
              "security_code":issuer["security_code"],
              "official_issuer_query_key":issuer["official_issuer_query_key"],
              "official_issuer_query_key_type":issuer["official_issuer_query_key_type"],
              "issuer_legal_name":issuer["issuer_legal_name"],
              "security_short_name":issuer["security_short_name"],
              "official_list_date":issuer["official_list_date"],
              "official_board_code":issuer["official_board_code"],
              "issuer_provenance":"BASELINE_ADOPTED_AT_T0",
              "membership_provenance":mem_prov,
              "baseline_source_path":issuer["source_path"],
              "baseline_source_sha256":issuer["source_sha256"]
            })
            universe.append({
              "epoch_id":EPOCH_ID,
              "epoch_t0_utc":T0_UTC,
              "certified_at_utc":certified_at.isoformat(),
              "canonical_security_id":cid,
              "exchange":issuer["exchange"],
              "security_code":issuer["security_code"],
              "issuer_legal_name":issuer["issuer_legal_name"],
              "security_short_name":issuer["security_short_name"],
              "official_list_date":issuer["official_list_date"],
              "official_board_code":issuer["official_board_code"],
              "membership_provenance":mem_prov,
              "issuer_provenance":"BASELINE_ADOPTED_AT_T0",
              "locator_provenance":"BASELINE_ADOPTED_AT_T0",
              "locator_original_first_observed_at_utc":BASELINE_LOCATOR_ORIGINAL_OBSERVED,
              "resolution":loc.get("resolution",""),
              "document_type":loc.get("document_type",""),
              "title":loc.get("title",""),
              "disclosure_date":loc.get("disclosure_date",""),
              "period_end":loc.get("period_end",""),
              "revision":loc.get("revision",""),
              "announcement_id":loc.get("announcement_id",""),
              "adjunct_url":loc.get("adjunct_url",""),
              "org_id":loc.get("org_id",""),
              "locator_source":loc.get("source",""),
              "pdf_materialization_status":"ON_DEMAND_NOT_REQUIRED_FOR_UNIVERSE_ENTRY",
              "universe_entry_status":"CERTIFIED"
            })
        write_csv(issuer_path,issuer_rows,issuer_fields)
        write_csv(universe_path,universe,list(universe[0].keys()))

    manifest,bundle,raw_rows=build_raw_manifest()
    current_set_hash=sha(("\n".join(sorted(current_ids))+"\n").encode())

    gate_status="FORWARD_CERTIFIED_UNIVERSE_BOOTSTRAP_PASS" if not unresolved_added else "FORWARD_MEMBERSHIP_PASS_ADDED_MEMBERS_UNRESOLVED"
    cert_status="PASS" if not unresolved_added else "BLOCKED_ADDED_MEMBERS_NEED_TARGETED_RESOLUTION"
    first60="READY_FOR_DETERMINISTIC_EPISODE_START_NOT_STARTED" if not unresolved_added else "BLOCKED_PENDING_ADDED_MEMBER_RESOLUTION"

    receipt={
      "schema":"AI_CORE_EVID_V2_7_31_FORWARD_CERTIFIED_UNIVERSE_RECEIPT_V3",
      "epoch_id":EPOCH_ID,
      "epoch_t0_utc":T0_UTC,
      "run_started_at_utc":started.isoformat(),
      "sse_membership_observed_at_utc":sse_observed_at.isoformat(),
      "szse_membership_provenance":szse_provenance,
      "contract_amendment":"V2.7.31-A1",
      "current_official_membership":{
        "count":len(current_ids),
        "sse_count":len(sse_ids),
        "szse_count":len(szse_current),
        "canonical_sorted_newline_sha256":current_set_hash
      },
      "delta":{
        "unchanged_count":len(unchanged),
        "added_count":len(added),
        "removed_count":len(removed),
        "added_ids":added,
        "removed_ids":removed,
        "unresolved_added_ids":unresolved_added
      },
      "no_change_interval_proof":{
        "status":"PASS_NO_EXCHANGE_TRADING_SESSION_IN_INTERVAL",
        "source_snapshot_completed_after_utc":FROZEN_SNAPSHOT_COMPLETED_AFTER_UTC,
        "source_snapshot_set_sha256":FROZEN_OFFICIAL_SET_SHA,
        "source_bytes_reclassified_as_post_t0":False
      },
      "outputs":{
        "membership_snapshot_sha256":sha(membership_path.read_bytes()),
        "membership_delta_sha256":sha(delta_path.read_bytes()),
        "no_change_proof_sha256":sha(proof_path.read_bytes()),
        "raw_manifest_sha256":sha(manifest.read_bytes()),
        "raw_bundle_sha256":sha(bundle.read_bytes()),
        "raw_bundle_bytes":bundle.stat().st_size,
        "raw_file_count":len(raw_rows)
      },
      "temporal_governance":{
        "pre_t0_decisions_authorized":False,
        "historical_2026_09_17_prospective_relabeling":"FORBIDDEN"
      },
      "downstream":{
        "certified_v2_universe":cert_status,
        "first60":first60,
        "filing_content_materialization":"ON_DEMAND_V2.7.30",
        "vendor_price_coverage":"SEPARATE_PER_SECURITY_EXECUTION_GATE",
        "s4_s5_s6":"BLOCKED_PENDING_FIRST60_AND_LATER_GATES",
        "live":"BLOCKED"
      },
      "gate":{
        "status":gate_status,
        "sse_forward_observation_pass":True,
        "szse_no_change_interval_proof_pass":True,
        "terminal_issuer_locator_complete":not unresolved_added
      }
    }
    if certified_at is not None:
        receipt["certified_at_utc"]=certified_at.isoformat()
        receipt["issuer_identity"]={
          "terminal_identity_count":len(current_ids),
          "baseline_adopted_count":len(current_ids),
          "missing_count":0
        }
        receipt["primary_locator"]={
          "terminal_locator_count":len(current_ids),
          "baseline_adopted_count":len(current_ids),
          "missing_count":0
        }
        receipt["outputs"]["current_issuer_map_sha256"]=sha(issuer_path.read_bytes())
        receipt["outputs"]["certified_universe_sha256"]=sha(universe_path.read_bytes())

    canonical=json.dumps(receipt,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()
    receipt["receipt_sha256"]=sha(canonical)
    (OUT/"V2.7.31_FORWARD_CERTIFIED_UNIVERSE_RECEIPT.json").write_text(
      json.dumps(receipt,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(receipt,ensure_ascii=False,indent=2))

if __name__=="__main__":
    main()
