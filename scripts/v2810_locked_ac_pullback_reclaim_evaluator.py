from __future__ import annotations
import argparse,csv,hashlib,json
from pathlib import Path
import numpy as np,pandas as pd,pyarrow.parquet as pq
from v280_scale_invariant_features import build_features

H=Path("evidence/V2.8.10_INDEPENDENT_ENTRY_MECHANISM_DISCOVERY_GATE.json")
E=Path("evidence/V2.8.10_LOCKED_AC_PULLBACK_RECLAIM_EVALUATION_GATE.json")
CAL=Path("evidence/V2.8.5_JOINT_A_SHARE_TRADING_CALENDAR_2023_2024.json")
HS="AI_CORE_EVID_V2_8_10_INDEPENDENT_ENTRY_MECHANISM_DISCOVERY_GATE_V1"
ES="AI_CORE_EVID_V2_8_10_LOCKED_AC_PULLBACK_RECLAIM_EVALUATION_GATE_V1"
CID="AC_MA20_PULLBACK_RECLAIM_V1"
OUTE=Path("evidence/V2.8.10_AC_EVENT_LEDGER.csv")
OUTD=Path("evidence/V2.8.10_AC_DAILY_METRICS.csv")
OUTF=Path("evidence/V2.8.10_AC_RESEARCH_FINAL_RECEIPT.json")
MIN_CTL=20; BOOT=10000; SEEDS={0:2810000,1:2810001,2:2810002}
MIN={ "events":200,"secs":100,"dates":80,"maxshare":.10,"d10e":150,"d5e":150,"d10d":60,"d5d":60,"incd":40,"quarters":4}
F={
0:{"sample":Path("evidence/V2.8.5_BACKWARD_HOLDOUT_SAMPLE_MANIFEST.csv"),"sample_sha":"199864ece6c02f3257647d59ba63fe261a7b478a2525b7ed8042bbf475a9fe48","n":1031,"receipt":Path("evidence/V2.8.5_BAOSTOCK_HOLDOUT_SOURCE_SNAPSHOT_RECEIPT.json"),"seal":"b38838f4c6a4fe679cc45300093cfb366ae15cb8f1fa52746cf50ca9faae62a9","dir":Path("evidence/v285_holdout_source")},
1:{"sample":Path("evidence/V2.8.6_FOLD1_MECHANISM_REPLICATION_MANIFEST.csv"),"sample_sha":"fe15777a0a3a131b58288454a0e3023503bd80ac6a22f20a2e50c45a4deed38a","n":1058,"receipt":Path("evidence/V2.8.6_FOLD1_SOURCE_SNAPSHOT_RECEIPT.json"),"seal":"fc9606a8ea1e024c40911202bfc7c7bddeb86403322e16176ceff6138c382a7e","dir":Path("evidence/v286_fold1_source")},
2:{"sample":Path("evidence/V2.8.7_FOLD2_SETUP_SHAPE_MANIFEST.csv"),"sample_sha":"79b6a4c752a22a16f6ec7167dfb1e6b007473229d7ec6729fb03a15b3ba0fa9a","n":1048,"receipt":Path("evidence/V2.8.7_FOLD2_SOURCE_SNAPSHOT_RECEIPT.json"),"seal":"f6c5df739dc82182f8ce8f660599106331c54cdd6597e98d0efacfb187d11d63","dir":Path("evidence/v287_fold2_source")}}

def sha(p):
 h=hashlib.sha256()
 with p.open("rb") as f:
  for b in iter(lambda:f.read(1<<20),b""): h.update(b)
 return h.hexdigest()
