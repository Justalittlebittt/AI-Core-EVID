from __future__ import annotations

import argparse, csv, hashlib, json, math, time
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import requests
from akshare.utils import demjson

SAMPLE=Path("evidence/V2.8.7_FOLD2_SETUP_SHAPE_MANIFEST.csv")
SAMPLE_SHA="79b6a4c752a22a16f6ec7167dfb1e6b007473229d7ec6729fb03a15b3ba0fa9a"
PROBE=Path("evidence/V2.8.6_TENCENT_DIRECT_TRANSPORT_PROBE_RECEIPT.json")
START="2022-09-01"; END="2024-12-31"
SHARD_COUNT=16
MAX_OBJECT_BYTES=95_000_000
URL="https://proxy.finance.qq.com/ifzqgtimg/appstock/app/newfqkline/get"

def sha_file(path:Path)->str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""): h.update(b)
    return h.hexdigest()

def stable_sha(obj)->str:
    return hashlib.sha256(json.dumps(obj,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()

def shard(cid:str)->int:
    return int(hashlib.sha256(cid.encode()).hexdigest()[:8],16)%SHARD_COUNT

def load_sample()->list[dict]:
    if sha_file(SAMPLE)!=SAMPLE_SHA: raise RuntimeError("FOLD1_MANIFEST_SHA_MISMATCH")
    rows=list(csv.DictReader(SAMPLE.read_text(encoding="utf-8").splitlines()))
    if len(rows)!=1048: raise RuntimeError(f"FOLD1_COUNT_MISMATCH:{len(rows)}")
    if any(str(r.get("identity_fold_mod5"))!="2" for r in rows): raise RuntimeError("FOLD1_IDENTITY_DRIFT")
    return sorted(rows,key=lambda x:x["canonical_security_id"])

def runtime_guard():
    p=json.loads(PROBE.read_text(encoding="utf-8"))
    if p.get("status")!="PASS" or any(not q.get("exact_match") for q in p.get("queries",[])):
        raise RuntimeError("TENCENT_DIRECT_TRANSPORT_PROBE_NOT_PASS")

def source_symbol(r:dict)->str:
    if r["exchange"]=="SSE": return "sh"+r["security_code"]
    if r["exchange"]=="SZSE": return "sz"+r["security_code"]
    raise RuntimeError(f"UNSUPPORTED_EXCHANGE:{r['exchange']}")

def fetch(symbol:str)->list[list]:
    last=""
    delays=[0,1,2,4,8,12]
    for attempt,delay in enumerate(delays):
        if delay: time.sleep(delay)
        try:
            params={
                "_var":"kline_dayhfq_direct",
                "param":f"{symbol},day,{START},{END},640,hfq",
                "r":"0.8205512681390605"
            }
            r=requests.get(URL,params=params,timeout=20)
            r.raise_for_status()
            pos=r.text.find("={")
            if pos<0: raise RuntimeError("RESPONSE_PREFIX_MISSING")
            data=demjson.decode(r.text[pos+1:])["data"][symbol]
            raw=data.get("hfqday") or data.get("day") or data.get("qfqday")
            if raw is None: raise RuntimeError("RESPONSE_DATA_KEY_MISSING")
            return raw
        except Exception as e:
            last=f"{type(e).__name__}:{e}"
    raise RuntimeError(f"PERSISTENT_TENCENT_DIRECT_QUERY_ERROR:{symbol}:{last}")

def normalize(meta:dict,raw:list[list])->tuple[list[dict],dict]:
    symbol=source_symbol(meta)
    def empty(status,reason=""):
        return [],{
            "status":status,"rows":0,"min_date":"","max_date":"",
            "rows_sha256":stable_sha([]),"source_invalid_reason":reason
        }
    if not raw:
        return empty("ZERO_ROWS")
    rows=[]
    seen=set()
    for z in raw:
        try:
            if len(z)<6:
                return empty("SOURCE_INVALID_ZERO_ROWS",f"SHORT_ROW:{z}")
            d=str(z[0])
            if not (START<=d<=END):
                continue
            if d in seen:
                return empty("SOURCE_INVALID_ZERO_ROWS",f"DATE_DUPLICATE:{d}")
            seen.add(d)
            vals={k:float(v) for k,v in zip(("open","close","high","low","volume"),z[1:6])}
            if not symbol.startswith(("sh688","sz399","sh000","sz000")):
                vals["volume"]*=100
            if any(not math.isfinite(vals[k]) for k in vals):
                return empty("SOURCE_INVALID_ZERO_ROWS",f"NONFINITE:{d}")
            if any(vals[k]<=0 for k in ("open","close","high","low")):
                return empty("SOURCE_INVALID_ZERO_ROWS",f"NONPOSITIVE_OHLC:{d}")
            if vals["high"]<max(vals["open"],vals["close"],vals["low"]) or vals["low"]>min(vals["open"],vals["close"],vals["high"]):
                return empty("SOURCE_INVALID_ZERO_ROWS",f"OHLC_ORDER:{d}")
            if vals["volume"]<0:
                return empty("SOURCE_INVALID_ZERO_ROWS",f"NEGATIVE_VOLUME:{d}")
        except Exception as e:
            return empty("SOURCE_INVALID_ZERO_ROWS",f"ROW_PARSE:{d if 'd' in locals() else 'UNKNOWN'}:{type(e).__name__}:{e}")
        rows.append({
            "canonical_security_id":meta["canonical_security_id"],
            "exchange":meta["exchange"],"security_code":meta["security_code"],
            "source_symbol":symbol,"acquisition_shard_mod16":shard(meta["canonical_security_id"]),
            "date":d,"open":vals["open"],"high":vals["high"],"low":vals["low"],"close":vals["close"],
            "volume":vals["volume"],"tradestatus":"1","source_adjustment":"hfq"
        })
    rows.sort(key=lambda r:r["date"])
    if not rows:
        return empty("ZERO_ROWS")
    dates=[r["date"] for r in rows]
    return rows,{
        "status":"SUCCESS","rows":len(rows),"min_date":dates[0],"max_date":dates[-1],
        "rows_sha256":stable_sha(rows),"source_invalid_reason":""
    }

def write_parquet(path:Path,rows:list[dict]):
    cols=["canonical_security_id","exchange","security_code","source_symbol","acquisition_shard_mod16",
          "date","open","high","low","close","volume","tradestatus","source_adjustment"]
    table=pa.table({c:[r.get(c) for r in rows] for c in cols})
    pq.write_table(table,path,compression="zstd",compression_level=9,use_dictionary=True,write_statistics=True,version="2.6")
    if path.stat().st_size>=MAX_OBJECT_BYTES: raise RuntimeError(f"PARQUET_TOO_LARGE:{path}:{path.stat().st_size}")

def run(shard_id:int,out:Path):
    runtime_guard()
    sample=[r for r in load_sample() if shard(r["canonical_security_id"])==shard_id]
    if not sample: raise RuntimeError(f"EMPTY_SHARD:{shard_id}")
    out.mkdir(parents=True,exist_ok=True)
    all_rows=[]; manifest=[]
    for i,meta in enumerate(sample,1):
        sym=source_symbol(meta)
        raw=fetch(sym); rows,rec=normalize(meta,raw); all_rows.extend(rows)
        manifest.append({"canonical_security_id":meta["canonical_security_id"],"source_symbol":sym,
                         "acquisition_shard_mod16":shard_id,**rec})
        if i%20==0 or i==len(sample):
            print(json.dumps({"shard":shard_id,"progress":i,"total":len(sample)},ensure_ascii=False),flush=True)
        time.sleep(0.08)
    all_rows.sort(key=lambda r:(r["canonical_security_id"],r["date"]))
    pp=out/f"V2.8.7_FOLD2_TENCENT_STOCKS_SHARD_{shard_id}.parquet"; write_parquet(pp,all_rows)
    mp=out/f"V2.8.7_FOLD2_TENCENT_QUERY_MANIFEST_SHARD_{shard_id}.csv"
    fields=["canonical_security_id","source_symbol","acquisition_shard_mod16","status","rows","min_date","max_date","rows_sha256","source_invalid_reason"]
    with mp.open("w",encoding="utf-8",newline="") as fh:
        w=csv.DictWriter(fh,fieldnames=fields,lineterminator="\n"); w.writeheader(); w.writerows(manifest)
    zero=[r["canonical_security_id"] for r in manifest if r["status"]=="ZERO_ROWS"]
    invalid=[r["canonical_security_id"] for r in manifest if r["status"]=="SOURCE_INVALID_ZERO_ROWS"]
    invalid_detail=[{"canonical_security_id":r["canonical_security_id"],"reason":r["source_invalid_reason"]} for r in manifest if r["status"]=="SOURCE_INVALID_ZERO_ROWS"]
    receipt={
      "schema":"AI_CORE_EVID_V2_8_7_FOLD2_TENCENT_DIRECT_SHARD_RECEIPT_V1","version":"V2.8.7","status":"PASS",
      "shard":shard_id,"shard_count":SHARD_COUNT,
      "upstream":"Tencent Securities","transport":"direct newfqkline/get","adjust":"hfq","count_limit":640,
      "retrieval_start":START,"retrieval_end":END,"sample_manifest_sha256":SAMPLE_SHA,
      "shard_sample_count":len(sample),"successful_nonzero_symbols":sum(r["status"]=="SUCCESS" for r in manifest),
      "zero_row_symbols":len(zero),"zero_row_canonical_ids":zero,
      "source_invalid_symbols":len(invalid),"source_invalid_canonical_ids":invalid,"source_invalid_details":invalid_detail,
      "stock_rows":len(all_rows),
      "parquet_file":pp.name,"parquet_bytes":pp.stat().st_size,"parquet_sha256":sha_file(pp),
      "query_manifest_file":mp.name,"query_manifest_sha256":sha_file(mp),
      "factor_or_forward_return_computed":False,"mechanism_statistics_computed":False,
      "sample_replacement_used":False,"fold3_4_consumed":False
    }
    receipt["receipt_sha256"]=stable_sha(receipt)
    rp=out/f"V2.8.7_FOLD2_TENCENT_SHARD_{shard_id}_RECEIPT.json"
    rp.write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(receipt,ensure_ascii=False,indent=2))

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--shard",type=int,choices=range(16),required=True); ap.add_argument("--out",required=True)
    a=ap.parse_args(); run(a.shard,Path(a.out))
if __name__=="__main__": main()
