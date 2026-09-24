from __future__ import annotations
import argparse,csv,hashlib,json,re,subprocess,tempfile
from pathlib import Path
from collections import Counter

GATE=Path("evidence/V2.8.12_PROSPECTIVE_E_EVENT_SHADOW_ACCUMULATION_GATE.json")
CADENCE=Path("evidence/V2.8.12_SHADOW_CADENCE_CONTRACT.json")
SHADOW=Path("evidence/V2.8.12_PROSPECTIVE_E_SHADOW_LEDGER.csv")
STATUS=Path("evidence/V2.8.12_SHADOW_INFORMATION_GATE_STATUS.json")
GENESIS=Path("evidence/V2.8.4_FIRST_PROSPECTIVE_POSITIVE_EVENT_RATIFICATION.json")
OBS_LEDGER=Path("evidence/V2.8.4_E_LAYER_OBSERVATION_LEDGER.csv")
BINDINGS=Path("evidence/V2.8.4_E_LAYER_ISSUER_IDENTITY_BINDINGS.csv")
RUNS=Path("evidence/v284_prospective_runs")
CANON=re.compile(r"^(SSE|SZSE):\d{6}$")
FIELDS=[
"shadow_event_id","announcement_id","canonical_security_id","issuer_legal_name",
"source_object_sha256","page_text_sha256","decision_sha256","evidence_sentence_sha256",
"matched_ai_role_json","matched_commerciality_json","evidence_observation_commit_sha",
"issuer_identity_binding_commit_sha","authoritative_observed_at_utc",
"eligibility_completeness_time_utc","effective_signal_date","issuer_positive_sequence_number",
"recurrence_status","prior_positive_announcement_id","prior_positive_effective_signal_date",
"source_finalization_receipt","source_ratification_file","historical_reconstruction",
"price_or_return_data_consumed"]

def rj(p:Path):
 s=p.read_text(encoding="utf-8").strip()
 while s.endswith("\\n"): s=s[:-2].rstrip()
 return json.loads(s)
def rows(p:Path):
 return list(csv.DictReader(p.read_text(encoding="utf-8").splitlines())) if p.exists() else []