def rj(p): return json.loads(p.read_text(encoding="utf-8"))
def num(s): return pd.to_numeric(s,errors="coerce")
def contracts():
 h,e=rj(H),rj(E)
 assert h["schema"]==HS and h["status"]=="FROZEN_BEFORE_INDEPENDENT_ENTRY_OUTCOME_RESEARCH"
 assert e["schema"]==ES and e["status"]=="FROZEN_BEFORE_AC_PULLBACK_RECLAIM_OUTCOME_RESEARCH"
 assert h["single_hypothesis"]["candidate_id"]==CID and e["hypothesis_gate"]["candidate_id"]==CID
 assert h["authorization"]["fold3_access"] is False and e["authorization"]["fold3_access"] is False
 assert h["authorization"]["fold4_access"] is False and e["authorization"]["fold4_access"] is False
 return h,e
def cal():
 d=rj(CAL)["trading_dates"]; assert len(d)==484 and d==sorted(d) and len(d)==len(set(d)); return d
def maps(d):
 return ({x:(d[i-1] if i else None) for i,x in enumerate(d)},
         {x:(d[i+5] if i+5<len(d) else None) for i,x in enumerate(d)},
         {x:(d[i+10] if i+10<len(d) else None) for i,x in enumerate(d)})
def sample(k):
 c=F[k]; assert sha(c["sample"])==c["sample_sha"]
 rows=list(csv.DictReader(c["sample"].read_text(encoding="utf-8").splitlines())); assert len(rows)==c["n"]
 return {x["canonical_security_id"]:x for x in rows}
def source(k):
 c=F[k]; rec=rj(c["receipt"]); assert rec["status"]=="PASS" and rec["receipt_sha256"]==c["seal"] and rec["sample_manifest_sha256"]==c["sample_sha"]
 z=[]
 for p in rec["stock_partitions"]:
  fp=c["dir"]/p["file"]; assert fp.exists() and sha(fp)==p["sha256"]; z.append(pq.read_table(fp).to_pandas())
 return pd.concat(z,ignore_index=True),rec
def pit(m,d):
 a=str(m.get("official_list_date") or ""); b=str(m.get("official_delist_date") or "")
 return not ((a and d<a) or (b and d>=b))

def symbol_panel(g,m,days):
 x=g.copy(); req={"date","open","high","low","close","canonical_security_id"}; miss=req-set(x)
 if miss: raise RuntimeError(f"SOURCE_COLUMNS_BLOCK:{sorted(miss)}")
 x["date"]=x["date"].astype(str)
 if x["date"].duplicated().any(): raise RuntimeError("DUPLICATE_STOCK_DATE")
 if "tradestatus" in x: x=x[x["tradestatus"].astype(str)=="1"].copy()
 x=x.sort_values("date",kind="mergesort")
 if x.empty:return []
 fi=x.rename(columns={"date":"bar_date"})[["canonical_security_id","bar_date","open","high","low","close"]].copy()
 for c in ["open","high","low","close"]: fi[c]=num(fi[c])
 fi["amount"]=num(x["amount"]) if "amount" in x else 1.0
 ft=build_features(fi); ft["bar_date"]=ft["bar_date"].astype(str); by=ft.set_index("bar_date")
 pm,d5,d10=maps(days); out=[]
 for d in days:
  if not pit(m,d) or d not in by.index: continue
  rr=by.loc[d]; p=pm[d]; pv=bool(p and pit(m,p) and p in by.index); pr=by.loc[p] if pv else None
  a=float(rr["close_vs_ma20"]) if np.isfinite(rr["close_vs_ma20"]) else np.nan
  b=float(rr["close_vs_ma50"]) if np.isfinite(rr["close_vs_ma50"]) else np.nan
  ap=float(pr["close_vs_ma20"]) if pv and np.isfinite(pr["close_vs_ma20"]) else np.nan
  bp=float(pr["close_vs_ma50"]) if pv and np.isfinite(pr["close_vs_ma50"]) else np.nan
  valid=np.isfinite(a) and np.isfinite(b) and np.isfinite(ap) and np.isfinite(bp)
  raw=bool(valid and ap<=0 and bp>0 and a>0 and b>0)
  ctl=bool(valid and ap>0 and bp>0 and a>0 and b>0)
  c0=float(rr["close"]) if np.isfinite(rr["close"]) else np.nan
  def fw(td):
   if td is None or td not in by.index or not np.isfinite(c0) or c0<=0:return np.nan
   q=by.loc[td]; z=float(q["close"]) if np.isfinite(q["close"]) else np.nan
   return z/c0-1 if np.isfinite(z) and z>0 else np.nan
  out.append({"canonical_security_id":m["canonical_security_id"],"signal_date":d,"previous_joint_date":p,
   "close_vs_ma20":a,"close_vs_ma50":b,"previous_close_vs_ma20":ap,"previous_close_vs_ma50":bp,
   "raw_reclaim":raw,"intact_trend_non_reclaim":ctl,"fwd5":fw(d5[d]),"fwd10":fw(d10[d])})
 return out

