from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import re
import shutil
from datetime import date
from pathlib import Path

CURRENT=Path("evidence/V2.7.31_FORWARD_CERTIFIED_UNIVERSE.csv")
EXPECTED_CURRENT_SHA="8815cd4ff5fb1f82e7c49b2a142ceb8e12138a4068d7a21c8ae144b57cc3f92d"
EXPECTED_SET_SHA="b9733a28f99a8c91902fb5ba7fb2fbcce5f2b4845612a1bc225a888bcc2cfa6c"
EXPECTED_ARTIFACT_ID=10535944660
EXPECTED_ARTIFACT_DIGEST="sha256:5ecbfe0b868e4709a97d71a703d07465156dbd48304e6d444ec93952e0b5e3dd"
EXPECTED_SSE_MAIN_SHA="d3d61557c176799dde4e4843a9cc815dc1174a7b5adaf9858a09612cd7bbc33d"
EXPECTED_SSE_STAR_SHA="6553b9f47ca966dbff810c96bf9d796b963591c2b3b081efa495da4148b8784f"

def sha_bytes(b:bytes)->str:
    return hashlib.sha256(b).hexdigest()

def sha_file(p:Path)->str:
    return sha_bytes(p.read_bytes())

def parse_date(s:str)->date:
    s=str(s or "").strip()
    if re.fullmatch(r"\d{8}",s):
        s=f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    return date.fromisoformat(s)

def clean_name(s:str)->str:
    return re.sub(r"\s+","",html.unescape(str(s or "").replace("&nbsp;","")))

def set_hash(ids)->str:
    return sha_bytes(("\n".join(sorted(ids))+"\n").encode())

def load_current():
    if sha_file(CURRENT)!=EXPECTED_CURRENT_SHA:
        raise RuntimeError("current Certified Universe SHA mismatch")
    rows=list(csv.DictReader(CURRENT.open(encoding="utf-8")))
    if len(rows)!=5221:
        raise RuntimeError(f"current universe rows {len(rows)} != 5221")
    by={}
    for r in rows:
        cid=r["canonical_security_id"]
        if cid in by:
            raise RuntimeError(f"duplicate current id {cid}")
        ld=parse_date(r["official_list_date"])
        by[cid]={
          "canonical_security_id":cid,
          "exchange":r["exchange"],
          "security_code":r["security_code"],
          "security_name":r["security_short_name"],
          "official_list_date":ld.isoformat(),
          "official_delist_date":"",
          "official_board_code":r.get("official_board_code",""),
          "official_stock_type":"",
          "membership_interval_source":"V2.7.31_FORWARD_CERTIFIED_UNIVERSE",
          "source_file":"evidence/V2.7.31_FORWARD_CERTIFIED_UNIVERSE.csv",
          "source_file_sha256":EXPECTED_CURRENT_SHA,
        }
    if set_hash(by)!=EXPECTED_SET_SHA:
        raise RuntimeError("current canonical-set hash mismatch")
    return by

def find_one(root:Path,name:str)->Path:
    hits=list(root.rglob(name))
    if len(hits)!=1:
        raise RuntimeError(f"expected exactly one {name}, found {len(hits)}")
    return hits[0]

