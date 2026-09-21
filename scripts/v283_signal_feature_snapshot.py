from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

def sha_file(path:Path)->str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""):
            h.update(b)
    return h.hexdigest()

def factor_values(df:pd.DataFrame)->dict:
    x=df.sort_values("bar_date").copy()
    c=pd.to_numeric(x["close"],errors="coerce").astype(float)
    h=pd.to_numeric(x["high"],errors="coerce").astype(float)
    l=pd.to_numeric(x["low"],errors="coerce").astype(float)
    prev=c.shift(1)
    logret=np.log(c/prev)
    rv10=logret.tail(10).std(ddof=0) if logret.tail(10).notna().sum()==10 else np.nan
    rv60=logret.tail(60).std(ddof=0) if logret.tail(60).notna().sum()==60 else np.nan
    tr=np.maximum.reduce([
        (h-l).to_numpy(float),
        (h-prev).abs().to_numpy(float),
        (l-prev).abs().to_numpy(float),
    ])
    tr_pct=pd.Series(tr,index=x.index)/prev
    tr10=tr_pct.tail(10).mean() if tr_pct.tail(10).notna().sum()==10 else np.nan
    tr60=tr_pct.tail(60).mean() if tr_pct.tail(60).notna().sum()==60 else np.nan
    rv_ratio=rv10/rv60 if np.isfinite(rv10) and np.isfinite(rv60) and rv60>0 else np.nan
    tr_ratio=tr10/tr60 if np.isfinite(tr10) and np.isfinite(tr60) and tr60>0 else np.nan
    return {
        "rv10_over_rv60":float(rv_ratio) if np.isfinite(rv_ratio) else np.nan,
        "tr10_over_tr60":float(tr_ratio) if np.isfinite(tr_ratio) else np.nan,
        "source_close_d":float(c.iloc[-1]) if len(c) and np.isfinite(c.iloc[-1]) and c.iloc[-1]>0 else np.nan,
    }

def market_state(ratio:float)->str:
    if not np.isfinite(ratio):
        return "UNKNOWN"
    return "CALM" if ratio<=1.0 else "STRESSED"

def self_test():
    tests=[]
    def ck(name,v): tests.append({"name":name,"pass":bool(v)})
    n=80
    # deterministic varying series: enough nonzero volatility and TR history.
    close=np.array([100.0*math.exp(0.001*i + 0.01*math.sin(i/3.0)) for i in range(n)])
    df=pd.DataFrame({
        "bar_date":pd.date_range("2026-01-01",periods=n,freq="D"),
        "close":close,
        "high":close*1.01,
        "low":close*0.99,
    })
    v=factor_values(df)
    ck("F01_rv_ratio_finite",np.isfinite(v["rv10_over_rv60"]) and v["rv10_over_rv60"]>0)
    ck("F02_tr_ratio_finite",np.isfinite(v["tr10_over_tr60"]) and v["tr10_over_tr60"]>0)
    ck("F03_close_d_exact",abs(v["source_close_d"]-close[-1])<1e-12)
    ck("F04_market_calm_identity",market_state(1.0)=="CALM")
    ck("F05_market_stressed",market_state(1.0000001)=="STRESSED")
    short=factor_values(df.tail(40))
    ck("F06_60bar_warmup_blocks",np.isnan(short["rv10_over_rv60"]) and np.isnan(short["tr10_over_tr60"]))
    # Scale invariance is required by the research architecture.
    scaled=df.copy()
    for col in ["close","high","low"]:
        scaled[col]=scaled[col]*17.25
    s=factor_values(scaled)
    ck("F07_rv_scale_invariant",abs(s["rv10_over_rv60"]-v["rv10_over_rv60"])<1e-12)
    ck("F08_tr_scale_invariant",abs(s["tr10_over_tr60"]-v["tr10_over_tr60"])<1e-12)
    result={"schema":"AI_CORE_EVID_V2_8_3_SIGNAL_FEATURE_SNAPSHOT_SELFTEST_V1",
            "passed":sum(x["pass"] for x in tests),"total":len(tests),
            "all_pass":all(x["pass"] for x in tests),"tests":tests}
    print(json.dumps(result,ensure_ascii=False,indent=2))
    if not result["all_pass"]:
        raise SystemExit(2)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("command",choices=["self-test"])
    a=ap.parse_args()
    self_test()

if __name__=="__main__":
    main()
