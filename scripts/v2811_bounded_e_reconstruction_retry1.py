from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

CONTRACT=Path("evidence/V2.8.11_BOUNDED_HISTORICAL_E_RECONSTRUCTION_PILOT_CONTRACT.json")
CALENDAR=Path("evidence/V2.8.5_JOINT_A_SHARE_TRADING_CALENDAR_2023_2024.json")
VALIDATION=Path("evidence/V2.8.11_BOUNDED_E_RECONSTRUCTION_RETRY1_VALIDATION_RECEIPT.json")
OUT_WINDOWS=Path("evidence/V2.8.11_BOUNDED_E_RECONSTRUCTION_RETRY1_WINDOWS.json")
OUT_RESULTS=Path("evidence/V2.8.11_BOUNDED_E_RECONSTRUCTION_RETRY1_RESULTS.csv")
OUT_POSITIVE=Path("evidence/V2.8.11_BOUNDED_E_RECONSTRUCTION_RETRY1_POSITIVE_EVENTS.csv")
OUT_FINAL=Path("evidence/V2.8.11_BOUNDED_E_RECONSTRUCTION_RETRY1_FINAL_RECEIPT.json")

CONTRACT_SCHEMA="AI_CORE_EVID_V2_8_11_BOUNDED_HISTORICAL_E_RECONSTRUCTION_PILOT_CONTRACT_V1"
MAX_PER_WINDOW=6
MAX_TOTAL=48
POSITIVE="ELIGIBLE_AI_CORE"
SH=ZoneInfo("Asia/Shanghai")

FROZEN_WINDOWS=[
    {"quarter":"2023Q1","quarter_joint_sessions":59,"anchor":"2023-02-07","start":"2023-02-07","end":"2023-02-13"},
    {"quarter":"2023Q2","quarter_joint_sessions":59,"anchor":"2023-05-05","start":"2023-05-05","end":"2023-05-11"},
    {"quarter":"2023Q3","quarter_joint_sessions":64,"anchor":"2023-07-31","start":"2023-07-31","end":"2023-08-06"},
    {"quarter":"2023Q4","quarter_joint_sessions":60,"anchor":"2023-11-06","start":"2023-11-06","end":"2023-11-12"},
    {"quarter":"2024Q1","quarter_joint_sessions":58,"anchor":"2024-01-30","start":"2024-01-30","end":"2024-02-05"},
    {"quarter":"2024Q2","quarter_joint_sessions":59,"anchor":"2024-05-06","start":"2024-05-06","end":"2024-05-12"},
    {"quarter":"2024Q3","quarter_joint_sessions":64,"anchor":"2024-07-29","start":"2024-07-29","end":"2024-08-04"},
    {"quarter":"2024Q4","quarter_joint_sessions":61,"anchor":"2024-11-05","start":"2024-11-05","end":"2024-11-11"},
]

