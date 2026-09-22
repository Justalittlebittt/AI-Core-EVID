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

SAMPLE=Path("evidence/V2.8.6_FOLD1_MECHANISM_REPLICATION_MANIFEST.csv")
SAMPLE_SHA="fe15777a0a3a131b58288454a0e3023503bd80ac6a22f20a2e50c45a4deed38a"
PROBE=Path("evidence/V2.8.5_BAOSTOCK_SOURCE_PROBE_RECEIPT.json")
START="2022-09-01"
END="2024-12-31"
FIELDS=["date","code","open","high","low","close","preclose","volume","amount","adjustflag","tradestatus"]
PRICE_KEYS=("open","high","low","close","preclose")
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
    if len(rows)!=1058:
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

def numeric_equal(a:str,b:str)->bool:
    try:
        x=float(a); y=float(b)
    except Exception:
        return a==b
    if not (math.isfinite(x) and math.isfinite(y)):
        return False
    return abs(x-y)<=1e-12*max(1.0,abs(x),abs(y))

def validate_common(code:str,rows:list[dict])->dict:
    if not rows:
        return {"status":"ZERO_ROWS","rows":0,"trading_rows":0,"min_date":"","max_date":"","rows_sha256":stable_sha([])}
    dates=[]; trading=0
    for r in rows:
        if r["code"]!=code:
            raise RuntimeError(f"CODE_DRIFT:{code}")
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
        "status":"SUCCESS","rows":len(rows),"trading_rows":trading,
        "min_date":dates[0],"max_date":dates[-1],"rows_sha256":stable_sha(rows),
    }

def validate_unadjusted(code:str,rows:list[dict])->dict:
    rec=validate_common(code,rows)
    if rows and {r["adjustflag"] for r in rows}!={"3"}:
        raise RuntimeError(f"UNADJUSTED_ROWFLAG_DRIFT:{code}:{sorted({r['adjustflag'] for r in rows})}")
    return rec

def validate_post_adjusted(code:str,rows:list[dict])->dict:
    rec=validate_common(code,rows)
    if not rows:
        return {**rec,"returned_adjustflags":"","flag3_rows":0,"flag3_crosschecked_rows":0}
    flags={r["adjustflag"] for r in rows}
    if not flags.issubset({"1","3"}):
        raise RuntimeError(f"POST_ADJUST_ROWFLAG_BLOCK:{code}:{sorted(flags)}")
    flag3=[r for r in rows if r["adjustflag"]=="3"]
    checked=0
    if flag3:
        raw=fetch(code,"3")
        validate_unadjusted(code,raw)
        by_date={r["date"]:r for r in raw}
        for r in flag3:
            q=by_date.get(r["date"])
            if q is None:
                raise RuntimeError(f"FLAG3_RAW_DATE_MISSING:{code}:{r['date']}")
            for k in PRICE_KEYS:
                if not numeric_equal(r[k],q[k]):
                    raise RuntimeError(f"FLAG3_RAW_PRICE_MISMATCH:{code}:{r['date']}:{k}")
            checked+=1
    return {
        **rec,
        "returned_adjustflags":"|".join(sorted(flags)),
        "flag3_rows":len(flag3),
        "flag3_crosschecked_rows":checked,
    }

def enriched_rows(sample_row:dict,raw:list[dict])->list[dict]:
    cid=sample_row["canonical_security_id"]
    b=bucket(cid)
    return [{
        "canonical_security_id":cid,
        "exchange":sample_row["exchange"],
        "security_code":sample_row["security_code"],
        "baostock_code":sample_row["baostock_code"],
        "sample_bucket":b,
        **r,
    } for r in raw]

def write_parquet(path:Path,rows:list[dict]):
    path.parent.mkdir(parents=True,exist_ok=True)
    cols=["canonical_security_id","exchange","security_code","baostock_code","sample_bucket",*FIELDS]
    data={c:[r.get(c,"") for r in rows] for c in cols}
    table=pa.table(data)
    pq.write_table(table,path,compression="zstd",compression_level=9,use_dictionary=True,write_statistics=True,version="2.6")
    if path.stat().st_size>=MAX_GIT_OBJECT_BYTES:
        raise RuntimeError(f"PARQUET_PARTITION_TOO_LARGE:{path}:{path.stat().st_size}")

def runtime_guard():
    if json.loads(PROBE.read_text(encoding="utf-8")).get("status")!="PASS":
        raise RuntimeError("SOURCE_PROBE_NOT_PASS")
    if importlib.metadata.version("baostock")!="0.9.4":
        raise RuntimeError("BAOSTOCK_VERSION_MISMATCH")
    pav=importlib.metadata.version("pyarrow")
    if pav!="21.0.0":
        raise RuntimeError(f"PYARROW_VERSION_MISMATCH:{pav}")
    return pav