def mark(z,days):
 pm,_,_=maps(days); x=z.copy(); x["signal_date"]=x["signal_date"].astype(str)
 by={(str(r.canonical_security_id),str(r.signal_date)):r for r in x.itertuples(index=False)}
 raw=[]; ctl=[]
 for r in x.itertuples(index=False):
  p=pm.get(str(r.signal_date)); q=by.get((str(r.canonical_security_id),p)) if p else None
  v=bool(q is not None and all(np.isfinite(v) for v in [r.close_vs_ma20,r.close_vs_ma50,q.close_vs_ma20,q.close_vs_ma50]))
  raw.append(bool(v and q.close_vs_ma20<=0 and q.close_vs_ma50>0 and r.close_vs_ma20>0 and r.close_vs_ma50>0))
  ctl.append(bool(v and q.close_vs_ma20>0 and q.close_vs_ma50>0 and r.close_vs_ma20>0 and r.close_vs_ma50>0))
 x["raw_reclaim"]=raw; x["intact_trend_non_reclaim"]=ctl; return x

def suppress(p,days):
 _,_,d10=maps(days); z=p.copy(); z["accepted_reclaim"]=False
 for _,idx in z.groupby("canonical_security_id",sort=True).groups.items():
  until=None
  for i,r in z.loc[idx].sort_values("signal_date",kind="mergesort").iterrows():
   if not bool(r.get("raw_reclaim",False)): continue
   d=str(r["signal_date"]); t=d10.get(d)
   if t is None: continue
   if until is not None and d<=until: continue
   z.at[i,"accepted_reclaim"]=True; until=t
 z.loc[z["accepted_reclaim"],"intact_trend_non_reclaim"]=False
 return z

def daily(k,p):
 rows=[]
 for d,g in p.groupby("signal_date",sort=True):
  ev=g["accepted_reclaim"].astype(bool); ct=g["intact_trend_non_reclaim"].astype(bool)
  y10=num(g["fwd10"]); y5=num(g["fwd5"]); a10=ev&np.isfinite(y10); a5=ev&np.isfinite(y5); c10=ct&np.isfinite(y10)
  rec={"fold":k,"signal_date":d,"accepted_reclaim_n":int(ev.sum()),"control_n":int(ct.sum()),
       "valid_D10_event_n":int(a10.sum()),"valid_D5_event_n":int(a5.sum()),"valid_D10_control_n":int(c10.sum()),
       "D10_reclaim_excess_mean":np.nan,"D5_reclaim_excess_mean":np.nan,"D10_incremental_timing_spread":np.nan}
  if a10.any() and np.isfinite(y10).any(): rec["D10_reclaim_excess_mean"]=float(y10[a10].mean()-y10[np.isfinite(y10)].mean())
  if a5.any() and np.isfinite(y5).any(): rec["D5_reclaim_excess_mean"]=float(y5[a5].mean()-y5[np.isfinite(y5)].mean())
  if a10.any() and int(c10.sum())>=MIN_CTL: rec["D10_incremental_timing_spread"]=float(y10[a10].mean()-y10[c10].mean())
  rows.append(rec)
 return pd.DataFrame(rows)
