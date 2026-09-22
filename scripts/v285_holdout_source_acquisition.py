from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.metadata
import json
import math
import time
from pathlib import Path

import baostock as bs
import pyarrow as pa
import pyarrow.parquet as pq

SAMPLE=Path("evidence/V2.8.5_BACKWARD_HOLDOUT_SAMPLE_MANIFEST.csv")
SAMPLE_SHA="199864ece6c02f3257647d59ba63fe261a7b478a2525b7ed8042bbf475a9fe48"
PROBE=Path("evidence/V2.8.5_BAOSTOCK_SOURCE_PROBE_RECEIPT.json")
START="2022-09-01"
END="2024-12-31"
FIELDS=["date","code","open","high","low","close","preclose","volume","amount","adjustflag","tradestatus"]
OUT=Path("v285_holdout_source")
MAX_GIT_OBJECT_BYTES=95_000_000

def sha_file(path:Path)->str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""):
            h.update(b)
    return h.hexdigest()

def stable_sha(obj)->str:
    return hashlib.sha256(
        json.dumps(obj,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()
    ).hexdigest()

def bucket(cid:str)->int:
    return int(hashlib.sha256(cid.encode()).hexdigest()[:8],16)%8

def load_sample()->list[dict]:
    if sha_file(SAMPLE)!=SAMPLE_SHA:
        raise RuntimeError("SAMPLE_MANIFEST_SHA_MISMATCH")
    rows=list(csv.DictReader(SAMPLE.read_text(encoding="utf-8").splitlines()))
    if len(rows)!=1031:
        raise RuntimeError(f"SAMPLE_COUNT_MISMATCH:{len(rows)}")
    ids=[r["canonical_security_id"] for r in rows]
    if len(ids)!=len(set(ids)):
        raise RuntimeError("SAMPLE_DUPLICATE_ID")
    return sorted(rows,key=lambda x:x["canonical_security_id"])

def query_once(code:str,adjustflag:str):
    return bs.query_history_k_data_plus(
        code,
        ",".join(FIELDS),
        start_date=START,
        end_date=END,
        frequency="d",
        adjustflag=adjustflag,
    )

def fetch(code:str,adjustflag:str)->list[dict]:
    last=None
    for attempt in range(3):
        rs=query_once(code,adjustflag)
        if rs.error_code=="0":
            if list(rs.fields)!=FIELDS:
                raise RuntimeError(f"SCHEMA_MISMATCH:{code}")
            rows=[]
            while rs.next():
                rows.append(dict(zip(FIELDS,rs.get_row_data())))
            return rows
        last=f"{rs.error_code}:{rs.error_msg}"
        if attempt<2:
            time.sleep(0.5*(attempt+1))
    raise RuntimeError(f"PERSISTENT_QUERY_ERROR:{code}:{last}")

def validate_rows(code:str,rows:list[dict],expected_adjustflag:str):
    if not rows:
        return {"status":"ZERO_ROWS","rows":0,"trading_rows":0,"min_date":"","max_date":"","rows_sha256":stable_sha([])}
    dates=[]
    trading=0
    for r in rows:
        if r["code"]!=code:
            raise RuntimeError(f"CODE_DRIFT:{code}")
        if r["adjustflag"]!=expected_adjustflag:
            raise RuntimeError(f"ADJUSTFLAG_DRIFT:{code}:{r['adjustflag']}")
        if r["tradestatus"] not in {"0","1"}:
            raise RuntimeError(f"TRADESTATUS_DOMAIN:{code}:{r['tradestatus']}")
        if not (START<=r["date"]<=END):
            raise RuntimeError(f"DATE_RANGE_DRIFT:{code}:{r['date']}")
        dates.append(r["date"])
        if r["tradestatus"]=="1":
            trading+=1
            vals={}
            for k in ("open","high","low","close"):
                try:
                    v=float(r[k])
                except Exception as e:
                    raise RuntimeError(f"NONNUMERIC_TRADING_OHLC:{code}:{r['date']}:{k}") from e
                if not math.isfinite(v) or v<=0:
                    raise RuntimeError(f"NONPOSITIVE_TRADING_OHLC:{code}:{r['date']}:{k}")
                vals[k]=v
            if vals["high"]<max(vals["open"],vals["low"],vals["close"]):
                raise RuntimeError(f"OHLC_ORDER:{code}:{r['date']}")
            if vals["low"]>min(vals["open"],vals["high"],vals["close"]):
                raise RuntimeError(f"OHLC_ORDER:{code}:{r['date']}")
    if dates!=sorted(dates) or len(dates)!=len(set(dates)):
        raise RuntimeError(f"DATE_ORDER_OR_DUPLICATE:{code}")
    return {
        "status":"SUCCESS",
        "rows":len(rows),
        "trading_rows":trading,
        "min_date":dates[0],
        "max_date":dates[-1],
        "rows_sha256":stable_sha(rows),
    }

def enriched_rows(sample_row:dict,raw:list[dict])->list[dict]:
    cid=sample_row["canonical_security_id"]
    b=bucket(cid)
    out=[]
    for r in raw:
        out.append({
            "canonical_security_id":cid,
            "exchange":sample_row["exchange"],
            "security_code":sample_row["security_code"],
            "baostock_code":sample_row["baostock_code"],
            "sample_bucket":b,
            **r,
        })
    return out

def write_parquet(path:Path,rows:list[dict]):
    path.parent.mkdir(parents=True,exist_ok=True)
    cols=[
        "canonical_security_id","exchange","security_code","baostock_code","sample_bucket",
        *FIELDS
    ]
    data={c:[r.get(c,"") for r in rows] for c in cols}
    table=pa.table(data)
    pq.write_table(
        table,path,
        compression="zstd",
        compression_level=9,
        use_dictionary=True,
        write_statistics=True,
        version="2.6",
    )
    if path.stat().st_size>=MAX_GIT_OBJECT_BYTES:
        raise RuntimeError(f"PARQUET_PARTITION_TOO_LARGE:{path}:{path.stat().st_size}")

def run(out:Path):
    if json.loads(PROBE.read_text(encoding="utf-8")).get("status")!="PASS":
        raise RuntimeError("SOURCE_PROBE_NOT_PASS")
    if importlib.metadata.version("baostock")!="0.9.4":
        raise RuntimeError("BAOSTOCK_VERSION_MISMATCH")
    pav=importlib.metadata.version("pyarrow")
    if pav!="21.0.0":
        raise RuntimeError(f"PYARROW_VERSION_MISMATCH:{pav}")

    sample=load_sample()
    out.mkdir(parents=True,exist_ok=True)
    lg=bs.login()
    if lg.error_code!="0":
        raise RuntimeError(f"BAOSTOCK_LOGIN_ERROR:{lg.error_code}:{lg.error_msg}")

    partitions={i:[] for i in range(8)}
    manifest=[]
    try:
        for i,s in enumerate(sample,1):
            code=s["baostock_code"]
            raw=fetch(code,"1")
            rec=validate_rows(code,raw,"1")
            manifest.append({
                "canonical_security_id":s["canonical_security_id"],
                "baostock_code":code,
                "sample_bucket":bucket(s["canonical_security_id"]),
                **rec,
            })
            if raw:
                partitions[bucket(s["canonical_security_id"])].extend(enriched_rows(s,raw))
            if i%100==0 or i==len(sample):
                print(json.dumps({"progress_symbols":i,"total_symbols":len(sample)},ensure_ascii=False),flush=True)

        bench_raw=fetch("sh.000300","3")
        bench_rec=validate_rows("sh.000300",bench_raw,"3")
        if bench_rec["status"]!="SUCCESS":
            raise RuntimeError("BENCHMARK_ZERO_ROWS_BLOCKED")
    finally:
        bs.logout()

    part_meta=[]
    stock_row_count=0
    trading_row_count=0
    for b in range(8):
        rows=sorted(partitions[b],key=lambda r:(r["canonical_security_id"],r["date"]))
        p=out/f"V2.8.5_BAOSTOCK_STOCKS_BUCKET_{b}.parquet"
        write_parquet(p,rows)
        stock_row_count+=len(rows)
        trading_row_count+=sum(r["tradestatus"]=="1" for r in rows)
        part_meta.append({
            "bucket":b,"file":p.name,"rows":len(rows),"bytes":p.stat().st_size,"sha256":sha_file(p)
        })

    bench_rows=[{
        "canonical_security_id":"BENCHMARK:CSI300",
        "exchange":"SSE_INDEX",
        "security_code":"000300",
        "baostock_code":"sh.000300",
        "sample_bucket":-1,
        **r,
    } for r in bench_raw]
    bench_path=out/"V2.8.5_BAOSTOCK_CSI300.parquet"
    write_parquet(bench_path,bench_rows)

    manifest_path=out/"V2.8.5_BAOSTOCK_QUERY_MANIFEST.csv"
    fields=["canonical_security_id","baostock_code","sample_bucket","status","rows","trading_rows","min_date","max_date","rows_sha256"]
    with manifest_path.open("w",encoding="utf-8",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,lineterminator="\n")
        w.writeheader(); w.writerows(manifest)

    zero=[r["canonical_security_id"] for r in manifest if r["status"]=="ZERO_ROWS"]
    receipt={
        "schema":"AI_CORE_EVID_V2_8_5_BAOSTOCK_HOLDOUT_SOURCE_SNAPSHOT_RECEIPT_V1",
        "version":"V2.8.5",
        "status":"PASS",
        "provider":"BaoStock",
        "baostock_version":"0.9.4",
        "pyarrow_version":pav,
        "retrieval_start":START,
        "retrieval_end":END,
        "sample_manifest_sha256":SAMPLE_SHA,
        "sample_count":len(sample),
        "successful_nonzero_symbols":sum(r["status"]=="SUCCESS" for r in manifest),
        "zero_row_symbols":len(zero),
        "zero_row_canonical_ids":zero,
        "persistent_query_errors":0,
        "stock_rows":stock_row_count,
        "stock_trading_rows":trading_row_count,
        "stock_partitions":part_meta,
        "benchmark":{
            **bench_rec,
            "file":bench_path.name,
            "bytes":bench_path.stat().st_size,
            "parquet_sha256":sha_file(bench_path),
        },
        "query_manifest_file":manifest_path.name,
        "query_manifest_sha256":sha_file(manifest_path),
        "factor_or_forward_return_computed":False,
        "holdout_outcome_inspected":False,
        "sample_replacement_used":False,
    }
    receipt["receipt_sha256"]=stable_sha(receipt)
    rp=out/"V2.8.5_BAOSTOCK_HOLDOUT_SOURCE_SNAPSHOT_RECEIPT.json"
    rp.write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(receipt,ensure_ascii=False,indent=2))

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--out",default=str(OUT))
    a=ap.parse_args()
    run(Path(a.out))

if __name__=="__main__":
    main()
