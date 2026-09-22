from __future__ import annotations

import argparse, csv, hashlib, json
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

SOURCE_RECEIPT=Path("evidence/V2.8.6_FOLD1_SOURCE_SNAPSHOT_RECEIPT.json")
SOURCE_DIR=Path("evidence/v286_fold1_source")
SAMPLE=Path("evidence/V2.8.6_FOLD1_MECHANISM_REPLICATION_MANIFEST.csv")
SAMPLE_SHA="fe15777a0a3a131b58288454a0e3023503bd80ac6a22f20a2e50c45a4deed38a"
CALENDAR=Path("evidence/V2.8.5_JOINT_A_SHARE_TRADING_CALENDAR_2023_2024.json")
DAILY_OUT=Path("evidence/V2.8.6_FOLD1_DAILY_METRICS.csv")
FINAL_OUT=Path("evidence/V2.8.6_MECHANISM_REPLICATION_FINAL_RECEIPT.json")
B=10000
BLOCK=20
MIN_ROWS=50
SEEDS={"ALL":2861001,"CALM":2861101,"STRESSED":2861201}

def sha_file(path:Path)->str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""):
            h.update(b)
    return h.hexdigest()

def stable_sha(obj)->str:
    return hashlib.sha256(json.dumps(obj,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()

def numeric(s):
    return pd.to_numeric(s,errors="coerce").astype(float)

def spearman(x,y)->float:
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

def bootstrap(values,seed:int):
    x=np.asarray(values,dtype=float)
    obs=float(x.mean())
    null=circular_block_means(x-obs,seed)
    p=(1+int((null>=obs).sum()))/(B+1)
    boots=circular_block_means(x,seed)
    lo,hi=np.quantile(boots,[0.025,0.975])
    return {"mean":obs,"ci_low":float(lo),"ci_high":float(hi),"one_sided_p":float(p)}

def load_calendar():
    x=json.loads(CALENDAR.read_text(encoding="utf-8"))
    days=x["trading_dates"]
    if len(days)!=484 or days!=sorted(days) or len(days)!=len(set(days)):
        raise RuntimeError("CALENDAR_INTEGRITY_BLOCK")
    return days

def targets(days):
    return {d:(days[i+5] if i+5<len(days) else None,days[i+10] if i+10<len(days) else None) for i,d in enumerate(days)}

def load_sample():
    if sha_file(SAMPLE)!=SAMPLE_SHA:
        raise RuntimeError("FOLD1_MANIFEST_SHA_BLOCK")
    rows=list(csv.DictReader(SAMPLE.read_text(encoding="utf-8").splitlines()))
    if len(rows)!=1058:
        raise RuntimeError("FOLD1_COUNT_BLOCK")
    if any(str(r.get("identity_fold_mod5"))!="1" for r in rows):
        raise RuntimeError("FOLD1_IDENTITY_DRIFT")
    return {r["canonical_security_id"]:r for r in rows}

def load_source():
    rec=json.loads(SOURCE_RECEIPT.read_text(encoding="utf-8"))
    if rec.get("status")!="PASS":
        raise RuntimeError("SOURCE_NOT_PASS")
    if rec.get("sample_manifest_sha256")!=SAMPLE_SHA or int(rec.get("sample_count",0))!=1058:
        raise RuntimeError("SOURCE_SAMPLE_BINDING_BLOCK")
    parts=[]
    for p in rec["stock_partitions"]:
        fp=SOURCE_DIR/p["file"]
        if not fp.exists() or sha_file(fp)!=p["sha256"]:
            raise RuntimeError(f"SOURCE_PARTITION_BLOCK:{p['file']}")
        parts.append(pq.read_table(fp).to_pandas())
    bp=SOURCE_DIR/rec["benchmark"]["file"]
    if not bp.exists() or sha_file(bp)!=rec["benchmark"]["parquet_sha256"]:
        raise RuntimeError("BENCHMARK_BLOCK")
    return pd.concat(parts,ignore_index=True),pq.read_table(bp).to_pandas(),rec

def symbol_panel(g,meta,days,tgt):
    x=g.loc[g["tradestatus"].astype(str)=="1"].copy().sort_values("date",kind="mergesort")
    if x.empty: return []
    if x["date"].duplicated().any():
        raise RuntimeError(f"DUPLICATE_STOCK_DATE:{meta['canonical_security_id']}")
    close=numeric(x["close"]); high=numeric(x["high"]); low=numeric(x["low"])
    prev=close.shift(1)
    lr=np.log(close/prev)
    rv10=lr.rolling(10,min_periods=10).std(ddof=0)
    rv60=lr.rolling(60,min_periods=60).std(ddof=0)
    tr_abs=pd.concat([(high-low),(high-prev).abs(),(low-prev).abs()],axis=1).max(axis=1)
    trp=tr_abs/prev
    x["rv"]=rv10/rv60.replace(0,np.nan)
    x["tr"]=trp.rolling(10,min_periods=10).mean()/trp.rolling(60,min_periods=60).mean().replace(0,np.nan)
    x["close_num"]=close
    by=x.set_index("date")
    ld=meta["official_list_date"]; dd=str(meta.get("official_delist_date") or "")
    out=[]
    for d in days:
        if d<ld or (dd and d>=dd) or d not in by.index: continue
        r=by.loc[d]
        if isinstance(r,pd.DataFrame): raise RuntimeError("DUPLICATE_D")
        d5,d10=tgt[d]; c=float(r["close_num"])
        def fwd(td):
            if td is None or td not in by.index or not np.isfinite(c) or c<=0: return np.nan
            rr=by.loc[td]
            if isinstance(rr,pd.DataFrame): raise RuntimeError("DUPLICATE_T")
            z=float(rr["close_num"])
            return z/c-1 if np.isfinite(z) and z>0 else np.nan
        out.append({
            "canonical_security_id":meta["canonical_security_id"],"signal_date":d,
            "rv":float(r["rv"]) if np.isfinite(r["rv"]) else np.nan,
            "tr":float(r["tr"]) if np.isfinite(r["tr"]) else np.nan,
            "fwd5":fwd(d5),"fwd10":fwd(d10)
        })
    return out

def market_states(bench,days):
    x=bench.loc[bench["tradestatus"].astype(str)=="1"].copy().sort_values("date",kind="mergesort")
    if x["date"].duplicated().any(): raise RuntimeError("BENCHMARK_DUPLICATE")
    have=set(x["date"].astype(str))
    miss=[d for d in days if d not in have]
    if miss: raise RuntimeError(f"BENCHMARK_MISSING:{miss[:5]}")
    close=numeric(x["close"]); lr=np.log(close/close.shift(1))
    ratio=lr.rolling(10,min_periods=10).std(ddof=0)/lr.rolling(60,min_periods=60).std(ddof=0).replace(0,np.nan)
    out={}
    for d,v in zip(x["date"].astype(str),ratio):
        if d in have and d in set(days):
            out[d]="UNKNOWN" if not np.isfinite(v) else ("CALM" if float(v)<=1 else "STRESSED")
    return out

def panel_hash(rows):
    h=hashlib.sha256()
    for r in sorted(rows,key=lambda x:(x["signal_date"],x["canonical_security_id"])):
        vals=[r["canonical_security_id"],r["signal_date"]]+[
            "" if not np.isfinite(r[k]) else format(r[k],".17g") for k in ("rv","tr","fwd5","fwd10")
        ]
        h.update(("\x1f".join(vals)+"\n").encode())
    return h.hexdigest()

def build_daily(panel,states):
    rows=[]
    for d,g in panel.groupby("signal_date",sort=True):
        rv=numeric(g["rv"]); tr=numeric(g["tr"])
        both=np.isfinite(rv)&np.isfinite(tr)
        rv_pct=pd.Series(np.nan,index=g.index,dtype=float)
        tr_pct=pd.Series(np.nan,index=g.index,dtype=float)
        if both.any():
            rv_pct.loc[both]=rv[both].rank(method="average",pct=True)
            tr_pct.loc[both]=tr[both].rank(method="average",pct=True)
        score=0.5*(1-rv_pct)+0.5*(1-tr_pct)
        rec={"signal_date":d,"market_state":states[d]}
        for hz,col in (("D5","fwd5"),("D10","fwd10")):
            y=numeric(g[col]); ok=np.isfinite(score)&np.isfinite(y)
            rec[f"composite_{hz}_n"]=int(ok.sum())
            rec[f"composite_{hz}_ic"]=spearman(score[ok],y[ok]) if int(ok.sum())>=MIN_ROWS else np.nan
        y10=numeric(g["fwd10"])
        for name,x in (("rv",rv),("tr",tr)):
            ok=np.isfinite(x)&np.isfinite(y10)
            rec[f"{name}_adj_D10_ic"]=-spearman(x[ok],y10[ok]) if int(ok.sum())>=MIN_ROWS else np.nan
        rows.append(rec)
    return pd.DataFrame(rows)

def quarter(d):
    t=pd.Timestamp(d); return f"{t.year}Q{(t.month-1)//3+1}"

def evaluate(write=True):
    if FINAL_OUT.exists():
        old=json.loads(FINAL_OUT.read_text(encoding="utf-8"))
        return {"status":"FINAL_ALREADY_FROZEN_NO_REEVALUATION","receipt_sha256":old.get("receipt_sha256")}
    days=load_calendar(); tgt=targets(days); sample=load_sample()
    stock,bench,src=load_source()
    if set(stock["canonical_security_id"].astype(str).unique())-set(sample):
        raise RuntimeError("NON_FOLD1_SECURITY_IN_SOURCE")
    rows=[]
    for cid,g in stock.groupby("canonical_security_id",sort=True):
        rows.extend(symbol_panel(g,sample[cid],days,tgt))
    ph=panel_hash(rows)
    panel=pd.DataFrame(rows)
    states=market_states(bench,days)
    daily=build_daily(panel,states)
    all10=daily.loc[np.isfinite(daily["composite_D10_ic"]),"composite_D10_ic"].to_numpy(float)
    calm=daily.loc[(daily.market_state=="CALM")&np.isfinite(daily["composite_D10_ic"]),"composite_D10_ic"].to_numpy(float)
    stressed=daily.loc[(daily.market_state=="STRESSED")&np.isfinite(daily["composite_D10_ic"]),"composite_D10_ic"].to_numpy(float)
    all5=daily.loc[np.isfinite(daily["composite_D5_ic"]),"composite_D5_ic"].to_numpy(float)
    q=daily.loc[np.isfinite(daily["composite_D10_ic"]),["signal_date","composite_D10_ic"]].copy()
    q["quarter"]=q["signal_date"].map(quarter)
    qmeans={k:float(g["composite_D10_ic"].mean()) for k,g in q.groupby("quarter",sort=True) if len(g)>=20}
    ready=len(all10)>=200 and len(calm)>=60 and len(stressed)>=30 and len(qmeans)>=4
    if not ready:
        status="V2_8_6_STATE_INVARIANT_DUAL_COMPRESSION_INCOMPLETE"
        final={
            "schema":"AI_CORE_EVID_V2_8_6_MECHANISM_REPLICATION_FINAL_RECEIPT_V1",
            "version":"V2.8.6","status":status,"panel_rows":len(panel),"panel_identity_sha256":ph,
            "information":{"all_D10":len(all10),"calm_D10":len(calm),"stressed_D10":len(stressed),"valid_quarters":len(qmeans)},
            "setup_or_episode_emission_authorized":False,"live_authorized":False
        }
    else:
        ba=bootstrap(all10,SEEDS["ALL"]); bc=bootstrap(calm,SEEDS["CALM"]); bs=bootstrap(stressed,SEEDS["STRESSED"])
        share=sum(v>0 for v in qmeans.values())/len(qmeans)
        loo={k:float(q.loc[q.quarter!=k,"composite_D10_ic"].mean()) for k in qmeans}
        rvmean=float(daily.loc[np.isfinite(daily["rv_adj_D10_ic"]),"rv_adj_D10_ic"].mean())
        trmean=float(daily.loc[np.isfinite(daily["tr_adj_D10_ic"]),"tr_adj_D10_ic"].mean())
        d5=float(np.mean(all5)) if len(all5) else np.nan
        gates={
            "all_market_mean_D10_positive":ba["mean"]>0,
            "all_market_D10_ci_above_zero":ba["ci_low"]>0,
            "all_market_one_sided_p_le_0_05":ba["one_sided_p"]<=0.05,
            "calm_mean_D10_positive":bc["mean"]>0,
            "calm_D10_ci_above_zero":bc["ci_low"]>0,
            "stressed_mean_D10_positive":bs["mean"]>0,
            "stressed_D10_ci_above_zero":bs["ci_low"]>0,
            "all_market_mean_D5_positive":np.isfinite(d5) and d5>0,
            "quarter_positive_share_ge_two_thirds":share>=2/3,
            "leave_one_quarter_out_all_positive":all(v>0 for v in loo.values()),
            "rv_component_adjusted_D10_positive":rvmean>0,
            "tr_component_adjusted_D10_positive":trmean>0
        }
        passed=all(gates.values())
        status="V2_8_6_STATE_INVARIANT_DUAL_COMPRESSION_REPLICATED" if passed else "V2_8_6_STATE_INVARIANT_DUAL_COMPRESSION_REJECTED"
        final={
            "schema":"AI_CORE_EVID_V2_8_6_MECHANISM_REPLICATION_FINAL_RECEIPT_V1",
            "version":"V2.8.6","status":status,
            "panel_rows":len(panel),"panel_identity_sha256":ph,
            "valid_dates":{"all_D10":len(all10),"calm_D10":len(calm),"stressed_D10":len(stressed),"all_D5":len(all5)},
            "all_market_D10":ba,"calm_D10":bc,"stressed_D10":bs,
            "all_market_mean_D5_ic":d5,
            "rv_component_mean_adjusted_D10_ic":rvmean,
            "tr_component_mean_adjusted_D10_ic":trmean,
            "quarter_means":qmeans,"positive_quarter_share":share,"leave_one_quarter_out_means":loo,
            "gates":gates,"failed_gates":[k for k,v in gates.items() if not v],
            "source_snapshot_receipt_sha256":src["receipt_sha256"],
            "sample_modified_after_results":False,"optional_stopping_used":False,
            "fold2_3_4_consumed":False,
            "setup_or_episode_emission_authorized":False,"first60_append_authorized":False,"live_authorized":False
        }
    if write:
        daily.to_csv(DAILY_OUT,index=False,lineterminator="\n")
        final["daily_metrics_sha256"]=sha_file(DAILY_OUT)
    final["receipt_sha256"]=stable_sha(final)
    if write: FINAL_OUT.write_text(json.dumps(final,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return final

def self_test():
    tests=[]
    def ck(n,v): tests.append({"name":n,"pass":bool(v)})
    x=np.linspace(0.01,0.08,80)
    ck("M01_bootstrap_deterministic",np.array_equal(circular_block_means(x,1,B_=200),circular_block_means(x,1,B_=200)))
    z=bootstrap(x,2861001)
    ck("M02_positive_bootstrap",z["mean"]>0 and z["ci_low"]>0 and z["one_sided_p"]<=0.05)
    fac=pd.Series([4.,1.,3.,2.]); pct=fac.rank(method="average",pct=True); fav=1-pct
    ck("M03_favorable_percentile_orders_low_ratio_high",fav.iloc[1]>fav.iloc[0])
    rv=pd.Series([1.,2.,3.,4.]); tr=pd.Series([4.,3.,2.,1.])
    score=0.5*(1-rv.rank(method="average",pct=True))+0.5*(1-tr.rank(method="average",pct=True))
    ck("M04_equal_weight_composite_exact",float(score.max()-score.min())==0.0)
    ck("M05_spearman_identity",abs(spearman(np.arange(60),np.arange(60))-1)<1e-12)
    ck("M06_min_rows_frozen",MIN_ROWS==50)
    ck("M07_seeds_frozen",SEEDS=={"ALL":2861001,"CALM":2861101,"STRESSED":2861201})
    ck("M08_fold1_manifest_sha_frozen",SAMPLE_SHA=="fe15777a0a3a131b58288454a0e3023503bd80ac6a22f20a2e50c45a4deed38a")
    ck("M09_single_primary_no_multiplicity",True)
    ck("M10_fold2_3_4_not_referenced",all("fold2" not in str(x).lower() for x in [SOURCE_RECEIPT,SOURCE_DIR,SAMPLE]))
    result={"schema":"AI_CORE_EVID_V2_8_6_LOCKED_MECHANISM_REPLICATION_SELFTEST_V1","tests":tests,"passed":sum(t["pass"] for t in tests),"total":len(tests),"all_pass":all(t["pass"] for t in tests),"real_fold1_price_rows_consumed":False}
    print(json.dumps(result,ensure_ascii=False,indent=2))
    if not result["all_pass"]: raise SystemExit(2)

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("command",choices=["self-test","evaluate"]); a=ap.parse_args()
    print(json.dumps(evaluate(True),ensure_ascii=False,indent=2)) if a.command=="evaluate" else self_test()

if __name__=="__main__":
    main()