def qtr(d):
 t=pd.Timestamp(d); return f"{t.year}Q{(t.month-1)//3+1}"
def boot(s,seed,reps=BOOT):
 x=num(s); x=x[np.isfinite(x)].to_numpy(float)
 if not len(x): return {"n_dates":0,"mean":np.nan,"ci95":[np.nan,np.nan]}
 rng=np.random.default_rng(seed); m=x[rng.integers(0,len(x),size=(reps,len(x)))].mean(axis=1)
 return {"n_dates":len(x),"mean":float(x.mean()),"ci95":[float(np.quantile(m,.025)),float(np.quantile(m,.975))]}
def summary(k,p,d):
 ev=p[p["accepted_reclaim"]].copy(); n=len(ev); cnt=ev.groupby("signal_date").size() if n else pd.Series(dtype=int)
 d10=d[np.isfinite(d["D10_reclaim_excess_mean"])].copy(); d5=d[np.isfinite(d["D5_reclaim_excess_mean"])].copy(); inc=d[np.isfinite(d["D10_incremental_timing_spread"])].copy()
 d10["quarter"]=d10["signal_date"].map(qtr); qr={}
 for q,g in d10.groupby("quarter",sort=True):
  en=int(g["valid_D10_event_n"].sum())
  if len(g)>=10 and en>=20: qr[q]={"dates":len(g),"events":en,"mean":float(g["D10_reclaim_excess_mean"].mean())}
 loo={q:float(d10.loc[d10["quarter"]!=q,"D10_reclaim_excess_mean"].mean()) for q in qr}
 chk={"events":n>=MIN["events"],"secs":ev["canonical_security_id"].nunique()>=MIN["secs"],"dates":ev["signal_date"].nunique()>=MIN["dates"],
 "maxshare":bool(n and cnt.max()/n<=MIN["maxshare"]),"d10e":int(d["valid_D10_event_n"].sum())>=MIN["d10e"],"d5e":int(d["valid_D5_event_n"].sum())>=MIN["d5e"],
 "d10d":len(d10)>=MIN["d10d"],"d5d":len(d5)>=MIN["d5d"],"incd":len(inc)>=MIN["incd"],"quarters":len(qr)>=MIN["quarters"]}
 return {"fold":k,"candidate_id":CID,"total_reclaim_events":n,"distinct_reclaim_securities":int(ev["canonical_security_id"].nunique()) if n else 0,
 "distinct_reclaim_signal_dates":int(ev["signal_date"].nunique()) if n else 0,"maximum_single_signal_date_share":float(cnt.max()/n) if n else np.nan,
 "minimum_information_checks":chk,"minimum_information_pass":all(chk.values()),"valid_D10_events":int(d["valid_D10_event_n"].sum()),"valid_D5_events":int(d["valid_D5_event_n"].sum()),
 "valid_D10_signal_dates":len(d10),"valid_D5_signal_dates":len(d5),"incremental_diagnostic_dates":len(inc),"valid_quarters":len(qr),
 "mean_D10_reclaim_excess":float(d10["D10_reclaim_excess_mean"].mean()) if len(d10) else np.nan,
 "mean_D5_reclaim_excess":float(d5["D5_reclaim_excess_mean"].mean()) if len(d5) else np.nan,
 "mean_D10_incremental_timing_spread":float(inc["D10_incremental_timing_spread"].mean()) if len(inc) else np.nan,
 "positive_valid_quarter_share":float(sum(v["mean"]>0 for v in qr.values())/len(qr)) if qr else np.nan,
 "quarter_primary":qr,"leave_one_valid_quarter_out_primary":loo,
 "leave_one_valid_quarter_out_all_positive":bool(qr and all(np.isfinite(v) and v>0 for v in loo.values())),
 "bootstrap_primary_D10":boot(d10["D10_reclaim_excess_mean"],SEEDS[k])}