def load_delisted(artifact_root:Path, durable_raw:Path):
    main=find_one(artifact_root,"sse_delisted_MAIN_A_1.json")
    star=find_one(artifact_root,"sse_delisted_STAR_1.json")
    if sha_file(main)!=EXPECTED_SSE_MAIN_SHA:
        raise RuntimeError("SSE Main delist raw hash mismatch")
    if sha_file(star)!=EXPECTED_SSE_STAR_SHA:
        raise RuntimeError("SSE STAR delist raw hash mismatch")

    durable_raw.mkdir(parents=True,exist_ok=True)
    source_manifest=[]
    all_events=[]

    for p,label,expected_count in ((main,"SSE_MAIN_A",143),(star,"SSE_STAR",3)):
        dst=durable_raw/p.name
        shutil.copyfile(p,dst)
        obj=json.loads(p.read_text(encoding="utf-8"))
        rows=obj.get("result") or (obj.get("pageHelp") or {}).get("data") or []
        if len(rows)!=expected_count:
            raise RuntimeError(f"{label} rows {len(rows)} != {expected_count}")
        source_manifest.append({"file":p.name,"bytes":p.stat().st_size,"sha256":sha_file(p),"rows":len(rows)})
        for r in rows:
            code=str(r.get("A_STOCK_CODE") or "").strip()
            ld=parse_date(r.get("LIST_DATE"))
            dd=parse_date(r.get("DELIST_DATE"))
            if not code or ld>=dd:
                raise RuntimeError(f"invalid SSE delist interval {code} {ld} {dd}")
            all_events.append({
              "canonical_security_id":f"SSE:{code}",
              "exchange":"SSE","security_code":code,
              "security_name":clean_name(r.get("COMPANY_ABBR")),
              "official_list_date":ld.isoformat(),
              "official_delist_date":dd.isoformat(),
              "official_board_code":str(r.get("LIST_BOARD") or ""),
              "official_stock_type":str(r.get("STOCK_TYPE") or ""),
              "membership_interval_source":"SSE_OFFICIAL_DELIST_TABLE",
              "source_file":p.name,
              "source_file_sha256":sha_file(p),
              "excluded_from_a_share_scope":False,
              "exclusion_reason":"",
            })

    sz_pages=sorted(artifact_root.rglob("szse_delisted_page_*.json"))
    if len(sz_pages)!=11:
        raise RuntimeError(f"SZSE page count {len(sz_pages)} != 11")
    sz_rows=[]
    server_recordcount=None
    for p in sz_pages:
        dst=durable_raw/p.name
        shutil.copyfile(p,dst)
        obj=json.loads(p.read_text(encoding="utf-8"))
        block=next((x for x in obj if isinstance(x,dict) and (x.get("metadata") or {}).get("tabkey")=="tab2"),None)
        if block is None:
            raise RuntimeError(f"{p.name}: terminal-list tab2 absent")
        md=block.get("metadata") or {}
        rc=int(md.get("recordcount") or 0)
        if server_recordcount is None: server_recordcount=rc
        elif rc!=server_recordcount: raise RuntimeError("SZSE recordcount changed across retained pages")
        rows=block.get("data") or []
        sz_rows.extend((p,r) for r in rows)
        source_manifest.append({"file":p.name,"bytes":p.stat().st_size,"sha256":sha_file(p),"rows":len(rows)})
    if server_recordcount!=208 or len(sz_rows)!=208:
        raise RuntimeError(f"SZSE pagination closure failed server={server_recordcount} rows={len(sz_rows)}")

    excluded_b=[]
    included_sz=[]
    for p,r in sz_rows:
        code=str(r.get("zqdm") or "").strip()
        name=clean_name(r.get("zqjc"))
        ld=parse_date(r.get("ssrq"))
        dd=parse_date(r.get("zzrq"))
        if not code or ld>=dd:
            raise RuntimeError(f"invalid SZSE delist interval {code} {ld} {dd}")
        explicit_b=bool(re.search(r"[BＢ]",name,re.I))
        rec={
          "canonical_security_id":f"SZSE:{code}",
          "exchange":"SZSE","security_code":code,
          "security_name":name,
          "official_list_date":ld.isoformat(),
          "official_delist_date":dd.isoformat(),
          "official_board_code":"",
          "official_stock_type":"",
          "membership_interval_source":"SZSE_OFFICIAL_TERMINAL_LIST",
          "source_file":p.name,
          "source_file_sha256":sha_file(p),
          "excluded_from_a_share_scope":explicit_b,
          "exclusion_reason":"OFFICIAL_SECURITY_NAME_EXPLICIT_B_SHARE" if explicit_b else "",
        }
        all_events.append(rec)
        (excluded_b if explicit_b else included_sz).append(rec)

    if len(excluded_b)!=21:
        raise RuntimeError(f"explicit SZSE B-share exclusions {len(excluded_b)} != 21")
    if len(included_sz)!=187:
        raise RuntimeError(f"included SZSE A-share terminal rows {len(included_sz)} != 187")

    included=[r for r in all_events if not r["excluded_from_a_share_scope"]]
    if len(included)!=333:
        raise RuntimeError(f"included A-share delist events {len(included)} != 333")
    return all_events,included,excluded_b,source_manifest

