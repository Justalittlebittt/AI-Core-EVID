from __future__ import annotations
import csv, hashlib, io, json, re
from pathlib import Path
from typing import Any
import pandas as pd

PIT=pd.Timestamp("2026-09-17")
EXPECTED_COUNT=5221
EXPECTED_SSE=2320
EXPECTED_SZSE=2901
EXPECTED_SET_HASH="b9733a28f99a8c91902fb5ba7fb2fbcce5f2b4845612a1bc225a888bcc2cfa6c"

ROOT=Path("source_artifact")
OUT=Path("v2727_generated"); OUT.mkdir(exist_ok=True)
CODE_RE=re.compile(r"^\d{6}$")

def sha_bytes(b:bytes)->str:
    return hashlib.sha256(b).hexdigest()

def decode_json_or_jsonp(b:bytes)->Any:
    s=b.decode("utf-8","ignore").strip()
    try:
        return json.loads(s)
    except Exception:
        m=re.match(r"^[A-Za-z_$][\w$]*\((.*)\)\s*;?\s*$",s,re.S)
        if not m: raise
        return json.loads(m.group(1))

def collect_sse_rows(obj:Any,out:list[dict[str,Any]]):
    if isinstance(obj,dict):
        if "A_STOCK_CODE" in obj and "STOCK_TYPE" in obj:
            out.append(obj)
        for v in obj.values(): collect_sse_rows(v,out)
    elif isinstance(obj,list):
        for v in obj: collect_sse_rows(v,out)

def dt(v:Any):
    return pd.to_datetime(v,errors="coerce")

def build_sse()->list[dict[str,Any]]:
    candidates={}
    for p in sorted(ROOT.rglob("raw/sse/*.json")):
        b=p.read_bytes()
        try: obj=decode_json_or_jsonp(b)
        except Exception: continue
        rows=[]; collect_sse_rows(obj,rows)
        fsha=sha_bytes(b)
        for r in rows:
            code=str(r.get("A_STOCK_CODE","")).strip()
            stock_type=str(r.get("STOCK_TYPE","")).strip()
            ld=dt(r.get("LIST_DATE"))
            if not CODE_RE.fullmatch(code) or stock_type not in {"1","8"}:
                continue
            if pd.isna(ld) or pd.Timestamp(ld).tz_localize(None) > PIT:
                continue
            company_code=str(r.get("COMPANY_CODE","")).strip()
            full_name=str(r.get("FULL_NAME","")).strip()
            if not CODE_RE.fullmatch(company_code) or not full_name:
                raise RuntimeError(f"SSE issuer identity missing for {code}")
            rec={
              "pit_date":"2026-09-17",
              "canonical_security_id":f"SSE:{code}",
              "exchange":"SSE",
              "security_code":code,
              "official_issuer_query_key":company_code,
              "official_issuer_query_key_type":"SSE_COMPANY_CODE",
              "issuer_legal_name":full_name,
              "security_short_name":str(r.get("COMPANY_ABBR","")).strip(),
              "official_list_date":pd.Timestamp(ld).date().isoformat(),
              "official_board_code":str(r.get("LIST_BOARD","")).strip(),
              "source_path":str(p.relative_to(ROOT)),
              "source_sha256":fsha,
            }
            candidates.setdefault(code,[]).append(rec)
    out=[]
    for code,recs in candidates.items():
        stable={(r["official_issuer_query_key"],r["issuer_legal_name"],r["official_list_date"],r["official_board_code"]) for r in recs}
        if len(stable)!=1:
            raise RuntimeError(f"SSE conflicting issuer rows for {code}: {stable}")
        out.append(sorted(recs,key=lambda r:(r["source_path"],r["source_sha256"]))[0])
    return sorted(out,key=lambda r:r["canonical_security_id"])

def build_szse()->list[dict[str,Any]]:
    files=sorted(ROOT.rglob("raw/szse/A_SHARE_LIST_FULL.xlsx"))
    if len(files)!=1:
        raise RuntimeError(f"Expected exactly one SZSE A-share workbook, got {len(files)}")
    p=files[0]; b=p.read_bytes(); fsha=sha_bytes(b)
    df=pd.read_excel(io.BytesIO(b),dtype=str).fillna("")
    required={"板块","公司全称","A股代码","A股简称","A股上市日期"}
    missing=required-set(df.columns)
    if missing: raise RuntimeError(f"SZSE workbook missing columns: {sorted(missing)}")
    out=[]
    for _,r in df.iterrows():
        board=str(r["板块"]).strip()
        code=str(r["A股代码"]).strip()
        ld=dt(r["A股上市日期"])
        if board not in {"主板","创业板"} or not CODE_RE.fullmatch(code):
            continue
        if pd.isna(ld) or pd.Timestamp(ld).tz_localize(None) > PIT:
            continue
        name=str(r["公司全称"]).strip()
        if not name: raise RuntimeError(f"SZSE issuer legal name missing for {code}")
        out.append({
          "pit_date":"2026-09-17",
          "canonical_security_id":f"SZSE:{code}",
          "exchange":"SZSE",
          "security_code":code,
          "official_issuer_query_key":code,
          "official_issuer_query_key_type":"SZSE_A_STOCK_CODE",
          "issuer_legal_name":name,
          "security_short_name":str(r["A股简称"]).strip(),
          "official_list_date":pd.Timestamp(ld).date().isoformat(),
          "official_board_code":board,
          "source_path":str(p.relative_to(ROOT)),
          "source_sha256":fsha,
        })
    return sorted(out,key=lambda r:r["canonical_security_id"])