def stable(x): return hashlib.sha256(json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()
def sentence_hash(s): return hashlib.sha256(str(s or "").encode()).hexdigest()
def event_id(a,c,d,e): return hashlib.sha256(f"V2.8.12|{a}|{c}|{d}|{e}".encode()).hexdigest()
def write_rows(p:Path,x):
 p.parent.mkdir(parents=True,exist_ok=True)
 with p.open("w",encoding="utf-8",newline="") as f:
  w=csv.DictWriter(f,fieldnames=FIELDS,lineterminator="\n");w.writeheader();w.writerows(x)

def gate_guard():
 g=rj(GATE); c=rj(CADENCE)
 assert g["status"]=="FROZEN_BEFORE_SHADOW_LEDGER_IMPLEMENTATION"
 assert c["status"]=="FROZEN_BEFORE_SCHEDULE_ACTIVATION"
 assert c["cadence"]["cron_utc"]=="0 1 * * 2-6"
 return g,c

def assess(existing,event):
 hits=[r for r in existing if r["announcement_id"]==event["announcement_id"]]
 if not hits:return "APPEND_ALLOWED"
 if len(hits)!=1: raise RuntimeError("DUPLICATE_ANNOUNCEMENT_IN_SHADOW")
 old=hits[0]
 keys=["canonical_security_id","source_object_sha256","decision_sha256"]
 if any(old[k]!=event[k] for k in keys): return "BLOCK_CONFLICT"
 return "NO_ACTION_DUPLICATE"

def with_recurrence(existing,event):
 same=[r for r in existing if r["canonical_security_id"]==event["canonical_security_id"]]
 n=len(same)+1
 out=dict(event)
 out["issuer_positive_sequence_number"]=str(n)
 if n==1:
  out["recurrence_status"]="FIRST_POSITIVE_FOR_ISSUER";out["prior_positive_announcement_id"]="";out["prior_positive_effective_signal_date"]=""
 else:
  prev=same[-1]
  out["recurrence_status"]="SUBSEQUENT_POSITIVE_FOR_ISSUER"
  out["prior_positive_announcement_id"]=prev["announcement_id"]
  out["prior_positive_effective_signal_date"]=prev["effective_signal_date"]
 return out

def readiness(x):
 n=len(x); issuers=Counter(r["canonical_security_id"] for r in x)
 eff={r["effective_signal_date"] for r in x}
 months={r["effective_signal_date"][:7] for r in x if r["effective_signal_date"]}
 maxshare=(max(issuers.values())/n) if n else 0.0
 prov=all(
  r["historical_reconstruction"]=="false" and
  r["price_or_return_data_consumed"]=="false" and
  CANON.fullmatch(r["canonical_security_id"] or "") and
  int(r["issuer_positive_sequence_number"])>=1
  for r in x)
 checks={
  "event_count_ge_20":n>=20,
  "distinct_issuer_count_ge_12":len(issuers)>=12,
  "distinct_effective_date_count_ge_12":len(eff)>=12,
  "distinct_positive_calendar_month_count_ge_6":len(months)>=6,
  "maximum_single_issuer_event_share_le_0_20":maxshare<=.20 if n else False,
  "provenance_integrity_pass":prov,
  "price_or_return_data_consumed_false":all(r["price_or_return_data_consumed"]=="false" for r in x)
 }
 return {
  "shadow_event_count":n,"distinct_issuer_count":len(issuers),
  "distinct_effective_date_count":len(eff),
  "distinct_positive_calendar_month_count":len(months),
  "maximum_single_issuer_event_share":maxshare,
  "provenance_checks":checks,
  "status":"READY_FOR_V2_8_13_OUTCOME_CONTRACT" if all(checks.values()) else "ACCUMULATING_PROSPECTIVE_E_EVENTS"
 }

def genesis_row():
 g=rj(GENESIS); e=g["event"]; ca=g["classification_authority"]; ia=g["issuer_identity_authority"]; tr=g["temporal_ratification"]
 run=ca["observation_run_id"]
 fp=RUNS/f"V2.8.4_PROSPECTIVE_OBSERVATION_RESULTS_{run}.csv"
 rr=[r for r in rows(fp) if r["announcement_id"]==e["announcement_id"]]
 if len(rr)!=1: raise RuntimeError("GENESIS_OBSERVATION_RESULT_BLOCK")
 r=rr[0]
 ev={
  "announcement_id":e["announcement_id"],"canonical_security_id":e["canonical_security_id"],
  "issuer_legal_name":e["issuer_legal_name"],"source_object_sha256":e["source_object_sha256"],
  "page_text_sha256":e["page_text_sha256"],"decision_sha256":e["decision_sha256"],
  "evidence_sentence_sha256":sentence_hash(r.get("evidence_sentence","")),
  "matched_ai_role_json":json.dumps(e["matched_ai_role"],ensure_ascii=False,separators=(",",":")),
  "matched_commerciality_json":json.dumps(e["matched_commerciality"],ensure_ascii=False,separators=(",",":")),
  "evidence_observation_commit_sha":ca["observation_commit_sha"],
  "issuer_identity_binding_commit_sha":ia["binding_commit_sha"],
  "authoritative_observed_at_utc":ca["observation_committed_at_utc"],
  "eligibility_completeness_time_utc":tr["eligibility_completeness_time_utc"],
  "effective_signal_date":tr["effective_signal_date"],
  "source_finalization_receipt":f"evidence/v284_prospective_runs/V2.8.4_PROSPECTIVE_FINALIZATION_RECEIPT_{run}.json",
  "source_ratification_file":str(GENESIS),
  "historical_reconstruction":"false","price_or_return_data_consumed":"false"
 }
 ev["shadow_event_id"]=event_id(ev["announcement_id"],ev["canonical_security_id"],ev["decision_sha256"],ev["effective_signal_date"])
 return ev

def binding_commit_for(cid,issuer):
 # Git blame returns the introducing commit for the exact CSV row.
 lines=BINDINGS.read_text(encoding="utf-8").splitlines()
 idx=None
 for i,line in enumerate(lines[1:],start=2):
  p=next(csv.reader([line]))
  if len(p)>=3 and p[0]==cid and p[2]==issuer: idx=i;break
 if idx is None: raise RuntimeError("BINDING_ROW_NOT_FOUND")
 out=subprocess.check_output(["git","blame","-L",f"{idx},{idx}","--porcelain",str(BINDINGS)],text=True)
 return out.splitlines()[0].split()[0]

def future_from_finalization(path:Path):
 f=rj(path); out=[]
 if f.get("historical_backfill") is not False: return []
 if f.get("price_or_return_data_consumed") is not False: raise RuntimeError("FINALIZATION_PRICE_CONTAMINATION")
 run=str(f["run_id"])
 obs=RUNS/f"V2.8.4_PROSPECTIVE_OBSERVATION_RESULTS_{run}.csv"
 obsrows={r["announcement_id"]:r for r in rows(obs)}
 led={r["announcement_id"]:r for r in rows(OBS_LEDGER)}
 for e in f.get("effective_positive_events") or []:
  if e.get("classification_state")!="ELIGIBLE_AI_CORE" or not e.get("record_complete"): continue
  aid=e["announcement_id"]
  if aid not in obsrows or aid not in led: raise RuntimeError("FINALIZATION_JOIN_BLOCK")
  o=obsrows[aid]; l=led[aid]
  issuer=e["issuer_legal_name"]; cid=e["canonical_security_id"]
  ev={
   "announcement_id":aid,"canonical_security_id":cid,"issuer_legal_name":issuer,
   "source_object_sha256":e["source_object_sha256"],"page_text_sha256":l["page_text_sha256"],
   "decision_sha256":l["decision_sha256"],"evidence_sentence_sha256":sentence_hash(e.get("evidence_text","")),
   "matched_ai_role_json":json.dumps(e.get("matched_ai_role") or [],ensure_ascii=False,separators=(",",":")),
   "matched_commerciality_json":json.dumps(e.get("matched_commerciality") or [],ensure_ascii=False,separators=(",",":")),
   "evidence_observation_commit_sha":f["observation_commit_sha"],
   "issuer_identity_binding_commit_sha":binding_commit_for(cid,issuer),
   "authoritative_observed_at_utc":e["authoritative_observed_at_utc"],
   "eligibility_completeness_time_utc":e["authoritative_observed_at_utc"],
   "effective_signal_date":e["effective_signal_date"],
   "source_finalization_receipt":str(path),"source_ratification_file":"",
   "historical_reconstruction":"false","price_or_return_data_consumed":"false"
  }
  ev["shadow_event_id"]=event_id(aid,cid,ev["decision_sha256"],ev["effective_signal_date"])
  out.append(ev)
 return out

def accumulate(ledger_path=SHADOW,status_path=STATUS):
 gate_guard()
 existing=rows(ledger_path)
 incoming=[]
 if not existing: incoming.append(genesis_row())
 for p in sorted(RUNS.glob("V2.8.4_PROSPECTIVE_FINALIZATION_RECEIPT_*.json")):
  incoming.extend(future_from_finalization(p))
 working=[dict(r) for r in existing]
 appended=0;dupes=0
 for ev in incoming:
  state=assess(working,ev)
  if state=="BLOCK_CONFLICT": raise RuntimeError(f"SHADOW_CONFLICT:{ev['announcement_id']}")
  if state=="NO_ACTION_DUPLICATE":dupes+=1;continue
  ev=with_recurrence(working,ev);working.append(ev);appended+=1
 write_rows(ledger_path,working)
 st=readiness(working);status_path.write_text(json.dumps(st,indent=2)+"\n")
 return {"appended":appended,"duplicate_noops":dupes,"rows":len(working),"readiness":st}

def self_test():
 gate_guard();t=[]
 def ck(n,v):t.append({"name":n,"pass":bool(v)})
 with tempfile.TemporaryDirectory() as td:
  p=Path(td)/"l.csv"
  g=with_recurrence([],genesis_row());write_rows(p,[g])
  x=rows(p)
  ck("S01_genesis_exactly_one",len(x)==1 and x[0]["announcement_id"]=="1225573666")
  ck("S02_genesis_sequence1",x[0]["issuer_positive_sequence_number"]=="1" and x[0]["recurrence_status"]=="FIRST_POSITIVE_FOR_ISSUER")
  ck("S03_no_historical_seed",x[0]["historical_reconstruction"]=="false")
  ck("S04_duplicate_noop",assess(x,dict(x[0]))=="NO_ACTION_DUPLICATE")
  bad=dict(x[0]);bad["source_object_sha256"]="f"*64
  ck("S05_conflict_blocks",assess(x,bad)=="BLOCK_CONFLICT")
  nxt={k:x[0][k] for k in FIELDS if k in x[0]};nxt.update({"announcement_id":"999","shadow_event_id":"z"*64,"effective_signal_date":"2026-10-08"})
  nxt=with_recurrence(x,nxt)
  ck("S06_same_issuer_sequence2",nxt["issuer_positive_sequence_number"]=="2" and nxt["prior_positive_announcement_id"]=="1225573666")
  other=dict(nxt);other.update({"announcement_id":"1000","canonical_security_id":"SSE:600001","shadow_event_id":"y"*64})
  other=with_recurrence(x,other)
  ck("S07_other_issuer_sequence1",other["issuer_positive_sequence_number"]=="1")
  syn=[]
  for i in range(20):
   cid=f"SSE:{600000+(i%12):06d}"
   syn.append({**x[0],"announcement_id":str(2000+i),"canonical_security_id":cid,"effective_signal_date":f"2026-{1+(i%6):02d}-{1+(i%20):02d}","issuer_positive_sequence_number":"1","historical_reconstruction":"false","price_or_return_data_consumed":"false"})
  r=readiness(syn);ck("S08_20_events_12_issuers_can_pass",r["shadow_event_count"]==20 and r["distinct_issuer_count"]==12 and r["status"]=="READY_FOR_V2_8_13_OUTCOME_CONTRACT")
  few=[{**z,"canonical_security_id":f"SSE:{600000+(i%5):06d}"} for i,z in enumerate(syn)]
  ck("S09_fewer_than_12_issuers_fails",readiness(few)["status"]!="READY_FOR_V2_8_13_OUTCOME_CONTRACT")
  conc=[dict(z) for z in syn]
  for i in range(5):conc[i]["canonical_security_id"]="SSE:699999"
  ck("S10_issuer_share_over20_fails",readiness(conc)["maximum_single_issuer_event_share"]>.20 and readiness(conc)["status"]!="READY_FOR_V2_8_13_OUTCOME_CONTRACT")
  hist=dict(x[0]);hist["historical_reconstruction"]="true"
  ck("S11_historical_fails_provenance",readiness([hist])["provenance_checks"]["provenance_integrity_pass"] is False)
  c=rj(CADENCE);ck("S12_frozen_cadence",c["cadence"]["cron_utc"]=="0 1 * * 2-6" and c["integration"]["active_now"] is False)
  src=Path(__file__).read_text()
  ck("S13_no_price_modules",all(q not in src for q in ["v283_outcome_resolver","v280_scale_invariant_features","fwd10","fwd5"]))
  ck("S14_no_v2811_ingestion","V2.8.11_RECONCILED" not in src and "V2.8.11_TARGETED" not in src)
 out={"schema":"AI_CORE_EVID_V2_8_12_SHADOW_ACCUMULATOR_SELFTEST_V1","tests":t,"passed":sum(z["pass"] for z in t),"total":len(t),"all_pass":all(z["pass"] for z in t),"real_shadow_ledger_modified":False,"price_or_return_data_consumed":False,"schedule_activated":False,"fold3_4_accessed":False}
 print(json.dumps(out,ensure_ascii=False,indent=2))
 if not out["all_pass"]:raise SystemExit(2)

if __name__=="__main__":
 ap=argparse.ArgumentParser();ap.add_argument("command",choices=["self-test","accumulate"]);a=ap.parse_args()
 self_test() if a.command=="self-test" else print(json.dumps(accumulate(),ensure_ascii=False,indent=2))