def decision(s):
 if any(not x["minimum_information_pass"] for x in s):
  return "V2_8_10_AC_PULLBACK_RECLAIM_DEVELOPMENT_INCONCLUSIVE",[f"fold{x['fold']}:{k}" for x in s for k,v in x["minimum_information_checks"].items() if not v]
 fail=[]
 for x in s:
  k=x["fold"]
  if not x["mean_D10_reclaim_excess"]>0: fail.append(f"fold{k}:primary")
  if not x["mean_D10_incremental_timing_spread"]>0: fail.append(f"fold{k}:incremental")
  if not x["positive_valid_quarter_share"]>=2/3: fail.append(f"fold{k}:quarter_share")
  if not x["leave_one_valid_quarter_out_all_positive"]: fail.append(f"fold{k}:loo")
 if sum(x["mean_D5_reclaim_excess"]>0 for x in s)<2: fail.append("D5_positive_in_two_folds")
 return ("V2_8_10_AC_PULLBACK_RECLAIM_DEVELOPMENT_PASS" if not fail else "V2_8_10_AC_PULLBACK_RECLAIM_DEVELOPMENT_REJECTED"),fail

def evaluate(write=True):
 if OUTF.exists(): return {"status":"FINAL_ALREADY_FROZEN_NO_REEVALUATION","receipt_sha256":rj(OUTF).get("receipt_sha256")}
 h,e=contracts(); days=cal(); sums=[]; evs=[]; ds=[]
 for k in (0,1,2):
  sm=sample(k); st,rec=source(k); rows=[]
  for cid,g in st.groupby("canonical_security_id",sort=True): rows+=symbol_panel(g,sm[cid],days)
  p=suppress(pd.DataFrame(rows),days); d=daily(k,p); s=summary(k,p,d); s["source_receipt_sha256"]=rec["receipt_sha256"]; sums.append(s)
  ee=p[p["accepted_reclaim"]].copy(); ee.insert(0,"fold",k); evs.append(ee); ds.append(d)
 status,fail=decision(sums); out={"schema":"AI_CORE_EVID_V2_8_10_AC_RESEARCH_FINAL_RECEIPT_V1","version":"V2.8.10","status":status,"candidate_id":CID,"fold_summaries":sums,"failed_checks":fail,
 "bootstrap_used_for_development_pass_fail":False,"sample_modified_after_results":False,"optional_stopping_used":False,"threshold_changed_after_results":False,
 "fold3_accessed":False,"fold4_accessed":False,"setup_emission_authorized":False,"first60_append_authorized":False,"episode_emission_authorized":False,"live_authorized":False}
 if write:
  pd.concat(evs,ignore_index=True).to_csv(OUTE,index=False,lineterminator="\n"); pd.concat(ds,ignore_index=True).to_csv(OUTD,index=False,lineterminator="\n")
  out["event_ledger_sha256"]=sha(OUTE); out["daily_metrics_sha256"]=sha(OUTD)
 out["receipt_sha256"]=hashlib.sha256(json.dumps(out,sort_keys=True,separators=(",",":")).encode()).hexdigest()
 if write: OUTF.write_text(json.dumps(out,indent=2)+"\n")
 return out