def write_csv(path,rows,fields):
    with path.open("w",encoding="utf-8",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,lineterminator="\n")
        w.writeheader()
        for r in rows: w.writerow({k:r.get(k,"") for k in fields})

def eligible(interval,date_):
    ld=parse_date(interval["official_list_date"])
    dd=parse_date(interval["official_delist_date"]) if interval["official_delist_date"] else None
    return ld<=date_ and (dd is None or date_<dd)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--artifact-root",required=True)
    ap.add_argument("--artifact-meta",required=True)
    ap.add_argument("--out",default="v281_pit_membership")
    args=ap.parse_args()
    root=Path(args.artifact_root)
    out=Path(args.out); out.mkdir(parents=True,exist_ok=True)
    raw=out/"raw_official"
    meta=json.loads(Path(args.artifact_meta).read_text(encoding="utf-8"))
    if int(meta.get("id") or 0)!=EXPECTED_ARTIFACT_ID:
        raise RuntimeError("artifact id mismatch")
    if meta.get("digest")!=EXPECTED_ARTIFACT_DIGEST:
        raise RuntimeError(f"artifact digest mismatch {meta.get('digest')}")

    current=load_current()
    all_events,delisted_a,excluded_b,source_manifest=load_delisted(root,raw)

    overlap=sorted(set(current)&{r["canonical_security_id"] for r in delisted_a})
    if overlap:
        raise RuntimeError(f"current/delisted identity overlap: {overlap[:20]}")

    intervals=list(current.values())+[
      {k:v for k,v in r.items() if k not in ("excluded_from_a_share_scope","exclusion_reason")}
      for r in delisted_a
    ]
    if len(intervals)!=5554:
        raise RuntimeError(f"interval count {len(intervals)} != 5554")
    ids=[r["canonical_security_id"] for r in intervals]
    if len(ids)!=len(set(ids)):
        raise RuntimeError("interval identity duplication")

    fields=[
      "canonical_security_id","exchange","security_code","security_name",
      "official_list_date","official_delist_date","official_board_code","official_stock_type",
      "membership_interval_source","source_file","source_file_sha256"
    ]
    intervals.sort(key=lambda r:r["canonical_security_id"])
    delisted_a.sort(key=lambda r:r["canonical_security_id"])
    all_events.sort(key=lambda r:(r["exchange"],r["security_code"]))
    excluded_b.sort(key=lambda r:r["canonical_security_id"])
    write_csv(out/"V2.8.1_PIT_MEMBERSHIP_INTERVALS.csv",intervals,fields)
    write_csv(out/"V2.8.1_OFFICIAL_DELIST_EVENT_LEDGER.csv",all_events,fields+["excluded_from_a_share_scope","exclusion_reason"])
    write_csv(out/"V2.8.1_SZSE_B_SHARE_EXCLUSION_AUDIT.csv",excluded_b,fields+["excluded_from_a_share_scope","exclusion_reason"])
    write_csv(out/"V2.8.1_OFFICIAL_DELIST_RAW_MANIFEST.csv",source_manifest,["file","bytes","sha256","rows"])

    # Actual PIT reconstruction tests.
    def members_on(ds):
        d=date.fromisoformat(ds)
        return {r["canonical_security_id"] for r in intervals if eligible(r,d)}

    pit_0917=members_on("2026-09-17")
    tests=[]
    tests.append({"name":"T01_reconstruct_2026_09_17_exact_set","pass":len(pit_0917)==5221 and set_hash(pit_0917)==EXPECTED_SET_SHA,
                  "count":len(pit_0917),"sha256":set_hash(pit_0917)})
    tests.append({"name":"T02_new_listing_excluded_before_list_date",
                  "pass":"SSE:601091" not in members_on("2026-09-16") and "SSE:601091" in pit_0917})
    tests.append({"name":"T03_sse_delist_effective_date_exclusive",
                  "pass":"SSE:688287" in members_on("2026-06-09") and "SSE:688287" not in members_on("2026-06-10")})
    tests.append({"name":"T04_szse_delist_effective_date_exclusive",
                  "pass":"SZSE:000004" in members_on("2026-07-13") and "SZSE:000004" not in members_on("2026-07-14")})
    tests.append({"name":"T05_explicit_b_share_absent",
                  "pass":"SZSE:200002" not in {r["canonical_security_id"] for r in intervals}})
    pit_2025=members_on("2025-01-02")
    survivor_2025={cid for cid,r in current.items() if parse_date(r["official_list_date"])<=date.fromisoformat("2025-01-02")}
    tests.append({"name":"T06_survivor_only_shortcut_detected",
                  "pass":len(pit_2025-survivor_2025)>0,
                  "historical_members_missing_from_survivor_only":len(pit_2025-survivor_2025)})
    tests.append({"name":"T07_no_identity_overlap","pass":len(overlap)==0})
    if not all(t["pass"] for t in tests):
        raise RuntimeError(f"PIT membership selftest failed: {[t for t in tests if not t['pass']]}")

    receipt={
      "schema":"AI_CORE_EVID_V2_8_1_PIT_MEMBERSHIP_RECONSTRUCTION_V1",
      "authorities":{
        "current_universe_sha256":EXPECTED_CURRENT_SHA,
        "delist_artifact_id":EXPECTED_ARTIFACT_ID,
        "delist_artifact_digest":EXPECTED_ARTIFACT_DIGEST
      },
      "source_counts":{
        "current_active":len(current),
        "sse_delisted_a":146,
        "szse_terminal_total":208,
        "szse_explicit_b_excluded":len(excluded_b),
        "szse_delisted_a_included":len(delisted_a)-146,
        "all_delisted_a_included":len(delisted_a),
        "interval_rows":len(intervals)
      },
      "interval_semantics":"list_date <= D < delist_date; blank delist_date is open-ended",
      "selftests":tests,
      "research_date_diagnostics":{
        "2025-01-02_members":len(pit_2025),
        "2025-01-02_non_survivor_members":len(pit_2025-survivor_2025),
        "2026-09-17_members":len(pit_0917)
      },
      "outputs":{
        "intervals_sha256":sha_file(out/"V2.8.1_PIT_MEMBERSHIP_INTERVALS.csv"),
        "delist_ledger_sha256":sha_file(out/"V2.8.1_OFFICIAL_DELIST_EVENT_LEDGER.csv"),
        "b_exclusion_audit_sha256":sha_file(out/"V2.8.1_SZSE_B_SHARE_EXCLUSION_AUDIT.csv"),
        "raw_manifest_sha256":sha_file(out/"V2.8.1_OFFICIAL_DELIST_RAW_MANIFEST.csv")
      },
      "gate":{"status":"PIT_MEMBERSHIP_INTERVALS_PASS","survivorship_shortcut_forbidden":True}
    }
    canonical=json.dumps(receipt,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()
    receipt["receipt_sha256"]=sha_bytes(canonical)
    (out/"V2.8.1_PIT_MEMBERSHIP_RECONSTRUCTION_RECEIPT.json").write_text(
      json.dumps(receipt,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(receipt,ensure_ascii=False,indent=2))

if __name__=="__main__":
    main()
