from __future__ import annotations

import argparse,csv,hashlib,json
from pathlib import Path
import numpy as np
import pandas as pd
import pyarrow.parquet as pq

SOURCE_RECEIPT=Path("evidence/V2.8.7_FOLD2_SOURCE_SNAPSHOT_RECEIPT.json")
SOURCE_DIR=Path("evidence/v287_fold2_source")
SAMPLE=Path("evidence/V2.8.7_FOLD2_SETUP_SHAPE_MANIFEST.csv")
SAMPLE_SHA="79b6a4c752a22a16f6ec7167dfb1e6b007473229d7ec6729fb03a15b3ba0fa9a"
CALENDAR=Path("evidence/V2.8.5_JOINT_A_SHARE_TRADING_CALENDAR_2023_2024.json")
DAILY_OUT=Path("evidence/V2.8.7_FOLD2_Q5_SETUP_SHAPE_DAILY_METRICS.csv")
FINAL_OUT=Path("evidence/V2.8.7_Q5_SETUP_SHAPE_FINAL_RECEIPT.json")
B=10000
BLOCK=20
MIN_SIDE=50
SEEDS={"ALL":2871001,"CALM":2871101,"STRESSED":2871201}

def sha_file(path):
    h=hashlib.sha256()
    with Path(path).open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""): h.update(b)
    return h.hexdigest()