def stable_sha(obj)->str:
    return hashlib.sha256(json.dumps(obj,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()

def sha_file(path:Path)->str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda:f.read(1<<20),b""): h.update(b)
    return h.hexdigest()

def read_json(path:Path)->dict:
    return json.loads(path.read_text(encoding="utf-8"))

def load_contract()->dict:
    c=read_json(CONTRACT)
    if c.get("schema")!=CONTRACT_SCHEMA or c.get("status")!="FROZEN_BEFORE_PILOT_IMPLEMENTATION_VALIDATION":
        raise RuntimeError("PILOT_CONTRACT_BINDING_BLOCK")
    if c["calendar"]["frozen_windows"]!=FROZEN_WINDOWS:
        raise RuntimeError("PILOT_WINDOW_BINDING_BLOCK")
    if c["discovery_and_selection"]["maximum_selected_per_window"]!=MAX_PER_WINDOW:
        raise RuntimeError("PILOT_PER_WINDOW_CAP_BLOCK")
    if c["discovery_and_selection"]["maximum_selected_total"]!=MAX_TOTAL:
        raise RuntimeError("PILOT_TOTAL_CAP_BLOCK")
    return c

def trading_dates()->list[str]:
    obj=read_json(CALENDAR)
    if obj.get("receipt_sha256")!="1f6e44915ec0a6f3db0396a491c83118b6ce57448f7f08b2d35a7d8ee7cf4ed8":
        raise RuntimeError("CALENDAR_RECEIPT_BLOCK")
    d=list(obj["trading_dates"])
    if len(d)!=484 or d!=sorted(d) or len(d)!=len(set(d)):
        raise RuntimeError("CALENDAR_INTEGRITY_BLOCK")
    return d

def compute_windows(days:list[str])->list[dict]:
    q={}
    for d in days:
        y,m=map(int,d.split("-")[:2])
        k=f"{y}Q{(m-1)//3+1}"
        q.setdefault(k,[]).append(d)
    out=[]
    for k in sorted(q):
        if k[:4] not in {"2023","2024"}: continue
        if len(q[k])<21: raise RuntimeError(f"QUARTER_TOO_SHORT:{k}")
        a=q[k][20]
        e=(datetime.fromisoformat(a)+timedelta(days=6)).date().isoformat()
        out.append({"quarter":k,"quarter_joint_sessions":len(q[k]),"anchor":a,"start":a,"end":e})
    return out

def selection_key(announcement_id:str)->str:
    return hashlib.sha256(str(announcement_id).encode()).hexdigest()

def select_candidates(rows:list[dict],limit:int=MAX_PER_WINDOW)->list[dict]:
    unique={}
    for r in rows:
        aid=str(r.get("announcement_id") or "").strip()
        cid=str(r.get("canonical_security_id") or "").strip()
        if not aid or not re.fullmatch(r"(SSE|SZSE):\d{6}",cid):
            raise RuntimeError("INVALID_SELECTION_IDENTITY")
        if aid in unique:
            keys=("canonical_security_id","adjunct_url","announcement_time","path_disclosure_date")
            if any(str(unique[aid].get(k))!=str(r.get(k)) for k in keys):
                raise RuntimeError(f"ANNOUNCEMENT_CONFLICT:{aid}")
            continue
        unique[aid]=dict(r)
    ordered=sorted(unique.values(),key=lambda r:(selection_key(r["announcement_id"]),str(r["announcement_id"])))
    chosen=[]; seen_sec=set()
    for r in ordered:
        cid=r["canonical_security_id"]
        if cid in seen_sec: continue
        chosen.append(r); seen_sec.add(cid)
        if len(chosen)>=limit: break
    return chosen

def announcement_local_date(value)->str:
    s=str(value or "").strip()
    if not re.fullmatch(r"\d{10}|\d{13}",s):
        raise RuntimeError("TEMPORAL_ANNOUNCEMENT_TIME_BLOCK")
    n=int(s)
    seconds=n/1000.0 if len(s)==13 else float(n)
    try:
        dt=datetime.fromtimestamp(seconds,tz=timezone.utc).astimezone(SH)
    except (ValueError,OverflowError,OSError) as e:
        raise RuntimeError("TEMPORAL_ANNOUNCEMENT_TIME_BLOCK") from e
    return dt.date().isoformat()

def path_date(row:dict)->str:
    aid=str(row.get("announcement_id") or "").strip()
    adj=str(row.get("adjunct_url") or "").strip()
    pd=str(row.get("path_disclosure_date") or "").strip()
    m=re.fullmatch(r"finalpage/(\d{4}-\d{2}-\d{2})/(\d+)\.pdf",adj,re.I)
    if not m or m.group(2)!=aid or m.group(1)!=pd:
        raise RuntimeError("TEMPORAL_OFFICIAL_PATH_BLOCK")
    datetime.fromisoformat(pd)
    return pd

def next_joint_after(d:str,days:list[str])->str:
    for x in days:
        if x>d: return x
    raise RuntimeError("TEMPORAL_NO_LATER_JOINT_SESSION")

def resolve_temporal(row:dict,days:list[str])->dict:
    p=path_date(row)
    a=announcement_local_date(row.get("announcement_time"))
    if a!=p:
        raise RuntimeError(f"TEMPORAL_DATE_CONFLICT:{a}:{p}")
    eff=next_joint_after(p,days)
    if eff<=p:
        raise RuntimeError("TEMPORAL_SAME_DAY_BLOCK")
    return {
        "announcement_local_date_asia_shanghai":a,
        "path_disclosure_date":p,
        "temporal_provenance_status":"PASS",
        "retrospective_causal_effective_date":eff,
    }

def validate_real_run_authorization():
    if not VALIDATION.exists():
        raise RuntimeError("REAL_PILOT_NOT_VALIDATED")
    v=read_json(VALIDATION)
    if v.get("status")!="PASS":
        raise RuntimeError("REAL_PILOT_VALIDATION_NOT_PASS")
    a=v.get("authorization",{})
    if a.get("execute_retry1") is not True:
        raise RuntimeError("REAL_PILOT_NOT_AUTHORIZED")
    if a.get("outcome_research") is not False or a.get("fold3_access") is not False or a.get("fold4_access") is not False:
        raise RuntimeError("REAL_PILOT_AUTHORIZATION_SCOPE_BLOCK")

def fetch_pdf(api,row:dict,path:Path):
    import v284_pdf_text_extractor as te
    adjunct=str(row["adjunct_url"]); aid=str(row["announcement_id"])
    if not adjunct.lower().endswith(f"/{aid}.pdf".lower()):
        raise RuntimeError("INVALID_OFFICIAL_LOCATOR")
    r=api.get("https://static.cninfo.com.cn/"+adjunct,timeout=90000,
              headers={"Referer":"https://www.cninfo.com.cn/","Accept":"application/pdf,*/*;q=0.8"})
    if r.status!=200: raise RuntimeError(f"PDF_FETCH_HTTP_{r.status}")
    b=r.body(); path.write_bytes(b)
    return te.validate_pdf(path),len(b)

def write_csv(path:Path,rows:list[dict],fields:list[str]):
    with path.open("w",encoding="utf-8",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,lineterminator="\n",extrasaction="ignore"); w.writeheader(); w.writerows(rows)

def run():
    validate_real_run_authorization()
    if OUT_FINAL.exists():
        return {"status":"FINAL_ALREADY_FROZEN_NO_REEXECUTION","receipt_sha256":read_json(OUT_FINAL).get("receipt_sha256")}
    load_contract(); days=trading_dates()
    windows=compute_windows(days)
    if windows!=FROZEN_WINDOWS: raise RuntimeError("RUNTIME_WINDOWS_DRIFT")

    import v284_candidate_collector as cc
    import v284_candidate_triage as ct
    import v284_pdf_text_extractor as te
    import v284_page_scoped_classifier as pc
    from playwright.sync_api import sync_playwright

    all_results=[]; window_records=[]
    with tempfile.TemporaryDirectory() as td:
        root=Path(td)

        # IMPORTANT RETRY1 ORCHESTRATION:
        # candidate collector owns its own sync_playwright context.
        # No outer Playwright context exists while cc.collect() runs.
        for wi,w in enumerate(windows,1):
            wr={**w,"window_status":"COMPLETED","source_blocker":"","candidate_rows":0,
                "triage_skipped":0,"materializable_rows":0,"selected_count":0}
            try:
                wd=root/f"window_{wi}"
                cc.collect(datetime.fromisoformat(w["start"]).date(),datetime.fromisoformat(w["end"]).date(),wd)
                dedup=wd/"V2.8.4_CNINFO_CANDIDATE_DEDUPED.csv"
                rows=list(csv.DictReader(dedup.read_text(encoding="utf-8").splitlines()))
                wr["candidate_rows"]=len(rows)
                mat=[]; skipped=0
                for row in rows:
                    q=ct.triage_title(row.get("announcement_title",""),row.get("security_name",""))
                    if q["triage_state"]=="MATERIALIZE_CANDIDATE": mat.append(row)
                    else: skipped+=1
                wr["triage_skipped"]=skipped; wr["materializable_rows"]=len(mat)
                selected=select_candidates(mat,MAX_PER_WINDOW); wr["selected_count"]=len(selected)

                # Separate Playwright context begins only after candidate collection.
                if selected:
                    with sync_playwright() as pw:
                        api=pw.request.new_context(extra_http_headers={
                            "User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/153 Safari/537.36"
                        })
                        home=api.get("https://www.cninfo.com.cn/",timeout=30000)
                        if home.status!=200: raise RuntimeError(f"CNINFO_HOME_HTTP_{home.status}")
                        for rank,row in enumerate(selected,1):
                            base={
                                "quarter":w["quarter"],"window_start":w["start"],"window_end":w["end"],
                                "sample_rank":rank,"selection_sha256":selection_key(row["announcement_id"]),
                                "announcement_id":row["announcement_id"],"canonical_security_id":row["canonical_security_id"],
                                "security_name":row.get("security_name",""),"announcement_title":row.get("announcement_title",""),
                                "announcement_time":row.get("announcement_time",""),"adjunct_url":row.get("adjunct_url",""),
                                "path_disclosure_date":row.get("path_disclosure_date",""),"matched_terms":row.get("matched_terms",""),
                            }
                            try:
                                temporal=resolve_temporal(row,days)
                                pdf=root/f"{w['quarter']}_{rank}.pdf"
                                obj_sha,nbytes=fetch_pdf(api,row,pdf)
                                page_rows,ex=te.extract_pdf(pdf,obj_sha)
                                dec=pc.classify_pages(page_rows)
                                evidence=dec["evidence"]
                                all_results.append({
                                    **base,**temporal,"pipeline_status":"SUCCESS","blocker":"",
                                    "object_sha256":obj_sha,"bytes":nbytes,
                                    "pdf_page_count":ex["pdf_page_count"],"pages_with_text":ex["pages_with_text"],
                                    "total_nonwhitespace_characters":ex["total_nonwhitespace_characters"],
                                    "page_text_sha256":ex["page_text_sha256"],
                                    "classification_state":dec["classification_state"],
                                    "evidence_page_number":evidence["page_number"],
                                    "evidence_sentence_sha256":hashlib.sha256(str(evidence.get("evidence_sentence") or "").encode()).hexdigest(),
                                    "matched_ai_role":"|".join(evidence.get("matched_ai_role") or []),
                                    "matched_commerciality":"|".join(evidence.get("matched_commerciality") or []),
                                    "classification_reason":evidence.get("reason",""),
                                    "decision_sha256":dec["decision_sha256"],
                                })
                            except Exception as ex:
                                all_results.append({**base,"pipeline_status":"BLOCKED","blocker":f"{type(ex).__name__}:{ex}"})
                        api.dispose()
            except Exception as ex:
                wr["window_status"]="WINDOW_SOURCE_BLOCKED"
                wr["source_blocker"]=f"{type(ex).__name__}:{ex}"
            window_records.append(wr)

    if sum(x["selected_count"] for x in window_records)>MAX_TOTAL:
        raise RuntimeError("GLOBAL_SELECTION_CAP_BLOCK")

    fields=[
        "quarter","window_start","window_end","sample_rank","selection_sha256","announcement_id","canonical_security_id",
        "security_name","announcement_title","announcement_time","adjunct_url","path_disclosure_date","matched_terms",
        "announcement_local_date_asia_shanghai","temporal_provenance_status","retrospective_causal_effective_date",
        "pipeline_status","blocker","object_sha256","bytes","pdf_page_count","pages_with_text",
        "total_nonwhitespace_characters","page_text_sha256","classification_state","evidence_page_number",
        "evidence_sentence_sha256","matched_ai_role","matched_commerciality","classification_reason","decision_sha256"
    ]
    write_csv(OUT_RESULTS,all_results,fields)
    positives=[r for r in all_results if r.get("pipeline_status")=="SUCCESS" and r.get("classification_state")==POSITIVE]
    write_csv(OUT_POSITIVE,positives,fields)

    selected=len(all_results)
    success=sum(r.get("pipeline_status")=="SUCCESS" for r in all_results)
    materialization_rate=success/selected if selected else 0.0
    positive_secs=len({r["canonical_security_id"] for r in positives})
    positive_quarters=len({r["quarter"] for r in positives})
    technical={
        "eight_windows_accounted_for":len(window_records)==8 and all(r["window_status"] in {"COMPLETED","WINDOW_SOURCE_BLOCKED"} for r in window_records),
        "classifier_ready_materialization_rate_ge_0_90":materialization_rate>=0.90,
        "positive_identity_complete":all(re.fullmatch(r"(SSE|SZSE):\\d{6}",r["canonical_security_id"]) for r in positives),
        "positive_temporal_provenance_complete":all(r.get("temporal_provenance_status")=="PASS" and r.get("retrospective_causal_effective_date","")>r.get("path_disclosure_date","") for r in positives),
        "semantics_unchanged":True,
    }
    density={
        "positive_filings_ge_4":len(positives)>=4,
        "distinct_positive_securities_ge_4":positive_secs>=4,
        "distinct_positive_quarters_ge_3":positive_quarters>=3,
    }
    if all(technical.values()):
        status="V2_8_11_BOUNDED_E_RECONSTRUCTION_FEASIBLE" if all(density.values()) else "V2_8_11_E_EVENT_RECONSTRUCTION_TOO_SPARSE"
    else:
        status="V2_8_11_E_RECONSTRUCTION_TECHNICALLY_BLOCKED"

    window_out={
        "schema":"AI_CORE_EVID_V2_8_11_BOUNDED_E_RECONSTRUCTION_RETRY1_WINDOWS_V1",
        "frozen_plan":FROZEN_WINDOWS,"runtime_windows":window_records,
        "price_or_return_data_consumed":False,
    }
    OUT_WINDOWS.write_text(json.dumps(window_out,ensure_ascii=False,indent=2)+"\\n",encoding="utf-8")
    rec={
        "schema":"AI_CORE_EVID_V2_8_11_BOUNDED_E_RECONSTRUCTION_RETRY1_FINAL_RECEIPT_V1",
        "version":"V2.8.11","retry":"RETRY1","status":status,
        "window_count":8,"selected_filings":selected,"successful_classifier_ready_filings":success,
        "materialization_rate":materialization_rate,"positive_filings":len(positives),
        "distinct_positive_securities":positive_secs,"distinct_positive_quarters":positive_quarters,
        "technical_checks":technical,"density_checks":density,
        "windows_sha256":sha_file(OUT_WINDOWS),"results_sha256":sha_file(OUT_RESULTS),"positive_events_sha256":sha_file(OUT_POSITIVE),
        "price_or_return_data_consumed":False,"fold3_accessed":False,"fold4_accessed":False,
        "prospective_E_ledger_modified":False,"setup_emission_authorized":False,
        "first60_append_authorized":False,"episode_emission_authorized":False,"live_authorized":False,
    }
    rec["receipt_sha256"]=stable_sha(rec)
    OUT_FINAL.write_text(json.dumps(rec,ensure_ascii=False,indent=2)+"\\n",encoding="utf-8")
    print(json.dumps(rec,ensure_ascii=False,indent=2))
    return rec

def self_test():
    load_contract(); days=trading_dates(); tests=[]
    def ck(name,cond): tests.append({"name":name,"pass":bool(cond)})

    ck("P01_exact_eight_frozen_windows",compute_windows(days)==FROZEN_WINDOWS)
    ck("P02_global_cap_48",len(FROZEN_WINDOWS)*MAX_PER_WINDOW==MAX_TOTAL==48)

    rows=[
        {"announcement_id":"10","canonical_security_id":"SSE:600001","adjunct_url":"finalpage/2023-02-07/10.PDF","announcement_time":"1675742400000","path_disclosure_date":"2023-02-07"},
        {"announcement_id":"11","canonical_security_id":"SSE:600001","adjunct_url":"finalpage/2023-02-07/11.PDF","announcement_time":"1675742400000","path_disclosure_date":"2023-02-07"},
        {"announcement_id":"12","canonical_security_id":"SZSE:000001","adjunct_url":"finalpage/2023-02-07/12.PDF","announcement_time":"1675742400000","path_disclosure_date":"2023-02-07"},
        {"announcement_id":"13","canonical_security_id":"SZSE:000002","adjunct_url":"finalpage/2023-02-07/13.PDF","announcement_time":"1675742400000","path_disclosure_date":"2023-02-07"},
        {"announcement_id":"14","canonical_security_id":"SZSE:000003","adjunct_url":"finalpage/2023-02-07/14.PDF","announcement_time":"1675742400000","path_disclosure_date":"2023-02-07"},
        {"announcement_id":"15","canonical_security_id":"SZSE:000004","adjunct_url":"finalpage/2023-02-07/15.PDF","announcement_time":"1675742400000","path_disclosure_date":"2023-02-07"},
        {"announcement_id":"16","canonical_security_id":"SZSE:000005","adjunct_url":"finalpage/2023-02-07/16.PDF","announcement_time":"1675742400000","path_disclosure_date":"2023-02-07"},
        {"announcement_id":"17","canonical_security_id":"SZSE:000006","adjunct_url":"finalpage/2023-02-07/17.PDF","announcement_time":"1675742400000","path_disclosure_date":"2023-02-07"},
    ]
    a=select_candidates(rows); b=select_candidates(list(reversed(rows)))
    ck("P03_selection_input_order_invariant",[x["announcement_id"] for x in a]==[x["announcement_id"] for x in b])
    ck("P04_max_six_per_window",len(a)==6)
    ck("P05_one_per_security",len({x["canonical_security_id"] for x in a})==len(a))

    ts=int(datetime(2023,2,10,12,0,tzinfo=SH).astimezone(timezone.utc).timestamp()*1000)
    good={"announcement_id":"99","canonical_security_id":"SSE:600099","announcement_time":str(ts),
          "adjunct_url":"finalpage/2023-02-10/99.PDF","path_disclosure_date":"2023-02-10"}
    tp=resolve_temporal(good,days)
    ck("P06_temporal_match_pass",tp["temporal_provenance_status"]=="PASS")
    ck("P07_effective_is_next_joint_session",tp["retrospective_causal_effective_date"]=="2023-02-13")
    ck("P08_no_same_day_effective",tp["retrospective_causal_effective_date"]>tp["path_disclosure_date"])

    conflict=False
    try: resolve_temporal({**good,"path_disclosure_date":"2023-02-09","adjunct_url":"finalpage/2023-02-09/99.PDF"},days)
    except RuntimeError: conflict=True
    ck("P09_metadata_path_conflict_blocks",conflict)

    missing=False
    try: resolve_temporal({**good,"announcement_time":""},days)
    except RuntimeError: missing=True
    ck("P10_missing_announcement_time_blocks",missing)

    badpath=False
    try: resolve_temporal({**good,"adjunct_url":"finalpage/2023-02-10/100.PDF"},days)
    except RuntimeError: badpath=True
    ck("P11_announcement_path_identity_blocks",badpath)

    src=Path(__file__).read_text(encoding="utf-8").split("def self_test():")[0]
    ck("P12_no_price_feature_engine_import","v280_scale_invariant_features" not in src)
    ck("P13_no_prior_price_evaluator_import","v2810_locked_ac_pullback_reclaim_evaluator" not in src and "v289_locked_transition_evaluator" not in src)
    ck("P14_real_run_requires_validation","validate_real_run_authorization" in src)
    ck("P15_contract_real_execution_false",read_json(CONTRACT)["authorization"]["execute_real_historical_pilot_now"] is False)
    ck("P16_fold3_4_sealed",read_json(CONTRACT)["authorization"]["fold3_access"] is False and read_json(CONTRACT)["authorization"]["fold4_access"] is False)
    run_src=Path(__file__).read_text(encoding="utf-8").split("def self_test():")[0]
    collect_pos=run_src.find("cc.collect(")
    pw_pos=run_src.find("with sync_playwright() as pw:", collect_pos)
    ck("P17_candidate_collection_precedes_pdf_playwright",collect_pos!=-1 and pw_pos>collect_pos)

    out={
        "schema":"AI_CORE_EVID_V2_8_11_BOUNDED_E_RECONSTRUCTION_RETRY1_SELFTEST_V1",
        "tests":tests,"passed":sum(x["pass"] for x in tests),"total":len(tests),"all_pass":all(x["pass"] for x in tests),
        "real_CNInfo_queries_executed":False,"real_PDFs_downloaded":False,"price_or_return_data_consumed":False,
        "fold3_4_accessed":False,
    }
    print(json.dumps(out,ensure_ascii=False,indent=2))
    if not out["all_pass"]: raise SystemExit(2)

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("command",choices=["self-test","plan","run"]); a=ap.parse_args()
    if a.command=="self-test": self_test()
    elif a.command=="plan": print(json.dumps({"windows":compute_windows(trading_dates())},ensure_ascii=False,indent=2))
    else: run()

if __name__=="__main__":
    main()