def self_test():
 t=[]; ck=lambda n,v:t.append({"name":n,"pass":bool(v)})
 h,e=contracts(); ck("A01_candidate_exact",h["single_hypothesis"]["candidate_id"]==CID); ck("A02_no_fold3_4_config",set(F)=={0,1,2})
 days=pd.bdate_range("2024-01-02",periods=40).strftime("%Y-%m-%d").tolist()
 z=pd.DataFrame([
 {"canonical_security_id":"X","signal_date":days[0],"close_vs_ma20":-.01,"close_vs_ma50":.05},
 {"canonical_security_id":"X","signal_date":days[1],"close_vs_ma20":.01,"close_vs_ma50":.04},
 {"canonical_security_id":"Y","signal_date":days[0],"close_vs_ma20":.02,"close_vs_ma50":.05},
 {"canonical_security_id":"Y","signal_date":days[1],"close_vs_ma20":.03,"close_vs_ma50":.06}])
 m=mark(z,days); ck("A03_exact_reclaim_transition",bool(m[(m.canonical_security_id=="X")&(m.signal_date==days[1])].raw_reclaim.iloc[0]))
 ck("A04_intact_control",bool(m[(m.canonical_security_id=="Y")&(m.signal_date==days[1])].intact_trend_non_reclaim.iloc[0]))
 gap=z[z.signal_date!=days[0]].copy(); mg=mark(gap,days); ck("A05_no_skip_previous_joint_day",not bool(mg[(mg.canonical_security_id=="X")&(mg.signal_date==days[1])].raw_reclaim.iloc[0]))
 future=pd.concat([z,pd.DataFrame([{"canonical_security_id":"X","signal_date":days[2],"close_vs_ma20":-9.0,"close_vs_ma50":-9.0}])]); ck("A06_future_cannot_change_D",bool(mark(future,days)[lambda q:(q.canonical_security_id=="X")&(q.signal_date==days[1])].raw_reclaim.iloc[0]))
 raw=pd.DataFrame([{"canonical_security_id":"S","signal_date":days[1],"raw_reclaim":True,"intact_trend_non_reclaim":False},{"canonical_security_id":"S","signal_date":days[5],"raw_reclaim":True,"intact_trend_non_reclaim":False},{"canonical_security_id":"S","signal_date":days[12],"raw_reclaim":True,"intact_trend_non_reclaim":False}])
 ac=suppress(raw,days); ck("A07_D_through_D10_suppression",ac.loc[ac.accepted_reclaim,"signal_date"].tolist()==[days[1],days[12]])
 q=pd.DataFrame([{"canonical_security_id":"Q","signal_date":days[0],"raw_reclaim":False,"intact_trend_non_reclaim":True},{"canonical_security_id":"Q","signal_date":days[1],"raw_reclaim":True,"intact_trend_non_reclaim":True}])
 qq=suppress(q,days); ck("A08_control_excludes_accepted_event",not bool(qq.loc[qq.accepted_reclaim,"intact_trend_non_reclaim"].iloc[0]))
 ck("A09_bootstrap_deterministic",boot(pd.Series([1.,-1.]),123,500)==boot(pd.Series([1.,-1.]),123,500))
 ck("A10_equal_date_weighting",abs(pd.Series([.1,-.02]).mean()-.04)<1e-12)
 src=Path(__file__).read_text().split("def self_test():")[0]; ck("A11_no_compression_alpha","rv10_over_rv60" not in src and "tr10_over_tr60" not in src)
 ck("A12_no_liquidity_alpha","amount_vs_med20" not in src and "amount_med20" not in src)
 ck("A13_no_ret_filter","ret_20" not in src and "ret_60" not in src)
 ck("A14_natural_zero_boundaries","<=0" in src and ">0" in src)
 ck("A15_real_research_not_authorized",e["authorization"]["run_real_AC_research_on_folds0_1_2"] is False)
 ck("A16_fold3_4_sealed",e["authorization"]["fold3_access"] is False and e["authorization"]["fold4_access"] is False)
 out={"schema":"AI_CORE_EVID_V2_8_10_LOCKED_AC_EVALUATOR_SELFTEST_V1","tests":t,"passed":sum(x["pass"] for x in t),"total":len(t),"all_pass":all(x["pass"] for x in t),
 "real_consumed_fold_price_rows_read":False,"real_AC_outcomes_read":False,"fold3_4_price_rows_read":False}
 print(json.dumps(out,indent=2))
 if not out["all_pass"]: raise SystemExit(2)

if __name__=="__main__":
 a=argparse.ArgumentParser(); a.add_argument("command",choices=["self-test","evaluate"]); x=a.parse_args()
 self_test() if x.command=="self-test" else print(json.dumps(evaluate(True),indent=2))
