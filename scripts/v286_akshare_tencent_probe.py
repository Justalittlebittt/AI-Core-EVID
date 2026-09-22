from __future__ import annotations

import hashlib, importlib.metadata, json, math
from pathlib import Path
import akshare as ak
import pandas as pd

VERSION="1.18.97"
START="20220104"; END="20220331"
SYMBOLS=["sh600000","sz000001","sz300750"]
OUT=Path("v286_tencent_probe/V2.8.6_AKSHARE_TENCENT_SOURCE_PROBE_RECEIPT.json")

def stable_sha(obj):
    return hashlib.sha256(json.dumps(obj,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()

def normalize(df,symbol):
    if df is None or df.empty:
        raise RuntimeError(f"EMPTY:{symbol}")
    cols=[str(c).lower() for c in df.columns]
    # Required semantic fields rather than exact presentation names.
    required={"date","open","close","high","low","volume"}
    if not required.issubset(set(cols)):
        raise RuntimeError(f"SCHEMA:{symbol}:{list(df.columns)}")
    x=df.copy()
    x.columns=cols
    rows=[]
    for _,r in x.iterrows():
        d=pd.Timestamp(r["date"]).date().isoformat()
        vals={k:float(r[k]) for k in ("open","close","high","low","volume")}
        if any(not math.isfinite(vals[k]) for k in vals):
            raise RuntimeError(f"NONFINITE:{symbol}:{d}")
        if any(vals[k]<=0 for k in ("open","close","high","low")):
            raise RuntimeError(f"NONPOSITIVE:{symbol}:{d}")
        if vals["high"]<max(vals["open"],vals["close"],vals["low"]) or vals["low"]>min(vals["open"],vals["close"],vals["high"]):
            raise RuntimeError(f"OHLC:{symbol}:{d}")
        rows.append({"date":d,**vals})
    dates=[r["date"] for r in rows]
    if dates!=sorted(dates) or len(dates)!=len(set(dates)):
        raise RuntimeError(f"DATE_ORDER:{symbol}")
    if dates[0]<"2022-01-04" or dates[-1]>"2022-03-31":
        raise RuntimeError(f"DATE_RANGE:{symbol}")
    return rows

def main():
    if importlib.metadata.version("akshare")!=VERSION:
        raise RuntimeError("AKSHARE_VERSION_MISMATCH")
    q=[]
    for symbol in SYMBOLS:
        df=ak.stock_zh_a_hist_tx(symbol=symbol,start_date=START,end_date=END,adjust="hfq")
        rows=normalize(df,symbol)
        q.append({"symbol":symbol,"rows":len(rows),"min_date":rows[0]["date"],"max_date":rows[-1]["date"],"rows_sha256":stable_sha(rows)})
    receipt={
      "schema":"AI_CORE_EVID_V2_8_6_AKSHARE_TENCENT_SOURCE_PROBE_RECEIPT_V1",
      "version":"V2.8.6","status":"PASS","akshare_version":VERSION,
      "upstream":"Tencent Securities","interface":"stock_zh_a_hist_tx","adjust":"hfq",
      "probe_start":"2022-01-04","probe_end":"2022-03-31","queries":q,
      "fold1_price_rows_read":False,"factor_or_forward_return_computed":False,
      "mechanism_statistics_computed":False,"fold2_3_4_consumed":False
    }
    receipt["receipt_sha256"]=stable_sha(receipt)
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(receipt,ensure_ascii=False,indent=2))
if __name__=="__main__": main()
