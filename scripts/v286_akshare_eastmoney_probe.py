from __future__ import annotations

import hashlib
import importlib.metadata
import json
import math
from pathlib import Path

import akshare as ak
import pandas as pd

VERSION="1.18.97"
START="20220104"
END="20220331"
SYMBOLS=["600000","000001","300750"]
EXPECTED_COLUMNS=["日期","股票代码","开盘","收盘","最高","最低","成交量","成交额","振幅","涨跌幅","涨跌额","换手率"]
OUT=Path("v286_eastmoney_probe/V2.8.6_AKSHARE_EASTMONEY_SOURCE_PROBE_RECEIPT.json")

def stable_sha(obj)->str:
    return hashlib.sha256(
        json.dumps(obj,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()
    ).hexdigest()

def normalized_rows(df:pd.DataFrame,symbol:str)->list[dict]:
    rows=[]
    for _,r in df.iterrows():
        d=pd.Timestamp(r["日期"]).date().isoformat()
        code=str(r["股票代码"]).strip().split(".")[0].zfill(6)
        rows.append({
            "date":d,"security_code":code,
            "open":float(r["开盘"]),"close":float(r["收盘"]),
            "high":float(r["最高"]),"low":float(r["最低"]),
            "volume":float(r["成交量"]),"amount":float(r["成交额"]),
        })
    return rows

def validate(symbol:str,df:pd.DataFrame)->dict:
    if list(df.columns)!=EXPECTED_COLUMNS:
        raise RuntimeError(f"SCHEMA_MISMATCH:{symbol}:{list(df.columns)}")
    if len(df)<20:
        raise RuntimeError(f"TOO_FEW_ROWS:{symbol}:{len(df)}")
    rows=normalized_rows(df,symbol)
    dates=[r["date"] for r in rows]
    if dates!=sorted(dates) or len(dates)!=len(set(dates)):
        raise RuntimeError(f"DATE_ORDER_OR_DUPLICATE:{symbol}")
    if min(dates)<"2022-01-04" or max(dates)>"2022-03-31":
        raise RuntimeError(f"DATE_RANGE_DRIFT:{symbol}")
    if {r["security_code"] for r in rows}!={symbol}:
        raise RuntimeError(f"SECURITY_CODE_DRIFT:{symbol}")
    for r in rows:
        vals={k:r[k] for k in ("open","close","high","low")}
        if any(not math.isfinite(v) or v<=0 for v in vals.values()):
            raise RuntimeError(f"NONPOSITIVE_OHLC:{symbol}:{r['date']}")
        if vals["high"]<max(vals["open"],vals["close"],vals["low"]):
            raise RuntimeError(f"OHLC_ORDER:{symbol}:{r['date']}")
        if vals["low"]>min(vals["open"],vals["close"],vals["high"]):
            raise RuntimeError(f"OHLC_ORDER:{symbol}:{r['date']}")
    return {
        "symbol":symbol,"rows":len(rows),"min_date":dates[0],"max_date":dates[-1],
        "normalized_rows_sha256":stable_sha(rows)
    }

def main():
    version=importlib.metadata.version("akshare")
    if version!=VERSION:
        raise RuntimeError(f"AKSHARE_VERSION_MISMATCH:{version}")
    queries=[]
    for symbol in SYMBOLS:
        df=ak.stock_zh_a_hist(
            symbol=symbol,period="daily",start_date=START,end_date=END,adjust="hfq",timeout=20
        )
        queries.append(validate(symbol,df))
    receipt={
        "schema":"AI_CORE_EVID_V2_8_6_AKSHARE_EASTMONEY_SOURCE_PROBE_RECEIPT_V1",
        "version":"V2.8.6","status":"PASS",
        "akshare_version":version,
        "upstream":"Eastmoney","interface":"stock_zh_a_hist",
        "period":"daily","adjust":"hfq",
        "probe_start":"2022-01-04","probe_end":"2022-03-31",
        "queries":queries,
        "fold1_price_rows_read":False,
        "factor_or_forward_return_computed":False,
        "mechanism_statistics_computed":False,
        "fold2_3_4_consumed":False
    }
    receipt["receipt_sha256"]=stable_sha(receipt)
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(receipt,ensure_ascii=False,indent=2))

if __name__=="__main__":
    main()
