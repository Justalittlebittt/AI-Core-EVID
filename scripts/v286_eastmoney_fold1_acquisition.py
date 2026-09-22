from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.metadata
import json
import math
import time
from pathlib import Path

import akshare as ak
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

SAMPLE=Path("evidence/V2.8.6_FOLD1_MECHANISM_REPLICATION_MANIFEST.csv")
SAMPLE_SHA="fe15777a0a3a131b58288454a0e3023503bd80ac6a22f20a2e50c45a4deed38a"
PROBE=Path("evidence/V2.8.6_AKSHARE_EASTMONEY_SOURCE_PROBE_RECEIPT.json")
START="20220901"
END="20241231"
START_ISO="2022-09-01"
END_ISO="2024-12-31"
AK_VERSION="1.18.97"
SHARD_COUNT=16
MAX_OBJECT_BYTES=95_000_000
EXPECTED_COLUMNS=["日期","股票代码","开盘","收盘","最高","最低","成交量","成交额","振幅","涨跌幅","涨跌额","换手率"]

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
    if sha_file(SAMPLE)!=SAMPLE_SHA:
        raise RuntimeError("FOLD1_MANIFEST_SHA_MISMATCH")
    rows=list(csv.DictReader(SAMPLE.read_text(encoding="utf-8").splitlines()))
    if len(rows)!=1058:
        raise RuntimeError(f"FOLD1_COUNT_MISMATCH:{len(rows)}")
    if any(str(r.get("identity_fold_mod5"))!="1" for r in rows):
        raise RuntimeError("FOLD1_IDENTITY_DRIFT")
    return sorted(rows,key=lambda x:x["canonical_security_id"])

def runtime_guard():
    if importlib.metadata.version("akshare")!=AK_VERSION:
        raise RuntimeError("AKSHARE_VERSION_MISMATCH")
    p=json.loads(PROBE.read_text(encoding="utf-8"))
    if p.get("status")!="PASS":
        raise RuntimeError("AKSHARE_EASTMONEY_PROBE_NOT_PASS")

def fetch(symbol:str)->pd.DataFrame:
    last=""
    for attempt in range(4):
        try:
            df=ak.stock_zh_a_hist(
                symbol=symbol,period="daily",start_date=START,end_date=END,adjust="hfq",timeout=20
            )
            return df
        except Exception as e:
            last=f"{type(e).__name__}:{e}"
            if attempt<3:
                time.sleep(1.5*(attempt+1))
    raise RuntimeError(f"PERSISTENT_EASTMONEY_QUERY_ERROR:{symbol}:{last}")

def normalize(sample_row:dict,df:pd.DataFrame)->tuple[list[dict],dict]:
    symbol=sample_row["security_code"]
    if df is None or df.empty:
        return [],{"status":"ZERO_ROWS","rows":0,"min_date":"","max_date":"","rows_sha256":stable_sha([])}
    if list(df.columns)!=EXPECTED_COLUMNS:
        raise RuntimeError(f"SCHEMA_MISMATCH:{symbol}:{list(df.columns)}")
    rows=[]
    for _,r in df.iterrows():
        d=pd.Timestamp(r["日期"]).date().isoformat()
        code=str(r["股票代码"]).strip().split(".")[0].zfill(6)
        if code!=symbol:
            raise RuntimeError(f"SECURITY_CODE_DRIFT:{symbol}:{code}")
        vals={k:float(r[src]) for k,src in (
            ("open","开盘"),("close","收盘"),("high","最高"),("low","最低")
        )}
        if any(not math.isfinite(v) or v<=0 for v in vals.values()):
            raise RuntimeError(f"NONPOSITIVE_OHLC:{symbol}:{d}")
        if vals["high"]<max(vals["open"],vals["close"],vals["low"]) or vals["low"]>min(vals["open"],vals["close"],vals["high"]):
            raise RuntimeError(f"OHLC_ORDER:{symbol}:{d}")
        volume=float(r["成交量"]); amount=float(r["成交额"])
        if not (math.isfinite(volume) and math.isfinite(amount)) or volume<0 or amount<0:
            raise RuntimeError(f"VOLUME_AMOUNT_BLOCK:{symbol}:{d}")
        rows.append({
            "canonical_security_id":sample_row["canonical_security_id"],
            "exchange":sample_row["exchange"],
            "security_code":symbol,
            "source_symbol":symbol,
            "acquisition_shard_mod16":shard(sample_row["canonical_security_id"]),
            "date":d,
            "open":vals["open"],"high":vals["high"],"low":vals["low"],"close":vals["close"],
            "volume":volume,"amount":amount,
            "tradestatus":"1",
            "source_adjustment":"hfq",
        })
    dates=[r["date"] for r in rows]
    if dates!=sorted(dates) or len(dates)!=len(set(dates)):
        raise RuntimeError(f"DATE_ORDER_OR_DUPLICATE:{symbol}")
    if dates[0]<START_ISO or dates[-1]>END_ISO:
        raise RuntimeError(f"DATE_RANGE_DRIFT:{symbol}")
    return rows,{
        "status":"SUCCESS","rows":len(rows),"min_date":dates[0],"max_date":dates[-1],
        "rows_sha256":stable_sha(rows)
    }

