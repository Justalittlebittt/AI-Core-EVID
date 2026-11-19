#!/usr/bin/env python3
"""One-shot CU2609 incremental forecast development (NOT pristine OOS or a trade system)."""
from __future__ import annotations
import hashlib
import json
import math
import time
import urllib.request
from datetime import date,datetime,timezone
from pathlib import Path
import numpy as np
from v29_2025_filing_to_return_case import records

ROOT=Path(__file__).resolve().parents[1]
SPEC=ROOT/"research/V3.2_COPPER_INCREMENTAL_INFORMATION_DEV_PREDECLARATION_20261119.json"
OUT=Path("/tmp/v32_copper_incremental_development_result.json")
START,END="2026-05-06","2026-07-15"
STOCK_END="2026-07-31"
FIELDS="date,code,open,close,adjustflag,tradestatus,isST,volume"
SHFE_URL="https://www.shfe.com.cn/data/tradedata/future/dailydata/kx%s.dat"

def read_spec():
    raw=SPEC.read_bytes()
    s=json.loads(raw)
    if (s["schema"]!="V32_COPPER_INCREMENTAL_PREDICTION_DEVELOPMENT_SPEC_V1"
        or s["dates"]["first_signal"]!=START or s["dates"]["last_signal"]!=END
        or s["SHFE"]["delivery_month"]!="2609"
        or s["no_buy"] is not True):
        raise ValueError("PREREGISTERED_RULE_CHANGED")
    return s,hashlib.sha256(raw).hexdigest()

def validnum(v):
    try:
        x=float(v)
        return x if math.isfinite(x) and x>0 else None
    except (TypeError,ValueError):return None

def fetch_copper(d):
    url=SHFE_URL%d.replace("-","")
    try:
        with urllib.request.urlopen(urllib.request.Request(url,headers={
            "User-Agent":"Mozilla/5.0","Accept":"application/json",
            "Referer":"https://www.shfe.com.cn/"}),timeout=14) as resp:
            raw=resp.read(3000001)
        if len(raw)>3000000:raise ValueError("SOURCE_TOO_LARGE")
        doc=json.loads(raw)
        rows=doc.get("o_curinstrument")
        if not isinstance(rows,list):raise ValueError("INVALID_SHFE_ROWS")
        matched=[r for r in rows if isinstance(r,dict)
                 and r.get("PRODUCTGROUPID")=="cu"
                 and r.get("PRODUCTID")=="cu_f"
                 and str(r.get("DELIVERYMONTH"))=="2609"]
        if len(matched)!=1:raise ValueError("CONTRACT_IDENTITY_NOT_UNIQUE")
        close=validnum(matched[0].get("CLOSEPRICE"))
        if close is None:raise ValueError("CLOSE_NOT_VALID")
        return {"status":"OK","close":close,"source_sha256":hashlib.sha256(raw).hexdigest(),
                "source_url":url}
    except (OSError,ValueError,KeyError,TypeError) as e:
        return {"status":"SOURCE_FAILED","reason":type(e).__name__,
                "detail":str(e)[:100],"source_url":url}

def dates_and_stocks():
    import baostock as bs
    status=bs.login()
    if status.error_code!="0":raise ValueError("BAOSTOCK_LOGIN_FAILED")
    try:
        cal=records(bs.query_trade_dates(start_date="2026-04-20",end_date=STOCK_END))
        sessions=[x["calendar_date"] for x in cal if x["is_trading_day"]=="1"]
        if len(sessions)<40 or sessions!=sorted(set(sessions)):
            raise ValueError("INVALID_BAOSTOCK_TRADING_CALENDAR")
        tickers=["sh.603993","sz.002203","sh.000300"]
        bars={}
        for code in tickers:
            quotes=records(bs.query_history_k_data_plus(
              code,FIELDS,start_date="2026-04-20",end_date=STOCK_END,
              frequency="d",adjustflag="3"))
            row={}
            for x in quotes:
                if x["date"] in row or x["code"]!=code or x["adjustflag"]!="3":
                    raise ValueError("DUPLICATE_ID_OR_WRONG_QUOTE_FLAG")
                row[x["date"]]=x
            bars[code]=row
            print("BAOSTOCK_HISTORY",code,len(row),flush=True)
        return sessions,bars,cal
    finally:
        bs.logout()

def ols(x,y):
    return np.linalg.lstsq(np.array(x,dtype=float),np.array(y,dtype=float),rcond=None)[0]

def forecast_report(issuer,signal_rows):
    n=len(signal_rows)
    row={"security_id":issuer,"eligible_observations":n,
         "signal_dates":[x["date"] for x in signal_rows]}
    if n<28:
        row["status"]="INSUFFICIENT_SIGNAL_OBSERVATIONS"
        return row
    cutoff=math.floor(n*.6)
    first_test_signal=signal_rows[cutoff]["date"]
    train=[v for v in signal_rows[:cutoff] if v["exit"]<first_test_signal]
    test=signal_rows[cutoff:]
    row.update({"train_count_after_purge":len(train),"test_count":len(test),
                "test_first_signal":first_test_signal,
                "train_last_exit":train[-1]["exit"] if train else None})
    if len(train)<15 or len(test)<8:
        row["status"]="INSUFFICIENT_PURGED_TRAIN_OR_TEST";return row
    # Freeze model membership before reading downstream test targets for fitting.
    # Training y values are used only for training OLS, never for input features.
    def xrow(z,aug):
        return [1.0,z["lag_stock_excess"]]+([z["lag_copper"]] if aug else [])
    train_y=[z["target_excess"] for z in train]
    a=ols([xrow(z,False) for z in train],train_y)
    b=ols([xrow(z,True) for z in train],train_y)
    y=np.array([z["target_excess"] for z in test])
    p0=np.array([float(np.dot(a,xrow(z,False))) for z in test])
    p1=np.array([float(np.dot(b,xrow(z,True))) for z in test])
    m0=float(np.mean((y-p0)**2));m1=float(np.mean((y-p1)**2))
    row.update({"status":"DESCRIPTIVE_TRAIN_TEST_COMPLETE","baseline_test_mse":m0,
        "augmented_test_mse":m1,"relative_mse_improvement":1-m1/m0 if m0>0 else None,
        "baseline_coefs":[float(v) for v in a],
        "augmented_coefs":[float(v) for v in b],
        "test_mean_target_excess":float(np.mean(y)),
        "test_signal_count":len(test),
        "complete_price_only_executable_return":False})
    return row