def stable_sha(obj):
    return hashlib.sha256(json.dumps(obj,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()

def numeric(s): return pd.to_numeric(s,errors="coerce").astype(float)

def circular_block_means(values,seed,B_=B,block=BLOCK):
    x=np.asarray(values,dtype=float)
    if len(x)==0 or not np.isfinite(x).all(): raise RuntimeError("BOOTSTRAP_INPUT_INVALID")
    rng=np.random.default_rng(seed); n=len(x); k=int(np.ceil(n/block))
    starts=rng.integers(0,n,size=(B_,k)); offs=np.arange(block)
    idx=(starts[:,:,None]+offs[None,None,:])%n
    idx=idx.reshape(B_,-1)[:,:n]
    return x[idx].mean(axis=1)

def bootstrap(values,seed):
    x=np.asarray(values,dtype=float); obs=float(x.mean())
    null=circular_block_means(x-obs,seed)
    p=(1+int((null>=obs).sum()))/(B+1)
    boots=circular_block_means(x,seed)
    lo,hi=np.quantile(boots,[0.025,0.975])
    return {"mean":obs,"ci_low":float(lo),"ci_high":float(hi),"one_sided_p":float(p)}

def load_calendar():
    obj=json.loads(CALENDAR.read_text(encoding="utf-8")); days=obj["trading_dates"]
    if len(days)!=484 or days!=sorted(days) or len(days)!=len(set(days)): raise RuntimeError("CALENDAR_BLOCK")
    return days

def targets(days):
    return {d:(days[i+5] if i+5<len(days) else None,days[i+10] if i+10<len(days) else None) for i,d in enumerate(days)}

def load_sample():
    if sha_file(SAMPLE)!=SAMPLE_SHA: raise RuntimeError("FOLD2_MANIFEST_SHA_BLOCK")
    rows=list(csv.DictReader(SAMPLE.read_text(encoding="utf-8").splitlines()))
    if len(rows)!=1048: raise RuntimeError("FOLD2_COUNT_BLOCK")
    if any(str(r.get("identity_fold_mod5"))!="2" for r in rows): raise RuntimeError("FOLD2_IDENTITY_DRIFT")
    return {r["canonical_security_id"]:r for r in rows}

def load_source():
    rec=json.loads(SOURCE_RECEIPT.read_text(encoding="utf-8"))
    if rec.get("status")!="PASS" or rec.get("sample_manifest_sha256")!=SAMPLE_SHA or int(rec.get("sample_count",0))!=1048:
        raise RuntimeError("SOURCE_BINDING_BLOCK")
    parts=[]
    for p in rec["stock_partitions"]:
        fp=SOURCE_DIR/p["file"]
        if not fp.exists() or sha_file(fp)!=p["sha256"]: raise RuntimeError(f"SOURCE_PARTITION_BLOCK:{p['file']}")
        parts.append(pq.read_table(fp).to_pandas())
    bp=SOURCE_DIR/rec["benchmark"]["file"]
    if not bp.exists() or sha_file(bp)!=rec["benchmark"]["parquet_sha256"]: raise RuntimeError("BENCHMARK_BLOCK")
    return pd.concat(parts,ignore_index=True),pq.read_table(bp).to_pandas(),rec

def symbol_panel(g,meta,days,tgt):
    x=g.loc[g["tradestatus"].astype(str)=="1"].copy().sort_values("date",kind="mergesort")
    if x.empty: return []
    if x["date"].duplicated().any(): raise RuntimeError(f"DUPLICATE_STOCK_DATE:{meta['canonical_security_id']}")
    close=numeric(x["close"]); high=numeric(x["high"]); low=numeric(x["low"]); prev=close.shift(1)
    lr=np.log(close/prev)
    rv=lr.rolling(10,min_periods=10).std(ddof=0)/lr.rolling(60,min_periods=60).std(ddof=0).replace(0,np.nan)
    tr_abs=pd.concat([(high-low),(high-prev).abs(),(low-prev).abs()],axis=1).max(axis=1)
    trp=tr_abs/prev
    tr=trp.rolling(10,min_periods=10).mean()/trp.rolling(60,min_periods=60).mean().replace(0,np.nan)
    x["rv"]=rv; x["tr"]=tr; x["close_num"]=close; by=x.set_index("date")
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
    have=set(x["date"].astype(str)); miss=[d for d in days if d not in have]
    if miss: raise RuntimeError(f"BENCHMARK_MISSING:{miss[:5]}")
    close=numeric(x["close"]); lr=np.log(close/close.shift(1))
    ratio=lr.rolling(10,min_periods=10).std(ddof=0)/lr.rolling(60,min_periods=60).std(ddof=0).replace(0,np.nan)
    wanted=set(days); out={}
    for d,v in zip(x["date"].astype(str),ratio):
        if d in wanted: out[d]="UNKNOWN" if not np.isfinite(v) else ("CALM" if float(v)<=1 else "STRESSED")
    return out

def panel_hash(rows):
    h=hashlib.sha256()
    for r in sorted(rows,key=lambda x:(x["signal_date"],x["canonical_security_id"])):
        vals=[r["canonical_security_id"],r["signal_date"]]+["" if not np.isfinite(r[k]) else format(r[k],".17g") for k in ("rv","tr","fwd5","fwd10")]
        h.update(("\x1f".join(vals)+"\n").encode())
    return h.hexdigest()

def add_score_and_quintile(g):
    rv=numeric(g["rv"]); tr=numeric(g["tr"]); both=np.isfinite(rv)&np.isfinite(tr)
    score=pd.Series(np.nan,index=g.index,dtype=float)
    if both.any():
        rvfav=1-rv[both].rank(method="average",pct=True)
        trfav=1-tr[both].rank(method="average",pct=True)
        score.loc[both]=0.5*rvfav+0.5*trfav
    pct=pd.Series(np.nan,index=g.index,dtype=float)
    ok=np.isfinite(score)
    if ok.any(): pct.loc[ok]=score[ok].rank(method="average",pct=True)
    q=pd.Series(np.nan,index=g.index,dtype=float)
    q.loc[ok & (pct<=0.20)]=1
    q.loc[ok & (pct>0.20) & (pct<=0.40)]=2
    q.loc[ok & (pct>0.40) & (pct<=0.60)]=3
    q.loc[ok & (pct>0.60) & (pct<=0.80)]=4
    q.loc[ok & (pct>0.80)]=5
    return score,pct,q

def daily_metrics(panel,states):
    rows=[]
    for d,g in panel.groupby("signal_date",sort=True):
        score,pct,q=add_score_and_quintile(g)
        rec={"signal_date":d,"market_state":states[d]}
        for hz,col in (("D5","fwd5"),("D10","fwd10")):
            y=numeric(g[col]); valid=np.isfinite(score)&np.isfinite(y)
            q1=valid&(q==1); q5=valid&(q==5)
            rec[f"{hz}_Q1_n"]=int(q1.sum()); rec[f"{hz}_Q5_n"]=int(q5.sum())
            if int(q1.sum())>=MIN_SIDE and int(q5.sum())>=MIN_SIDE:
                q1m=float(y[q1].mean()); q5m=float(y[q5].mean()); allm=float(y[valid].mean())
                rec[f"{hz}_Q1_mean"]=q1m; rec[f"{hz}_Q5_mean"]=q5m
                rec[f"{hz}_Q5_minus_Q1"]=q5m-q1m
                rec[f"{hz}_Q5_excess_all"]=q5m-allm
            else:
                rec[f"{hz}_Q1_mean"]=np.nan; rec[f"{hz}_Q5_mean"]=np.nan
                rec[f"{hz}_Q5_minus_Q1"]=np.nan; rec[f"{hz}_Q5_excess_all"]=np.nan
            for qi in range(1,6):
                m=valid&(q==qi)
                rec[f"{hz}_Q{qi}_mean"]=float(y[m].mean()) if int(m.sum())>=MIN_SIDE else np.nan
        rows.append(rec)
    return pd.DataFrame(rows)

def quarter(d):
    t=pd.Timestamp(d); return f"{t.year}Q{(t.month-1)//3+1}"

def evaluate(write=True):
    if FINAL_OUT.exists():
        old=json.loads(FINAL_OUT.read_text(encoding="utf-8"))
        return {"status":"FINAL_ALREADY_FROZEN_NO_REEVALUATION","receipt_sha256":old.get("receipt_sha256")}
    days=load_calendar(); tgt=targets(days); sample=load_sample(); stock,bench,src=load_source()
    if set(stock["canonical_security_id"].astype(str).unique())-set(sample): raise RuntimeError("NON_FOLD2_SECURITY_IN_SOURCE")
    rows=[]
    for cid,g in stock.groupby("canonical_security_id",sort=True): rows.extend(symbol_panel(g,sample[cid],days,tgt))
    ph=panel_hash(rows); panel=pd.DataFrame(rows); states=market_states(bench,days); daily=daily_metrics(panel,states)
    all10=daily.loc[np.isfinite(daily["D10_Q5_minus_Q1"]),"D10_Q5_minus_Q1"].to_numpy(float)
    calm=daily.loc[(daily.market_state=="CALM")&np.isfinite(daily["D10_Q5_minus_Q1"]),"D10_Q5_minus_Q1"].to_numpy(float)
    stressed=daily.loc[(daily.market_state=="STRESSED")&np.isfinite(daily["D10_Q5_minus_Q1"]),"D10_Q5_minus_Q1"].to_numpy(float)
    all5=daily.loc[np.isfinite(daily["D5_Q5_minus_Q1"]),"D5_Q5_minus_Q1"].to_numpy(float)
    q5ex=daily.loc[np.isfinite(daily["D10_Q5_excess_all"]),"D10_Q5_excess_all"].to_numpy(float)
    qdf=daily.loc[np.isfinite(daily["D10_Q5_minus_Q1"]),["signal_date","D10_Q5_minus_Q1"]].copy()
    qdf["quarter"]=qdf["signal_date"].map(quarter)
    qmeans={k:float(g["D10_Q5_minus_Q1"].mean()) for k,g in qdf.groupby("quarter",sort=True) if len(g)>=20}
    ready=len(all10)>=200 and len(calm)>=60 and len(stressed)>=30 and len(qmeans)>=4
    if not ready:
        final={"schema":"AI_CORE_EVID_V2_8_7_Q5_SETUP_SHAPE_FINAL_RECEIPT_V1","version":"V2.8.7","status":"V2_8_7_Q5_SETUP_SHAPE_INCOMPLETE","panel_rows":len(panel),"panel_identity_sha256":ph,"information":{"all_D10":len(all10),"calm_D10":len(calm),"stressed_D10":len(stressed),"valid_quarters":len(qmeans)},"setup_emission_authorized":False,"live_authorized":False}
    else:
        ba=bootstrap(all10,SEEDS["ALL"]); bc=bootstrap(calm,SEEDS["CALM"]); bs=bootstrap(stressed,SEEDS["STRESSED"])
        share=sum(v>0 for v in qmeans.values())/len(qmeans)
        loo={k:float(qdf.loc[qdf.quarter!=k,"D10_Q5_minus_Q1"].mean()) for k in qmeans}
        d5=float(np.mean(all5)); ex=float(np.mean(q5ex))
        aggregate_quintile_means={str(qi):float(daily.loc[np.isfinite(daily[f"D10_Q{qi}_mean"]),f"D10_Q{qi}_mean"].mean()) for qi in range(1,6)}
        q5_highest=aggregate_quintile_means["5"]>max(aggregate_quintile_means[str(qi)] for qi in range(1,5))
        gates={
          "all_market_D10_spread_positive":ba["mean"]>0,
          "all_market_D10_ci_above_zero":ba["ci_low"]>0,
          "all_market_one_sided_p_le_0_05":ba["one_sided_p"]<=0.05,
          "calm_D10_spread_positive":bc["mean"]>0,
          "calm_D10_ci_above_zero":bc["ci_low"]>0,
          "stressed_D10_spread_positive":bs["mean"]>0,
          "stressed_D10_ci_above_zero":bs["ci_low"]>0,
          "all_market_D5_spread_positive":d5>0,
          "Q5_D10_excess_all_positive":ex>0,
          "Q5_highest_aggregate_D10_quintile_mean":q5_highest,
          "positive_quarter_share_ge_two_thirds":share>=2/3,
          "leave_one_quarter_out_all_positive":all(v>0 for v in loo.values())
        }
        passed=all(gates.values())
        final={
          "schema":"AI_CORE_EVID_V2_8_7_Q5_SETUP_SHAPE_FINAL_RECEIPT_V1","version":"V2.8.7",
          "status":"V2_8_7_Q5_SETUP_SHAPE_SUPPORTED" if passed else "V2_8_7_Q5_SETUP_SHAPE_REJECTED",
          "panel_rows":len(panel),"panel_identity_sha256":ph,
          "valid_dates":{"all_D10":len(all10),"calm_D10":len(calm),"stressed_D10":len(stressed),"all_D5":len(all5)},
          "all_market_D10_Q5_minus_Q1":ba,"calm_D10_Q5_minus_Q1":bc,"stressed_D10_Q5_minus_Q1":bs,
          "all_market_mean_D5_Q5_minus_Q1":d5,"all_market_mean_D10_Q5_excess_all":ex,
          "aggregate_D10_quintile_means":aggregate_quintile_means,
          "quarter_means":qmeans,"positive_quarter_share":share,"leave_one_quarter_out_means":loo,
          "gates":gates,"failed_gates":[k for k,v in gates.items() if not v],
          "source_snapshot_receipt_sha256":src["receipt_sha256"],
          "sample_modified_after_results":False,"optional_stopping_used":False,"alternate_threshold_search_used":False,
          "fold3_4_consumed":False,"setup_emission_authorized":False,"first60_append_authorized":False,"episode_emission_authorized":False,"live_authorized":False
        }
    if write:
        daily.to_csv(DAILY_OUT,index=False,lineterminator="\n"); final["daily_metrics_sha256"]=sha_file(DAILY_OUT)
    final["receipt_sha256"]=stable_sha(final)
    if write: FINAL_OUT.write_text(json.dumps(final,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return final

def self_test():
    tests=[]
    def ck(n,v): tests.append({"name":n,"pass":bool(v)})
    x=np.linspace(0.01,0.08,80); z=bootstrap(x,2871001)
    ck("S01_bootstrap_deterministic",np.array_equal(circular_block_means(x,7,B_=200),circular_block_means(x,7,B_=200)))
    ck("S02_positive_bootstrap",z["mean"]>0 and z["ci_low"]>0 and z["one_sided_p"]<=0.05)
    g=pd.DataFrame({"rv":np.arange(100,0,-1,dtype=float),"tr":np.arange(100,0,-1,dtype=float)})
    score,pct,q=add_score_and_quintile(g)
    ck("S03_fixed_quintiles",int((q==1).sum())==20 and int((q==5).sum())==20)
    y=pd.Series(np.arange(100,dtype=float))
    ck("S04_Q5_shape_positive",float(y[q==5].mean()-y[q==1].mean())>0)
    means={"1":0.0,"2":0.01,"3":0.02,"4":0.03,"5":0.05}
    ck("S05_Q5_highest_rule",means["5"]>max(means[str(i)] for i in range(1,5)))
    ck("S06_min_side_frozen",MIN_SIDE==50)
    ck("S07_seeds_frozen",SEEDS=={"ALL":2871001,"CALM":2871101,"STRESSED":2871201})
    ck("S08_fold2_manifest_sha_frozen",SAMPLE_SHA=="79b6a4c752a22a16f6ec7167dfb1e6b007473229d7ec6729fb03a15b3ba0fa9a")
    ck("S09_no_threshold_grid",True)
    ck("S10_fold3_4_not_referenced",all("fold3" not in str(x).lower() and "fold4" not in str(x).lower() for x in [SOURCE_RECEIPT,SOURCE_DIR,SAMPLE]))
    result={"schema":"AI_CORE_EVID_V2_8_7_LOCKED_Q5_SETUP_SHAPE_SELFTEST_V1","tests":tests,"passed":sum(t["pass"] for t in tests),"total":len(tests),"all_pass":all(t["pass"] for t in tests),"real_fold2_price_rows_consumed":False}
    print(json.dumps(result,ensure_ascii=False,indent=2))
    if not result["all_pass"]: raise SystemExit(2)

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("command",choices=["self-test","evaluate"]); a=ap.parse_args()
    print(json.dumps(evaluate(True),ensure_ascii=False,indent=2)) if a.command=="evaluate" else self_test()
if __name__=="__main__": main()
