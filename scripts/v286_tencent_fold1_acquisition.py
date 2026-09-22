from __future__ import annotations

import argparse, csv, hashlib, importlib.metadata, json, math, time
from pathlib import Path

import akshare as ak
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

SAMPLE=Path("evidence/V2.8.6_FOLD1_MECHANISM_REPLICATION_MANIFEST.csv")
SAMPLE_SHA="fe15777a0a3a131b58288454a0e3023503bd80ac6a22f20a2e50c45a4deed38a"
PROBE=Path("evidence/V2.8.6_AKSHARE_TENCENT_SOURCE_PROBE_RECEIPT.json")
START="20220901"; END="20241231"
START_ISO="2022-09-01"; END_ISO="2024-12-31"
AK_VERSION="1.18.97"
SHARD_COUNT=16
MAX_OBJECT_BYTES=95_000_000

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
    if len(rows)!=1058: raise RuntimeError(f"FOLD1_COUNT_MISMATCH:{len(rows)}")
    if any(str(r.get("identity_fold_mod5"))!="1" for r in rows): raise RuntimeError("FOLD1_IDENTITY_DRIFT")
    return sorted(rows,key=lambda x:x["canonical_security_id"])

def runtime_guard():
    if importlib.metadata.version("akshare")!=AK_VERSION: raise RuntimeError("AKSHARE_VERSION_MISMATCH")
    p=json.loads(PROBE.read_text(encoding="utf-8"))
    if p.get("status")!="PASS" or p.get("interface")!="stock_zh_a_hist_tx" or p.get("adjust")!="hfq":
        raise RuntimeError("AKSHARE_TENCENT_PROBE_NOT_PASS")

def source_symbol(r:dict)->str:
    if r["exchange"]=="SSE": return "sh"+r["security_code"]
    if r["exchange"]=="SZSE": return "sz"+r["security_code"]
    raise RuntimeError(f"UNSUPPORTED_EXCHANGE:{r['exchange']}")

def fetch(symbol:str)->pd.DataFrame:
    last=""
    for attempt,delay in enumerate([0,1,2,4,8]):
        if delay: time.sleep(delay)
        try:
            return ak.stock_zh_a_hist_tx(symbol=symbol,start_date=START,end_date=END,adjust="hfq")
        except Exception as e:
            last=f"{type(e).__name__}:{e}"
    raise RuntimeError(f"PERSISTENT_TENCENT_QUERY_ERROR:{symbol}:{last}")

def normalize(meta:dict,df:pd.DataFrame)->tuple[list[dict],dict]:
    symbol=source_symbol(meta)
    if df is None or df.empty:
        return [],{"status":"ZERO_ROWS","rows":0,"min_date":"","max_date":"","rows_sha256":stable_sha([])}
    x=df.copy(); x.columns=[str(c).lower() for c in x.columns]
    required={"date","open","close","high","low","volume"}
    if not required.issubset(set(x.columns)): raise RuntimeError(f"SCHEMA_MISMATCH:{symbol}:{list(x.columns)}")
    rows=[]
    for _,r in x.iterrows():
        d=pd.Timestamp(r["date"]).date().isoformat()
        vals={k:float(r[k]) for k in ("open","close","high","low","volume")}
        if any(not math.isfinite(vals[k]) for k in vals): raise RuntimeError(f"NONFINITE:{symbol}:{d}")
        if any(vals[k]<=0 for k in ("open","close","high","low")): raise RuntimeError(f"NONPOSITIVE_OHLC:{symbol}:{d}")
        if vals["high"]<max(vals["open"],vals["close"],vals["low"]) or vals["low"]>min(vals["open"],vals["close"],vals["high"]):
            raise RuntimeError(f"OHLC_ORDER:{symbol}:{d}")
        if vals["volume"]<0: raise RuntimeError(f"NEGATIVE_VOLUME:{symbol}:{d}")
        rows.append({
            "canonical_security_id":meta["canonical_security_id"],
            "exchange":meta["exchange"],"security_code":meta["security_code"],
            "source_symbol":symbol,"acquisition_shard_mod16":shard(meta["canonical_security_id"]),
            "date":d,"open":vals["open"],"high":vals["high"],"low":vals["low"],"close":vals["close"],
            "volume":vals["volume"],"tradestatus":"1","source_adjustment":"hfq"
        })
    dates=[r["date"] for r in rows]
    if dates!=sorted(dates) or len(dates)!=len(set(dates)): raise RuntimeError(f"DATE_ORDER_OR_DUPLICATE:{symbol}")
    if dates[0]<START_ISO or dates[-1]>END_ISO: raise RuntimeError(f"DATE_RANGE_DRIFT:{symbol}")
    return rows,{"status":"SUCCESS","rows":len(rows),"min_date":dates[0],"max_date":dates[-1],"rows_sha256":stable_sha(rows)}

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
        df=fetch(sym); rows,rec=normalize(meta,df); all_rows.extend(rows)
        manifest.append({"canonical_security_id":meta["canonical_security_id"],"source_symbol":sym,
                         "acquisition_shard_mod16":shard_id,**rec})
        if i%20==0 or i==len(sample):
            print(json.dumps({"shard":shard_id,"progress":i,"total":len(sample)},ensure_ascii=False),flush=True)
        time.sleep(0.12)
    all_rows.sort(key=lambda r:(r["canonical_security_id"],r["date"]))
    pp=out/f"V2.8.6_FOLD1_TENCENT_STOCKS_SHARD_{shard_id}.parquet"; write_parquet(pp,all_rows)
    mp=out/f"V2.8.6_FOLD1_TENCENT_QUERY_MANIFEST_SHARD_{shard_id}.csv"
    fields=["canonical_security_id","source_symbol","acquisition_shard_mod16","status","rows","min_date","max_date","rows_sha256"]
    with mp.open("w",encoding="utf-8",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,lineterminator="\n"); w.writeheader(); w.writerows(manifest)
    zero=[r["canonical_security_id"] for r in manifest if r["status"]=="ZERO_ROWS"]
    receipt={
      "schema":"AI_CORE_EVID_V2_8_6_FOLD1_TENCENT_SHARD_RECEIPT_V1","version":"V2.8.6","status":"PASS",
      "shard":shard_id,"shard_count":SHARD_COUNT,"akshare_version":AK_VERSION,
      "upstream":"Tencent Securities","interface":"stock_zh_a_hist_tx","adjust":"hfq",
      "retrieval_start":START_ISO,"retrieval_end":END_ISO,"sample_manifest_sha256":SAMPLE_SHA,
      "shard_sample_count":len(sample),"successful_nonzero_symbols":sum(r["status"]=="SUCCESS" for r in manifest),
      "zero_row_symbols":len(zero),"zero_row_canonical_ids":zero,"stock_rows":len(all_rows),
      "parquet_file":pp.name,"parquet_bytes":pp.stat().st_size,"parquet_sha256":sha_file(pp),
      "query_manifest_file":mp.name,"query_manifest_sha256":sha_file(mp),
      "factor_or_forward_return_computed":False,"mechanism_statistics_computed":False,
      "sample_replacement_used":False,"fold2_3_4_consumed":False
    }
    receipt["receipt_sha256"]=stable_sha(receipt)
    rp=out/f"V2.8.6_FOLD1_TENCENT_SHARD_{shard_id}_RECEIPT.json"
    rp.write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(receipt,ensure_ascii=False,indent=2))

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--shard",type=int,choices=range(16),required=True); ap.add_argument("--out",required=True)
    a=ap.parse_args(); run(a.shard,Path(a.out))
if __name__=="__main__": main()