def main():
    spec,specsha=read_spec()
    sessions,bars,calendar=dates_and_stocks()
    first=date.fromisoformat(START);last=date.fromisoformat(END)
    signal_days=[d for d in sessions if first<=date.fromisoformat(d)<=last]
    needed=set(signal_days)
    for d in signal_days:
        i=sessions.index(d)
        if i<1 or i+3>=len(sessions):raise ValueError("MISSING_SIGNAL_BOUNDARIES")
        needed.add(sessions[i-1])
    copper={}
    for i,d in enumerate(sorted(needed),1):
        copper[d]=fetch_copper(d)
        if i%12==0:print("SHFE_SOURCE_PROGRESS",i,len(needed),flush=True)
        time.sleep(.12)
    rows={}
    statuses={}
    for issuer in ["sh.603993","sz.002203"]:
        obs=[]
        for d in signal_days:
            i=sessions.index(d)
            prior,entry,exitday=sessions[i-1],sessions[i+2],sessions[i+3]
            cf,cp=copper[d],copper[prior]
            if cf["status"]!="OK" or cp["status"]!="OK":
                statuses["COPPER_SOURCE_MISSING"]=statuses.get("COPPER_SOURCE_MISSING",0)+1
                continue
            a=bars[issuer];b=bars["sh.000300"]
            if any(k not in a or k not in b for k in (prior,d,entry,exitday)):
                statuses["STOCK_OR_INDEX_BAR_MISSING"]=statuses.get("STOCK_OR_INDEX_BAR_MISSING",0)+1
                continue
            if any(a[k].get("tradestatus")!="1" or a[k].get("isST")!="0" or
                   validnum(a[k].get("volume")) is None for k in (prior,d,entry,exitday)):
                statuses["STOCK_OR_ENTRY_TRADING_STATUS_INVALID"]=statuses.get("STOCK_OR_ENTRY_TRADING_STATUS_INVALID",0)+1
                continue
            pa,pb=a[prior],a[d]
            ia,ib=b[prior],b[d]
            features=[validnum(x.get("close")) for x in (pa,pb,ia,ib)]
            targets=[validnum(a[entry].get("open")),validnum(a[exitday].get("close")),
                     validnum(b[entry].get("open")),validnum(b[exitday].get("close"))]
            if None in features+targets:
                statuses["NONPOSITIVE_PRICE"]=statuses.get("NONPOSITIVE_PRICE",0)+1
                continue
            lag_stock=(features[1]/features[0]-1)-(features[3]/features[2]-1)
            lag_copper=cf["close"]/cp["close"]-1
            target=targets[1]/targets[0]-1-(targets[3]/targets[2]-1)
            obs.append({"date":d,"entry":entry,"exit":exitday,
                        "lag_copper":lag_copper,"lag_stock_excess":lag_stock,
                        "target_excess":target})
        rows[issuer]=obs
    issuer_result=[forecast_report(issuer,rows[issuer]) for issuer in sorted(rows)]
    improvements=[r.get("relative_mse_improvement") for r in issuer_result]
    if any(z is None for z in improvements):
        verdict="SOURCE_OR_SAMPLE_INSUFFICIENT"
    elif all(z>0 for z in improvements):
        verdict="DESCRIPTIVE_INCREMENTAL_SUPPORT_ONLY_NOT_VERIFIED_ALPHA"
    else:
        verdict="NOT_SUPPORTED_BY_THIS_RETROSPECTIVE_DEVELOPMENT_SAMPLE"
    summary={"schema":"V32_COPPER_INCREMENTAL_FORECAST_RETROSPECTIVE_DEV_RESULT_V1",
      "preregistered_spec_sha256":specsha,
      "status":verdict,"eligible_signal_dates_requested":len(signal_days),
      "shfe_source_days_queried":len(needed),
      "shfe_source_days_valid":sum(q["status"]=="OK" for q in copper.values()),
      "missing_reasons":statuses,
      "issuer_results":issuer_result,
      "mean_relative_mse_improvement":(float(np.mean(improvements))
                if all(x is not None for x in improvements) else None),
      "source_summaries":{k:v for k,v in copper.items()},
      "retrospective_holdout_not_pristine_OOS":True,
      "source_publication_in_historical_clock_certified":False,
      "costed_executable_alpha_tested":False,
      "corporate_action_and_limit_price_executability_verified":False,
      "signal_has_no_required_prior_stock_appreciation":True,
      "live_buy_authorized":False}
    OUT.write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("V32_INCREMENTAL_RESULT="+json.dumps({k:v for k,v in summary.items()
          if k not in ("source_summaries",)},ensure_ascii=False),flush=True)

if __name__=="__main__":main()
