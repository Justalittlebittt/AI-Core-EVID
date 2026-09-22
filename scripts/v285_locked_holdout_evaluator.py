from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

SOURCE_RECEIPT=Path("evidence/V2.8.5_BAOSTOCK_HOLDOUT_SOURCE_SNAPSHOT_RECEIPT.json")
SOURCE_DIR=Path("evidence/v285_holdout_source")
SAMPLE=Path("evidence/V2.8.5_BACKWARD_HOLDOUT_SAMPLE_MANIFEST.csv")
CALENDAR=Path("evidence/V2.8.5_JOINT_A_SHARE_TRADING_CALENDAR_2023_2024.json")
DAILY_OUT=Path("evidence/V2.8.5_BACKWARD_HOLDOUT_DAILY_METRICS.csv")
LEDGER_OUT=Path("evidence/V2.8.5_BACKWARD_HOLDOUT_HYPOTHESIS_LEDGER.csv")
FINAL_OUT=Path("evidence/V2.8.5_BACKWARD_HOLDOUT_FINAL_RECEIPT.json")

B=10000
BLOCK=20
ALPHA=0.05
MIN_ROWS=50
HYP=[
    {"id":"H1_RV_COMPRESSION_CALM_BACKWARD_HOLDOUT","factor":"rv10_over_rv60","seed":2851001,"contrast_seed":2851101},
    {"id":"H2_TR_COMPRESSION_CALM_BACKWARD_HOLDOUT","factor":"tr10_over_tr60","seed":2851002,"contrast_seed":2851102},
]

def sha_file(path:Path)->str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""):
            h.update(b)
    return h.hexdigest()