def write_parquet(path:Path,rows:list[dict]):
    cols=[
        "canonical_security_id","exchange","security_code","source_symbol","acquisition_shard_mod16",
        "date","open","high","low","close","volume","amount","tradestatus","source_adjustment"
    ]
    table=pa.table({c:[r.get(c) for r in rows] for c in cols})
    pq.write_table(table,path,compression="zstd",compression_level=9,use_dictionary=True,write_statistics=True,version="2.6")
    if path.stat().st_size>=MAX_OBJECT_BYTES:
        raise RuntimeError(f"PARQUET_TOO_LARGE:{path}:{path.stat().st_size}")

def run(shard_id:int,out:Path):
    runtime_guard()
    sample=[r for r in load_sample() if shard(r["canonical_security_id"])==shard_id]
    if not sample:
        raise RuntimeError(f"EMPTY_SHARD:{shard_id}")
    out.mkdir(parents=True,exist_ok=True)
    all_rows=[]; manifest=[]
    for i,s in enumerate(sample,1):
        df=fetch(s["security_code"])
        rows,rec=normalize(s,df)
        all_rows.extend(rows)
        manifest.append({
            "canonical_security_id":s["canonical_security_id"],
            "security_code":s["security_code"],
            "acquisition_shard_mod16":shard_id,
            **rec
        })
        if i%20==0 or i==len(sample):
            print(json.dumps({"shard":shard_id,"progress":i,"total":len(sample)},ensure_ascii=False),flush=True)
        time.sleep(0.08)

    all_rows.sort(key=lambda r:(r["canonical_security_id"],r["date"]))
    pp=out/f"V2.8.6_FOLD1_EASTMONEY_STOCKS_SHARD_{shard_id}.parquet"
    write_parquet(pp,all_rows)
    mp=out/f"V2.8.6_FOLD1_EASTMONEY_QUERY_MANIFEST_SHARD_{shard_id}.csv"
    fields=["canonical_security_id","security_code","acquisition_shard_mod16","status","rows","min_date","max_date","rows_sha256"]
    with mp.open("w",encoding="utf-8",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,lineterminator="\n"); w.writeheader(); w.writerows(manifest)
    zero=[r["canonical_security_id"] for r in manifest if r["status"]=="ZERO_ROWS"]
    receipt={
        "schema":"AI_CORE_EVID_V2_8_6_FOLD1_EASTMONEY_SHARD_RECEIPT_V1",
        "version":"V2.8.6","status":"PASS","shard":shard_id,"shard_count":SHARD_COUNT,
        "akshare_version":AK_VERSION,"upstream":"Eastmoney","interface":"stock_zh_a_hist",
        "period":"daily","adjust":"hfq","retrieval_start":START_ISO,"retrieval_end":END_ISO,
        "sample_manifest_sha256":SAMPLE_SHA,"shard_sample_count":len(sample),
        "successful_nonzero_symbols":sum(r["status"]=="SUCCESS" for r in manifest),
        "zero_row_symbols":len(zero),"zero_row_canonical_ids":zero,
        "stock_rows":len(all_rows),
        "parquet_file":pp.name,"parquet_bytes":pp.stat().st_size,"parquet_sha256":sha_file(pp),
        "query_manifest_file":mp.name,"query_manifest_sha256":sha_file(mp),
        "factor_or_forward_return_computed":False,"mechanism_statistics_computed":False,
        "sample_replacement_used":False,"fold2_3_4_consumed":False
    }
    receipt["receipt_sha256"]=stable_sha(receipt)
    rp=out/f"V2.8.6_FOLD1_EASTMONEY_SHARD_{shard_id}_RECEIPT.json"
    rp.write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(receipt,ensure_ascii=False,indent=2))

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--shard",type=int,choices=range(16),required=True); ap.add_argument("--out",required=True)
    a=ap.parse_args(); run(a.shard,Path(a.out))

if __name__=="__main__": main()