def main():
    sse=build_sse(); sz=build_szse(); rows=sorted(sse+sz,key=lambda r:r["canonical_security_id"])
    ids=[r["canonical_security_id"] for r in rows]
    if len(sse)!=EXPECTED_SSE: raise RuntimeError(f"SSE count {len(sse)} != {EXPECTED_SSE}")
    if len(sz)!=EXPECTED_SZSE: raise RuntimeError(f"SZSE count {len(sz)} != {EXPECTED_SZSE}")
    if len(rows)!=EXPECTED_COUNT or len(set(ids))!=EXPECTED_COUNT:
        raise RuntimeError("Security map count/uniqueness failure")
    set_hash=sha_bytes(("\n".join(ids)+"\n").encode())
    if set_hash!=EXPECTED_SET_HASH:
        raise RuntimeError(f"Mother Pool hash mismatch: {set_hash}")

    # Query keys must be unique inside each exchange; issuer names are descriptive only.
    qkeys=[(r["exchange"],r["official_issuer_query_key"]) for r in rows]
    if len(set(qkeys))!=len(qkeys):
        raise RuntimeError("Duplicate official issuer query key within exchange")

    fields=[
      "pit_date","canonical_security_id","exchange","security_code",
      "official_issuer_query_key","official_issuer_query_key_type",
      "issuer_legal_name","security_short_name","official_list_date",
      "official_board_code","source_path","source_sha256"
    ]
    csv_path=OUT/"V2.7.27_SECURITY_ISSUER_PIT_MAP.csv"
    with csv_path.open("w",encoding="utf-8",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,lineterminator="\n")
        w.writeheader(); w.writerows(rows)
    map_bytes=csv_path.read_bytes()

    legal_names=[r["issuer_legal_name"] for r in rows]
    duplicate_legal_names=sorted({x for x in legal_names if legal_names.count(x)>1})
    receipt={
      "schema":"AI_CORE_EVID_V2_7_27_SECURITY_ISSUER_PIT_MAP_RECEIPT_V1",
      "pit_date":"2026-09-17",
      "source_artifact":{
        "workflow_run_id":35317123694,
        "artifact_id":10534869343,
        "artifact_sha256":"ef8632ba57ee2337d06712ce7e7d7de55ee383aca27f73cba9a7fbae1ceee65a"
      },
      "mother_pool":{
        "count":len(rows),
        "sse_count":len(sse),
        "szse_count":len(sz),
        "canonical_sorted_newline_sha256":set_hash,
        "expected_sha256":EXPECTED_SET_HASH,
        "exact_match":set_hash==EXPECTED_SET_HASH
      },
      "issuer_mapping":{
        "row_count":len(rows),
        "unique_security_ids":len(set(ids)),
        "unique_exchange_query_keys":len(set(qkeys)),
        "missing_query_keys":0,
        "missing_legal_names":0,
        "duplicate_legal_name_count":len(duplicate_legal_names),
        "duplicate_legal_names":duplicate_legal_names,
        "identity_rule":"Official exchange query key is authoritative; legal name is descriptive and never used for fuzzy identity matching."
      },
      "output":{
        "map_file":"evidence/V2.7.27_SECURITY_ISSUER_PIT_MAP.csv",
        "map_sha256":sha_bytes(map_bytes)
      },
      "gate":{
        "status":"EXACT_PASS",
        "next_stage":"OFFICIAL_LATEST_PRIMARY_CATALOG_INVENTORY"
      }
    }
    canonical=json.dumps(receipt,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()
    receipt["receipt_sha256"]=sha_bytes(canonical)
    (OUT/"V2.7.27_SECURITY_ISSUER_PIT_MAP_RECEIPT.json").write_text(
      json.dumps(receipt,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(receipt,ensure_ascii=False,indent=2))

if __name__=="__main__":
    main()