def stable_json_sha(obj)->str:
    return hashlib.sha256(
        json.dumps(obj,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()
    ).hexdigest()

def avg_rank_corr(x,y)->float:
    a=pd.Series(x).rank(method="average")
    b=pd.Series(y).rank(method="average")
    if len(a)<2 or a.nunique()<2 or b.nunique()<2:
        return np.nan
    return float(a.corr(b,method="pearson"))

def circular_block_means(values,seed:int,B_:int=B,block:int=BLOCK):
    x=np.asarray(values,dtype=float)
    if len(x)==0 or not np.isfinite(x).all():
        raise RuntimeError("BOOTSTRAP_INPUT_INVALID")
    rng=np.random.default_rng(seed)
    n=len(x); k=int(np.ceil(n/block))
    starts=rng.integers(0,n,size=(B_,k))
    offs=np.arange(block)
    idx=(starts[:,:,None]+offs[None,None,:])%n
    idx=idx.reshape(B_,-1)[:,:n]
    return x[idx].mean(axis=1)

def primary_bootstrap(values,seed:int):
    x=np.asarray(values,dtype=float)
    obs=float(x.mean())
    null=circular_block_means(x-obs,seed)
    p=(1+int((null>=obs).sum()))/(B+1)
    boots=circular_block_means(x,seed)
    lo,hi=np.quantile(boots,[0.025,0.975])
    return obs,float(lo),float(hi),float(p)

def contrast_bootstrap(calm,stressed,seed:int):
    c=np.asarray(calm,dtype=float); s=np.asarray(stressed,dtype=float)
    obs=float(c.mean()-s.mean())
    d=circular_block_means(c,seed)-circular_block_means(s,seed+10000)
    lo,hi=np.quantile(d,[0.025,0.975])
    return obs,float(lo),float(hi)

def holm_pass(pvals:dict[str,float])->dict[str,bool]:
    order=sorted(pvals,key=lambda k:(pvals[k],k))
    out={k:False for k in pvals}; alive=True; m=len(order)
    for i,k in enumerate(order):
        if alive and pvals[k] <= ALPHA/(m-i):
            out[k]=True
        else:
            alive=False
    return out

def load_calendar()->list[str]:
    x=json.loads(CALENDAR.read_text(encoding="utf-8"))
    days=x["trading_dates"]
    if len(days)!=484 or days!=sorted(days) or len(days)!=len(set(days)):
        raise RuntimeError("CALENDAR_INTEGRITY_BLOCK")
    return days

def targets(days:list[str])->dict[str,tuple[str|None,str|None]]:
    idx={d:i for i,d in enumerate(days)}
    out={}
    for d,i in idx.items():
        d5=days[i+5] if i+5<len(days) else None
        d10=days[i+10] if i+10<len(days) else None
        out[d]=(d5,d10)
    return out

def load_source()->tuple[pd.DataFrame,pd.DataFrame,dict]:
    rec=json.loads(SOURCE_RECEIPT.read_text(encoding="utf-8"))
    if rec.get("status")!="PASS":
        raise RuntimeError("SOURCE_SNAPSHOT_NOT_PASS")
    parts=[]
    for p in rec["stock_partitions"]:
        fp=SOURCE_DIR/p["file"]
        if not fp.exists() or sha_file(fp)!=p["sha256"]:
            raise RuntimeError(f"STOCK_PARTITION_INTEGRITY_BLOCK:{p['file']}")
        parts.append(pq.read_table(fp).to_pandas())
    stock=pd.concat(parts,ignore_index=True) if parts else pd.DataFrame()
    bp=SOURCE_DIR/rec["benchmark"]["file"]
    if not bp.exists() or sha_file(bp)!=rec["benchmark"]["parquet_sha256"]:
        raise RuntimeError("BENCHMARK_INTEGRITY_BLOCK")
    bench=pq.read_table(bp).to_pandas()
    mp=SOURCE_DIR/rec["query_manifest_file"]
    if not mp.exists() or sha_file(mp)!=rec["query_manifest_sha256"]:
        raise RuntimeError("QUERY_MANIFEST_INTEGRITY_BLOCK")
    return stock,bench,rec

def load_sample()->dict[str,dict]:
    rows=list(csv.DictReader(SAMPLE.read_text(encoding="utf-8").splitlines()))
    if len(rows)!=1031:
        raise RuntimeError("SAMPLE_COUNT_BLOCK")
    return {r["canonical_security_id"]:r for r in rows}

def numeric(s):
    return pd.to_numeric(s,errors="coerce").astype(float)

def symbol_panel(g:pd.DataFrame,meta:dict,days:list[str],tgt:dict[str,tuple[str|None,str|None]])->list[dict]:
    x=g.loc[g["tradestatus"].astype(str)=="1"].copy()
    if x.empty:
        return []
    x=x.sort_values("date",kind="mergesort").drop_duplicates("date",keep=False)
    close=numeric(x["close"]); high=numeric(x["high"]); low=numeric(x["low"])
    prev=close.shift(1)
    logret=np.log(close/prev)
    rv10=logret.rolling(10,min_periods=10).std(ddof=0)
    rv60=logret.rolling(60,min_periods=60).std(ddof=0)
    tr_abs=pd.concat([(high-low),(high-prev).abs(),(low-prev).abs()],axis=1).max(axis=1)
    tr_pct=tr_abs/prev
    tr10=tr_pct.rolling(10,min_periods=10).mean()
    tr60=tr_pct.rolling(60,min_periods=60).mean()
    x["rv10_over_rv60"]=rv10/rv60.replace(0,np.nan)
    x["tr10_over_tr60"]=tr10/tr60.replace(0,np.nan)
    x["close_num"]=close
    by=x.set_index("date")
    ld=meta["official_list_date"]; dd=str(meta.get("official_delist_date") or "")
    out=[]
    for d in days:
        if d<ld or (dd and d>=dd) or d not in by.index:
            continue
        r=by.loc[d]
        if isinstance(r,pd.DataFrame):
            raise RuntimeError(f"DUPLICATE_STOCK_DATE:{meta['canonical_security_id']}:{d}")
        d5,d10=tgt[d]
        c=float(r["close_num"])
        def fwd(td):
            if td is None or td not in by.index or not np.isfinite(c) or c<=0:
                return np.nan
            rr=by.loc[td]
            if isinstance(rr,pd.DataFrame):
                raise RuntimeError(f"DUPLICATE_STOCK_DATE:{meta['canonical_security_id']}:{td}")
            t=float(rr["close_num"])
            return t/c-1.0 if np.isfinite(t) and t>0 else np.nan
        out.append({
            "canonical_security_id":meta["canonical_security_id"],
            "signal_date":d,
            "rv10_over_rv60":float(r["rv10_over_rv60"]) if np.isfinite(r["rv10_over_rv60"]) else np.nan,
            "tr10_over_tr60":float(r["tr10_over_tr60"]) if np.isfinite(r["tr10_over_tr60"]) else np.nan,
            "fwd_5":fwd(d5),
            "fwd_10":fwd(d10),
        })
    return out

def market_context(bench:pd.DataFrame,days:list[str])->dict[str,str]:
    x=bench.loc[bench["tradestatus"].astype(str)=="1"].copy()
    x=x.sort_values("date",kind="mergesort")
    if x["date"].duplicated().any():
        raise RuntimeError("BENCHMARK_DUPLICATE_DATE")
    have=set(x["date"].astype(str))
    missing=[d for d in days if d not in have]
    if missing:
        raise RuntimeError(f"BENCHMARK_MISSING_JOINT_DATES:{missing[:10]}")
    close=numeric(x["close"]); lr=np.log(close/close.shift(1))
    rv10=lr.rolling(10,min_periods=10).std(ddof=0)
    rv60=lr.rolling(60,min_periods=60).std(ddof=0)
    ratio=rv10/rv60.replace(0,np.nan)
    x["ratio"]=ratio
    out={}
    for _,r in x.iterrows():
        d=str(r["date"])
        if d not in have or d not in set(days):
            continue
        v=r["ratio"]
        out[d]="UNKNOWN" if not np.isfinite(v) else "CALM" if float(v)<=1 else "STRESSED"
    return out

def panel_hash(rows:list[dict])->str:
    h=hashlib.sha256()
    for r in sorted(rows,key=lambda x:(x["signal_date"],x["canonical_security_id"])):
        vals=[
            r["canonical_security_id"],r["signal_date"],
            "" if not np.isfinite(r["rv10_over_rv60"]) else format(r["rv10_over_rv60"],".17g"),
            "" if not np.isfinite(r["tr10_over_tr60"]) else format(r["tr10_over_tr60"],".17g"),
            "" if not np.isfinite(r["fwd_5"]) else format(r["fwd_5"],".17g"),
            "" if not np.isfinite(r["fwd_10"]) else format(r["fwd_10"],".17g"),
        ]
        h.update(("\x1f".join(vals)+"\n").encode())
    return h.hexdigest()

def daily_metrics(panel:pd.DataFrame,states:dict[str,str])->pd.DataFrame:
    rows=[]
    for d,g in panel.groupby("signal_date",sort=True):
        rec={"signal_date":d,"market_state":states[d]}
        for h in HYP:
            fac=h["factor"]
            for horizon,col in (("D5","fwd_5"),("D10","fwd_10")):
                a=numeric(g[fac]); b=numeric(g[col]); ok=np.isfinite(a)&np.isfinite(b)
                n=int(ok.sum())
                ic=avg_rank_corr(a[ok],b[ok]) if n>=MIN_ROWS else np.nan
                rec[f"{h['id']}_{horizon}"]=ic
                rec[f"{h['id']}_{horizon}_n"]=n
        rows.append(rec)
    return pd.DataFrame(rows)

def quarter_label(d:str)->str:
    t=pd.Timestamp(d)
    return f"{t.year}Q{(t.month-1)//3+1}"

def evaluate(write:bool=True)->dict:
    if FINAL_OUT.exists():
        old=json.loads(FINAL_OUT.read_text(encoding="utf-8"))
        return {"status":"FINAL_ALREADY_FROZEN_NO_REEVALUATION","existing_receipt_sha256":old.get("receipt_sha256")}
    days=load_calendar(); tgt=targets(days)
    stock,bench,src=load_source(); sample=load_sample()
    if set(stock["canonical_security_id"].unique())-set(sample):
        raise RuntimeError("SOURCE_CONTAINS_NON_SAMPLE_SECURITY")
    rows=[]
    for cid,g in stock.groupby("canonical_security_id",sort=True):
        rows.extend(symbol_panel(g,sample[cid],days,tgt))
    ph=panel_hash(rows)
    panel=pd.DataFrame(rows)
    states=market_context(bench,days)
    daily=daily_metrics(panel,states)

    pvals={}; per={}; enough=True
    for h in HYP:
        hid=h["id"]
        x=daily[["signal_date","market_state",f"{hid}_D10",f"{hid}_D5"]].copy()
        x["adj10"]=-1*pd.to_numeric(x[f"{hid}_D10"],errors="coerce")
        x["adj5"]=-1*pd.to_numeric(x[f"{hid}_D5"],errors="coerce")
        calm10=x.loc[(x.market_state=="CALM")&np.isfinite(x.adj10),"adj10"].to_numpy(float)
        stress10=x.loc[(x.market_state=="STRESSED")&np.isfinite(x.adj10),"adj10"].to_numpy(float)
        calm5=x.loc[(x.market_state=="CALM")&np.isfinite(x.adj5),"adj5"].to_numpy(float)
        qx=x.loc[(x.market_state=="CALM")&np.isfinite(x.adj10),["signal_date","adj10"]].copy()
        qx["quarter"]=qx["signal_date"].map(quarter_label)
        qmeans={q:float(g["adj10"].mean()) for q,g in qx.groupby("quarter",sort=True) if len(g)>=15}
        ready=len(calm10)>=60 and len(stress10)>=30 and len(qmeans)>=3
        enough=enough and ready
        per[hid]={
            "factor":h["factor"],"ready":ready,
            "valid_calm_d10_dates":len(calm10),
            "valid_stressed_d10_dates":len(stress10),
            "valid_calm_d5_dates":len(calm5),
            "valid_quarter_means":qmeans,
            "calm10":calm10,"stress10":stress10,"calm5":calm5,"qx":qx,
        }

    if not enough:
        final={
            "schema":"AI_CORE_EVID_V2_8_5_BACKWARD_HOLDOUT_FINAL_RECEIPT_V1",
            "version":"V2.8.5",
            "status":"V2_8_5_BACKWARD_HOLDOUT_INCOMPLETE",
            "panel_rows":len(panel),
            "panel_identity_sha256":ph,
            "information":{
                hid:{k:v for k,v in r.items() if k in {"ready","valid_calm_d10_dates","valid_stressed_d10_dates","valid_calm_d5_dates","valid_quarter_means"}}
                for hid,r in per.items()
            },
            "setup_or_episode_emission_authorized":False,
            "live_authorized":False,
        }
        final["receipt_sha256"]=stable_json_sha(final)
        if write:
            daily.to_csv(DAILY_OUT,index=False,lineterminator="\n")
            FINAL_OUT.write_text(json.dumps(final,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        return final

    for h in HYP:
        hid=h["id"]; r=per[hid]
        obs,lo,hi,p=primary_bootstrap(r["calm10"],h["seed"])
        con,clo,chi=contrast_bootstrap(r["calm10"],r["stress10"],h["contrast_seed"])
        r.update({"mean10":obs,"lo":lo,"hi":hi,"p":p,"contrast":con,"clo":clo,"chi":chi})
        pvals[hid]=p
    holm=holm_pass(pvals)

    ledger=[]; passes={}
    for h in HYP:
        hid=h["id"]; r=per[hid]; qx=r["qx"]; qmeans=r["valid_quarter_means"]
        share=sum(v>0 for v in qmeans.values())/len(qmeans)
        loo={q:float(qx.loc[qx["quarter"]!=q,"adj10"].mean()) for q in qmeans}
        mean5=float(np.mean(r["calm5"])) if len(r["calm5"]) else np.nan
        gates={
            "mean_calm_d10_positive":r["mean10"]>0,
            "calm_d10_ci_excludes_zero_above":r["lo"]>0,
            "holm_bonferroni_pass":holm[hid],
            "conditioner_contrast_positive":r["contrast"]>0,
            "contrast_ci_excludes_zero_above":r["clo"]>0,
            "mean_calm_d5_positive":np.isfinite(mean5) and mean5>0,
            "quarter_positive_share_ge_two_thirds":share>=0.6666666667,
            "leave_one_valid_quarter_out_positive":all(v>0 for v in loo.values()),
        }
        passed=all(gates.values()); passes[hid]=passed
        ledger.append({
            "hypothesis":hid,"factor":h["factor"],
            "valid_calm_d10_dates":r["valid_calm_d10_dates"],
            "valid_stressed_d10_dates":r["valid_stressed_d10_dates"],
            "mean_adjusted_calm_d10_ic":r["mean10"],
            "calm_d10_ci_low":r["lo"],"calm_d10_ci_high":r["hi"],
            "one_sided_p":r["p"],"holm_bonferroni_pass":holm[hid],
            "calm_minus_stressed_adjusted_d10_ic":r["contrast"],
            "contrast_ci_low":r["clo"],"contrast_ci_high":r["chi"],
            "mean_adjusted_calm_d5_ic":mean5,
            "positive_valid_quarter_share":share,
            "leave_one_valid_quarter_out_all_positive":all(v>0 for v in loo.values()),
            "all_holdout_gates_pass":passed,
            "failed_gates":"|".join(k for k,v in gates.items() if not v),
            "quarter_means_json":json.dumps(qmeans,sort_keys=True),
            "loo_means_json":json.dumps(loo,sort_keys=True),
        })
    n=sum(passes.values())
    status=(
        "V2_8_5_BACKWARD_HOLDOUT_REPLICATED_BOTH" if n==2 else
        "V2_8_5_BACKWARD_HOLDOUT_PARTIAL" if n==1 else
        "V2_8_5_BACKWARD_HOLDOUT_REJECTED"
    )
    led=pd.DataFrame(ledger)
    if write:
        daily.to_csv(DAILY_OUT,index=False,lineterminator="\n")
        led.to_csv(LEDGER_OUT,index=False,lineterminator="\n")
    final={
        "schema":"AI_CORE_EVID_V2_8_5_BACKWARD_HOLDOUT_FINAL_RECEIPT_V1",
        "version":"V2.8.5","status":status,
        "hypothesis_pass":passes,"passed_count":n,
        "panel_rows":len(panel),"panel_identity_sha256":ph,
        "source_snapshot_receipt_sha256":src["receipt_sha256"],
        "daily_metrics_sha256":sha_file(DAILY_OUT) if write else None,
        "hypothesis_ledger_sha256":sha_file(LEDGER_OUT) if write else None,
        "optional_stopping_used":False,
        "sample_modified_after_results":False,
        "V2_8_3_contract_changed":False,
        "setup_or_episode_emission_authorized":False,
        "live_authorized":False,
    }
    final["receipt_sha256"]=stable_json_sha(final)
    if write:
        FINAL_OUT.write_text(json.dumps(final,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return final

def self_test():
    tests=[]
    def ck(n,v): tests.append({"name":n,"pass":bool(v)})
    x=np.array([0.01,0.02,0.03,0.04]*20,dtype=float)
    ck("T01_bootstrap_deterministic",np.array_equal(circular_block_means(x,1,B_=200),circular_block_means(x,1,B_=200)))
    obs,lo,hi,p=primary_bootstrap(np.linspace(0.01,0.08,80),2851001)
    ck("T02_positive_primary",obs>0 and lo<=obs<=hi and 0<p<=1)
    con,clo,chi=contrast_bootstrap(np.full(80,0.05),np.full(40,0.01),2851101)
    ck("T03_positive_contrast",con>0 and clo>0 and chi>0)
    ck("T04_holm_pass",holm_pass({"H1":0.001,"H2":0.02})=={"H1":True,"H2":True})
    ck("T05_holm_stop",holm_pass({"H1":0.03,"H2":0.04})=={"H1":False,"H2":False})
    a=np.arange(50); ck("T06_rank_ic",abs(avg_rank_corr(a,a)-1)<1e-12)
    days=["2023-01-03","2023-01-04","2023-01-05","2023-01-06","2023-01-09","2023-01-10","2023-01-11","2023-01-12","2023-01-13","2023-01-16","2023-01-17"]
    tt=targets(days)
    ck("T07_target_exact_index",tt["2023-01-03"]==("2023-01-10","2023-01-17"))
    ck("T08_last_target_unavailable",tt["2023-01-17"]==(None,None))
    ck("T09_min_rows_frozen",MIN_ROWS==50)
    ck("T10_seed_family_frozen",HYP[0]["seed"]==2851001 and HYP[1]["contrast_seed"]==2851102)
    result={
      "schema":"AI_CORE_EVID_V2_8_5_LOCKED_HOLDOUT_EVALUATOR_SELFTEST_V1",
      "tests":tests,"passed":sum(t["pass"] for t in tests),"total":len(tests),
      "all_pass":all(t["pass"] for t in tests)
    }
    print(json.dumps(result,ensure_ascii=False,indent=2))
    if not result["all_pass"]: raise SystemExit(2)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("command",choices=["self-test","evaluate"])
    a=ap.parse_args()
    if a.command=="self-test":
        self_test()
    else:
        print(json.dumps(evaluate(True),ensure_ascii=False,indent=2))

if __name__=="__main__":
    main()
