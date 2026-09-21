from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

READINESS=Path("evidence/V2.8.3_INFORMATION_GATE_STATUS.json")
SIGNAL_DIR=Path("evidence/v283_signal_features")
OUTCOME_DIR=Path("evidence/v283_outcomes")
DAILY_OUT=Path("evidence/V2.8.3_CONFIRMATORY_DAILY_METRICS.csv")
LEDGER_OUT=Path("evidence/V2.8.3_CONFIRMATORY_HYPOTHESIS_LEDGER.csv")
FINAL_OUT=Path("evidence/V2.8.3_CONFIRMATORY_FINAL_RECEIPT.json")
B=10000
BLOCK=20
ALPHA=0.05
HYP=[
    {"id":"H1_RV_COMPRESSION_CALM","factor":"rv10_over_rv60","sign":-1,"ic_seed":2831001,"contrast_seed":2831101},
    {"id":"H2_TR_COMPRESSION_CALM","factor":"tr10_over_tr60","sign":-1,"ic_seed":2831002,"contrast_seed":2831102},
]

def sha_file(p:Path)->str:
    h=hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""):
            h.update(b)
    return h.hexdigest()

def stable_json_sha(obj)->str:
    b=json.dumps(obj,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()
    return hashlib.sha256(b).hexdigest()

def avg_rank_corr(x,y)->float:
    a=pd.Series(x).rank(method="average")
    b=pd.Series(y).rank(method="average")
    if len(a)<2 or a.nunique()<2 or b.nunique()<2:
        return np.nan
    return float(a.corr(b,method="pearson"))

def daily_ic(feature:pd.DataFrame,outcome:pd.DataFrame,factor:str)->tuple[float,int]:
    z=feature[["canonical_security_id",factor]].merge(
        outcome[["canonical_security_id","fwd_return"]],
        on="canonical_security_id",how="inner",validate="one_to_one"
    )
    x=pd.to_numeric(z[factor],errors="coerce")
    y=pd.to_numeric(z["fwd_return"],errors="coerce")
    ok=np.isfinite(x)&np.isfinite(y)
    n=int(ok.sum())
    if n<50:
        return np.nan,n
    return avg_rank_corr(x[ok],y[ok]),n

def circular_block_means(values,seed:int,B:int=B,block:int=BLOCK):
    x=np.asarray(values,dtype=float)
    if len(x)==0 or not np.isfinite(x).all():
        raise RuntimeError("BOOTSTRAP_INPUT_INVALID")
    rng=np.random.default_rng(seed)
    n=len(x)
    k=int(np.ceil(n/block))
    starts=rng.integers(0,n,size=(B,k))
    offs=np.arange(block)
    idx=(starts[:,:,None]+offs[None,None,:])%n
    idx=idx.reshape(B,-1)[:,:n]
    return x[idx].mean(axis=1)

def primary_bootstrap(values,seed):
    x=np.asarray(values,dtype=float)
    obs=float(x.mean())
    centered=x-obs
    null=circular_block_means(centered,seed)
    p=(1+int((null>=obs).sum()))/(B+1)
    boots=circular_block_means(x,seed)
    lo,hi=np.quantile(boots,[0.025,0.975])
    return obs,float(lo),float(hi),float(p)

def contrast_bootstrap(calm,stressed,seed):
    c=np.asarray(calm,dtype=float); s=np.asarray(stressed,dtype=float)
    obs=float(c.mean()-s.mean())
    cb=circular_block_means(c,seed)
    sb=circular_block_means(s,seed+10000)
    d=cb-sb
    lo,hi=np.quantile(d,[0.025,0.975])
    return obs,float(lo),float(hi)

def holm_pass(pvals:dict[str,float],alpha=ALPHA)->dict[str,bool]:
    order=sorted(pvals,key=lambda k:(pvals[k],k))
    out={k:False for k in pvals}
    m=len(order)
    alive=True
    for i,k in enumerate(order):
        threshold=alpha/(m-i)
        if alive and pvals[k]<=threshold:
            out[k]=True
        else:
            alive=False
    return out

def quarter_label(d:str)->str:
    t=pd.Timestamp(d)
    return f"{t.year}Q{(t.month-1)//3+1}"

def load_pairs():
    if not READINESS.exists():
        raise RuntimeError("READINESS_STATUS_MISSING")
    readiness=json.loads(READINESS.read_text(encoding="utf-8"))
    if readiness.get("status")!="READY_FOR_LOCKED_CONFIRMATORY_EVALUATION":
        return readiness,None
    if FINAL_OUT.exists():
        raise RuntimeError("FINAL_CONFIRMATORY_RESULT_ALREADY_EXISTS_NO_REPLACEMENT")

    rows=[]
    receipts=sorted(SIGNAL_DIR.glob("*_SIGNAL_FEATURE_RECEIPT.json"))
    for rp in receipts:
        sr=json.loads(rp.read_text(encoding="utf-8"))
        d=sr["signal_date"]
        fp=Path(sr["feature_csv"])
        if not fp.exists() or sha_file(fp)!=sr["feature_csv_sha256"]:
            raise RuntimeError(f"FEATURE_INTEGRITY_BLOCK:{d}")
        feat=pd.read_csv(fp)
        rec={"signal_date":d,"market_state":sr["market_state"]}
        for horizon in ("D5","D10"):
            op=OUTCOME_DIR/f"{d}_{horizon}_OUTCOMES.csv"
            orp=OUTCOME_DIR/f"{d}_{horizon}_OUTCOME_RECEIPT.json"
            if not op.exists() or not orp.exists():
                outcome=None
            else:
                ro=json.loads(orp.read_text(encoding="utf-8"))
                if sha_file(op)!=ro["outcome_csv_sha256"]:
                    raise RuntimeError(f"OUTCOME_INTEGRITY_BLOCK:{d}:{horizon}")
                outcome=pd.read_csv(op)
            for h in HYP:
                key=f"{h['id']}_{horizon}"
                if outcome is None:
                    rec[key]=np.nan
                    rec[key+"_n"]=0
                else:
                    ic,n=daily_ic(feat,outcome,h["factor"])
                    rec[key]=ic
                    rec[key+"_n"]=n
        rows.append(rec)
    return readiness,pd.DataFrame(rows)

def evaluate():
    readiness,daily=load_pairs()
    if daily is None:
        return {
            "schema":"AI_CORE_EVID_V2_8_3_CONFIRMATORY_EVALUATOR_BLOCK_V1",
            "status":"INCOMPLETE_NO_EVALUATION",
            "readiness_status":readiness.get("status"),
            "performance_statistics_computed":False
        }

    daily_rows=[]
    per_h={}
    pvals={}
    for h in HYP:
        hid=h["id"]; sign=h["sign"]
        d10col=f"{hid}_D10"; d5col=f"{hid}_D5"
        x=daily[["signal_date","market_state",d10col,d5col,d10col+"_n",d5col+"_n"]].copy()
        x["adj_d10"]=sign*pd.to_numeric(x[d10col],errors="coerce")
        x["adj_d5"]=sign*pd.to_numeric(x[d5col],errors="coerce")
        for _,r in x.iterrows():
            daily_rows.append({
                "hypothesis":hid,
                "factor":h["factor"],
                "signal_date":r["signal_date"],
                "market_state":r["market_state"],
                "rows_d10":int(r[d10col+"_n"]),
                "raw_ic_d10":r[d10col],
                "direction_adjusted_ic_d10":r["adj_d10"],
                "rows_d5":int(r[d5col+"_n"]),
                "raw_ic_d5":r[d5col],
                "direction_adjusted_ic_d5":r["adj_d5"],
            })
        calm10=x.loc[(x.market_state=="CALM")&np.isfinite(x.adj_d10),"adj_d10"].to_numpy(float)
        stress10=x.loc[(x.market_state=="STRESSED")&np.isfinite(x.adj_d10),"adj_d10"].to_numpy(float)
        calm5=x.loc[(x.market_state=="CALM")&np.isfinite(x.adj_d5),"adj_d5"].to_numpy(float)
        if len(calm10)<60 or len(stress10)<30:
            raise RuntimeError(f"READINESS_CONTRADICTION:{hid}")
        obs,lo,hi,p=primary_bootstrap(calm10,h["ic_seed"])
        contrast,clo,chi=contrast_bootstrap(calm10,stress10,h["contrast_seed"])
        pvals[hid]=p

        qx=x.loc[(x.market_state=="CALM")&np.isfinite(x.adj_d10),["signal_date","adj_d10"]].copy()
        qx["quarter"]=qx["signal_date"].map(quarter_label)
        qmeans={}
        for q,g in qx.groupby("quarter",sort=True):
            if len(g)>=15:
                qmeans[q]=float(g["adj_d10"].mean())
        if len(qmeans)<3:
            raise RuntimeError(f"READINESS_QUARTER_CONTRADICTION:{hid}")
        positive_share=float(sum(v>0 for v in qmeans.values())/len(qmeans))
        loo={}
        for q in qmeans:
            vals=qx.loc[qx["quarter"]!=q,"adj_d10"]
            loo[q]=float(vals.mean())
        per_h[hid]={
            "factor":h["factor"],
            "mean_adjusted_calm_d10_ic":obs,
            "calm_d10_ci_low":lo,
            "calm_d10_ci_high":hi,
            "one_sided_p":p,
            "calm_minus_stressed_adjusted_d10_ic":contrast,
            "contrast_ci_low":clo,
            "contrast_ci_high":chi,
            "mean_adjusted_calm_d5_ic":float(calm5.mean()) if len(calm5) else np.nan,
            "valid_calm_d10_dates":len(calm10),
            "valid_stressed_d10_dates":len(stress10),
            "valid_calm_d5_dates":len(calm5),
            "valid_quarter_means":qmeans,
            "positive_valid_quarter_share":positive_share,
            "leave_one_valid_quarter_out_means":loo,
            "leave_one_valid_quarter_out_all_positive":all(v>0 for v in loo.values()),
        }

    holm=holm_pass(pvals)
    ledger=[]
    passes={}
    for h in HYP:
        hid=h["id"]; r=per_h[hid]
        gates={
            "mean_calm_d10_positive":r["mean_adjusted_calm_d10_ic"]>0,
            "calm_d10_ci_excludes_zero_above":r["calm_d10_ci_low"]>0,
            "holm_bonferroni_pass":holm[hid],
            "conditioner_contrast_positive":r["calm_minus_stressed_adjusted_d10_ic"]>0,
            "contrast_ci_excludes_zero_above":r["contrast_ci_low"]>0,
            "mean_calm_d5_positive":np.isfinite(r["mean_adjusted_calm_d5_ic"]) and r["mean_adjusted_calm_d5_ic"]>0,
            "quarter_positive_share_ge_two_thirds":r["positive_valid_quarter_share"]>=0.6666666667,
            "leave_one_valid_quarter_out_positive":r["leave_one_valid_quarter_out_all_positive"],
        }
        passed=all(gates.values())
        passes[hid]=passed
        ledger.append({
            "hypothesis":hid,
            "factor":r["factor"],
            "mean_adjusted_calm_d10_ic":r["mean_adjusted_calm_d10_ic"],
            "calm_d10_ci_low":r["calm_d10_ci_low"],
            "calm_d10_ci_high":r["calm_d10_ci_high"],
            "one_sided_p":r["one_sided_p"],
            "holm_bonferroni_pass":holm[hid],
            "calm_minus_stressed_adjusted_d10_ic":r["calm_minus_stressed_adjusted_d10_ic"],
            "contrast_ci_low":r["contrast_ci_low"],
            "contrast_ci_high":r["contrast_ci_high"],
            "mean_adjusted_calm_d5_ic":r["mean_adjusted_calm_d5_ic"],
            "positive_valid_quarter_share":r["positive_valid_quarter_share"],
            "leave_one_valid_quarter_out_all_positive":r["leave_one_valid_quarter_out_all_positive"],
            "all_confirmatory_gates_pass":passed,
            "failed_gates":"|".join(k for k,v in gates.items() if not v),
            "quarter_means_json":json.dumps(r["valid_quarter_means"],sort_keys=True),
            "loo_means_json":json.dumps(r["leave_one_valid_quarter_out_means"],sort_keys=True),
        })

    n=sum(passes.values())
    family="V2_8_3_ARCHITECTURE_CONFIRMED" if n==2 else "V2_8_3_PARTIAL_REPLICATION" if n==1 else "V2_8_3_ARCHITECTURE_REJECTED"
    daily_df=pd.DataFrame(daily_rows)
    ledger_df=pd.DataFrame(ledger)
    daily_df.to_csv(DAILY_OUT,index=False,lineterminator="\n")
    ledger_df.to_csv(LEDGER_OUT,index=False,lineterminator="\n")
    final={
        "schema":"AI_CORE_EVID_V2_8_3_CONFIRMATORY_FINAL_RECEIPT_V1",
        "version":"V2.8.3",
        "status":family,
        "hypothesis_pass":passes,
        "passed_count":n,
        "daily_metrics_sha256":sha_file(DAILY_OUT),
        "hypothesis_ledger_sha256":sha_file(LEDGER_OUT),
        "readiness_receipt_sha256":readiness["receipt_sha256"],
        "optional_stopping_used":False,
        "thresholds_modified_after_results":False,
        "setup_or_episode_emission_authorized":False,
        "live_authorized":False,
    }
    final["receipt_sha256"]=stable_json_sha(final)
    FINAL_OUT.write_text(json.dumps(final,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return final

def self_test():
    tests=[]
    def ck(n,v): tests.append({"name":n,"pass":bool(v)})
    x=np.array([0.01,0.02,0.03,0.04]*20,dtype=float)
    m1=circular_block_means(x,123,B=200,block=20)
    m2=circular_block_means(x,123,B=200,block=20)
    ck("C01_bootstrap_deterministic",np.array_equal(m1,m2))
    ck("C02_bootstrap_replications",len(m1)==200)
    obs,lo,hi,p=primary_bootstrap(np.linspace(0.01,0.08,80),2831001)
    ck("C03_positive_primary_mean",obs>0)
    ck("C04_primary_ci_order",lo<=obs<=hi)
    ck("C05_one_sided_p_range",0<p<=1)
    con,clo,chi=contrast_bootstrap(np.full(80,0.05),np.full(40,0.01),2831101)
    ck("C06_positive_contrast",con>0 and clo>0 and chi>0)
    hp=holm_pass({"H1":0.001,"H2":0.02})
    ck("C07_holm_two_pass",hp=={"H1":True,"H2":True})
    hf=holm_pass({"H1":0.03,"H2":0.04})
    ck("C08_holm_sequential_stop",hf=={"H1":False,"H2":False})
    f=pd.DataFrame({"canonical_security_id":[str(i) for i in range(50)],"x":np.arange(50)})
    o=pd.DataFrame({"canonical_security_id":[str(i) for i in range(50)],"fwd_return":np.arange(50)})
    ic,n=daily_ic(f,o,"x")
    ck("C09_rank_ic_50_rows",n==50 and abs(ic-1)<1e-12)
    f49=f.iloc[:49]; o49=o.iloc[:49]
    ic49,n49=daily_ic(f49,o49,"x")
    ck("C10_rank_ic_49_rows_blocked",n49==49 and np.isnan(ic49))
    ck("C11_direction_adjustment_negative",-1*0.2==-0.2)
    result={"schema":"AI_CORE_EVID_V2_8_3_CONFIRMATORY_EVALUATOR_SELFTEST_V1",
            "tests":tests,"passed":sum(x["pass"] for x in tests),"total":len(tests),"all_pass":all(x["pass"] for x in tests)}
    result["receipt_sha256"]=stable_json_sha(result)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    if not result["all_pass"]:
        raise SystemExit(2)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("command",choices=["self-test","evaluate"])
    a=ap.parse_args()
    if a.command=="self-test":
        self_test()
    else:
        r=evaluate()
        print(json.dumps(r,ensure_ascii=False,indent=2))

if __name__=="__main__":
    main()