def run_bucket(bucket_id:int,out:Path):
    pav=runtime_guard()
    sample=[r for r in load_sample() if bucket(r["canonical_security_id"])==bucket_id]
    if not sample:
        raise RuntimeError(f"EMPTY_BUCKET:{bucket_id}")
    out.mkdir(parents=True,exist_ok=True)
    lg=bs.login()
    if lg.error_code!="0":
        raise RuntimeError(f"BAOSTOCK_LOGIN_ERROR:{lg.error_code}:{lg.error_msg}")
    all_rows=[]; manifest=[]
    try:
        for i,s in enumerate(sample,1):
            code=s["baostock_code"]
            raw=fetch(code,"1")
            rec=validate_post_adjusted(code,raw)
            manifest.append({
                "canonical_security_id":s["canonical_security_id"],
                "baostock_code":code,
                "sample_bucket":bucket_id,
                **rec,
            })
            if raw:
                all_rows.extend(enriched_rows(s,raw))
            if i%50==0 or i==len(sample):
                print(json.dumps({"bucket":bucket_id,"progress_symbols":i,"bucket_total":len(sample)},ensure_ascii=False),flush=True)
    finally:
        bs.logout()

    all_rows.sort(key=lambda r:(r["canonical_security_id"],r["date"]))
    pp=out/f"V2.8.6_FOLD1_BAOSTOCK_STOCKS_BUCKET_{bucket_id}.parquet"
    write_parquet(pp,all_rows)
    mp=out/f"V2.8.6_FOLD1_BAOSTOCK_QUERY_MANIFEST_BUCKET_{bucket_id}.csv"
    fields=[
        "canonical_security_id","baostock_code","sample_bucket","status","rows","trading_rows",
        "min_date","max_date","rows_sha256","returned_adjustflags","flag3_rows","flag3_crosschecked_rows"
    ]
    with mp.open("w",encoding="utf-8",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,lineterminator="\n")
        w.writeheader(); w.writerows(manifest)
    zero=[r["canonical_security_id"] for r in manifest if r["status"]=="ZERO_ROWS"]
    receipt={
        "schema":"AI_CORE_EVID_V2_8_6_FOLD1_BAOSTOCK_BUCKET_RECEIPT_V1",
        "version":"V2.8.6","status":"PASS","bucket":bucket_id,
        "baostock_version":"0.9.4","pyarrow_version":pav,
        "retrieval_start":START,"retrieval_end":END,
        "sample_manifest_sha256":SAMPLE_SHA,
        "bucket_sample_count":len(sample),
        "successful_nonzero_symbols":sum(r["status"]=="SUCCESS" for r in manifest),
        "zero_row_symbols":len(zero),"zero_row_canonical_ids":zero,
        "flag3_rows_total":sum(int(r.get("flag3_rows") or 0) for r in manifest),
        "flag3_crosschecked_rows_total":sum(int(r.get("flag3_crosschecked_rows") or 0) for r in manifest),
        "stock_rows":len(all_rows),
        "parquet_file":pp.name,"parquet_bytes":pp.stat().st_size,"parquet_sha256":sha_file(pp),
        "query_manifest_file":mp.name,"query_manifest_sha256":sha_file(mp),
        "factor_or_forward_return_computed":False,
        "holdout_outcome_inspected":False,
        "sample_replacement_used":False,
    }
    receipt["receipt_sha256"]=stable_sha(receipt)
    rp=out/f"V2.8.6_FOLD1_BAOSTOCK_BUCKET_{bucket_id}_RECEIPT.json"
    rp.write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(receipt,ensure_ascii=False,indent=2))

def run_benchmark(out:Path):
    pav=runtime_guard()
    out.mkdir(parents=True,exist_ok=True)
    lg=bs.login()
    if lg.error_code!="0":
        raise RuntimeError(f"BAOSTOCK_LOGIN_ERROR:{lg.error_code}:{lg.error_msg}")
    try:
        raw=fetch("sh.000300","3")
        rec=validate_unadjusted("sh.000300",raw)
    finally:
        bs.logout()
    if rec["status"]!="SUCCESS":
        raise RuntimeError("BENCHMARK_ZERO_ROWS_BLOCKED")
    rows=[{
        "canonical_security_id":"BENCHMARK:CSI300","exchange":"SSE_INDEX","security_code":"000300",
        "baostock_code":"sh.000300","sample_bucket":-1,**r
    } for r in raw]
    pp=out/"V2.8.6_FOLD1_BAOSTOCK_CSI300.parquet"
    write_parquet(pp,rows)
    receipt={
        "schema":"AI_CORE_EVID_V2_8_6_FOLD1_BAOSTOCK_BENCHMARK_RECEIPT_V1",
        "version":"V2.8.6","status":"PASS","baostock_version":"0.9.4","pyarrow_version":pav,
        "retrieval_start":START,"retrieval_end":END,
        **rec,"file":pp.name,"bytes":pp.stat().st_size,"parquet_sha256":sha_file(pp),
        "factor_or_forward_return_computed":False,"holdout_outcome_inspected":False,
    }
    receipt["receipt_sha256"]=stable_sha(receipt)
    rp=out/"V2.8.6_FOLD1_BAOSTOCK_BENCHMARK_RECEIPT.json"
    rp.write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(receipt,ensure_ascii=False,indent=2))

def main():
    ap=argparse.ArgumentParser()
    g=ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--bucket",type=int,choices=range(8))
    g.add_argument("--benchmark",action="store_true")
    ap.add_argument("--out",required=True)
    a=ap.parse_args()
    if a.benchmark:
        run_benchmark(Path(a.out))
    else:
        run_bucket(a.bucket,Path(a.out))

if __name__=="__main__":
    main()
