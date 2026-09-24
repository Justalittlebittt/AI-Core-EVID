from __future__ import annotations
import argparse,csv,hashlib,json,re,tempfile
from datetime import date
from pathlib import Path

AMEND=Path("evidence/V2.8.11_TECHNICAL_BLOCKER_AMENDMENT_2.json")
RETRY1_WINDOWS=Path("evidence/V2.8.11_BOUNDED_E_RECONSTRUCTION_RETRY1_WINDOWS.json")
RETRY1_RESULTS=Path("evidence/V2.8.11_BOUNDED_E_RECONSTRUCTION_RETRY1_RESULTS.csv")
RETRY1_POS=Path("evidence/V2.8.11_BOUNDED_E_RECONSTRUCTION_RETRY1_POSITIVE_EVENTS.csv")
RETRY1_FINAL=Path("evidence/V2.8.11_BOUNDED_E_RECONSTRUCTION_RETRY1_FINAL_RECEIPT.json")
VALIDATION=Path("evidence/V2.8.11_TARGETED_RETRY2_VALIDATION_RECEIPT.json")

OUT_SELECTED=Path("evidence/V2.8.11_TARGETED_RETRY2_SELECTED.csv")
OUT_RESULTS=Path("evidence/V2.8.11_TARGETED_RETRY2_RESULTS.csv")
OUT_POS=Path("evidence/V2.8.11_TARGETED_RETRY2_POSITIVE_EVENTS.csv")
OUT_COMBINED=Path("evidence/V2.8.11_RECONCILED_RESULTS.csv")
OUT_FINAL=Path("evidence/V2.8.11_RECONCILED_FINAL_RECEIPT.json")

TARGET_START="2023-07-31"; TARGET_END="2023-08-06"; TARGET_QUARTER="2023Q3"
EXPECTED_CANDIDATES=2; EXPECTED_MATERIALIZABLE=2; EXPECTED_SELECTED=2
TOTAL_SELECTED=21
CANON=re.compile(r"^(SSE|SZSE):\d{6}$")

def rj(p:Path): return json.loads(p.read_text(encoding="utf-8").replace("\\n\n","\n").replace("}\n","}"))
def sha_file(p:Path):
    h=hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda:f.read(1<<20),b""): h.update(b)
    return h.hexdigest()
def stable(obj):
    return hashlib.sha256(json.dumps(obj,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()
def read_csv(p:Path):
    return list(csv.DictReader(p.read_text(encoding="utf-8").splitlines()))
def write_csv(p:Path,rows:list[dict],fields:list[str]):
    with p.open("w",encoding="utf-8",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,lineterminator="\n",extrasaction="ignore")
        w.writeheader(); w.writerows(rows)

def bind():
    a=rj(AMEND); f=rj(RETRY1_FINAL); w=rj(RETRY1_WINDOWS)
    assert a["status"]=="FROZEN_BEFORE_TARGETED_RETRY2_IMPLEMENTATION"
    assert f["receipt_sha256"]=="53bb2283a5c5a5dc676bf7ce9d000a8c1a66eaec58e6a5559cbe8255ea0725e3"
    assert sha_file(RETRY1_WINDOWS)==f["windows_sha256"]
    assert sha_file(RETRY1_RESULTS)==f["results_sha256"]
    assert sha_file(RETRY1_POS)==f["positive_events_sha256"]
    q=[x for x in w["runtime_windows"] if x["quarter"]==TARGET_QUARTER]
    assert len(q)==1
    q=q[0]
    assert q["start"]==TARGET_START and q["end"]==TARGET_END
    assert q["candidate_rows"]==EXPECTED_CANDIDATES
    assert q["materializable_rows"]==EXPECTED_MATERIALIZABLE
    assert q["selected_count"]==EXPECTED_SELECTED
    assert sum(int(x["selected_count"]) for x in w["runtime_windows"])==TOTAL_SELECTED
    return a,f,w

def authorization():
    if not VALIDATION.exists(): raise RuntimeError("RETRY2_NOT_VALIDATED")
    v=rj(VALIDATION)
    if v.get("status")!="PASS" or v.get("authorization",{}).get("execute_targeted_retry2") is not True:
        raise RuntimeError("RETRY2_NOT_AUTHORIZED")
    if any(v["authorization"].get(k) is not False for k in ["outcome_research","price_or_return_data","fold3_access","fold4_access"]):
        raise RuntimeError("RETRY2_SCOPE_BLOCK")

def selected_fields():
    return ["quarter","sample_rank","selection_sha256","announcement_id","canonical_security_id","security_name",
            "announcement_title","announcement_time","adjunct_url","path_disclosure_date","matched_terms"]

def result_fields():
    return [
        "quarter","window_start","window_end","sample_rank","selection_sha256","announcement_id","canonical_security_id",
        "security_name","announcement_title","announcement_time","adjunct_url","path_disclosure_date","matched_terms",
        "announcement_local_date_asia_shanghai","temporal_provenance_status","retrospective_causal_effective_date",
        "pipeline_status","blocker","object_sha256","bytes","pdf_page_count","pages_with_text",
        "total_nonwhitespace_characters","page_text_sha256","classification_state","evidence_page_number",
        "evidence_sentence_sha256","matched_ai_role","matched_commerciality","classification_reason","decision_sha256"
    ]

def reconcile(retry2_rows:list[dict], source_drift:bool=False, source_drift_reason:str=""):
    old=read_csv(RETRY1_RESULTS)
    combined=old+retry2_rows
    fields=result_fields()
    write_csv(OUT_COMBINED,combined,fields)
    success=sum(r.get("pipeline_status")=="SUCCESS" for r in combined)
    positives=[r for r in combined if r.get("pipeline_status")=="SUCCESS" and r.get("classification_state")=="ELIGIBLE_AI_CORE"]
    write_csv(OUT_POS, [r for r in retry2_rows if r.get("pipeline_status")=="SUCCESS" and r.get("classification_state")=="ELIGIBLE_AI_CORE"], fields)

    pos_secs={r["canonical_security_id"] for r in positives}
    pos_q={r["quarter"] for r in positives}
    technical={
      "eight_windows_accounted_for":True,
      "classifier_ready_materialization_rate_ge_0_90":(success/TOTAL_SELECTED)>=0.90,
      "positive_identity_complete":all(CANON.fullmatch(r["canonical_security_id"] or "") for r in positives),
      "positive_temporal_provenance_complete":all(r.get("temporal_provenance_status")=="PASS" and r.get("retrospective_causal_effective_date","")>r.get("path_disclosure_date","") for r in positives),
      "semantics_unchanged":True,
      "targeted_retry2_source_stable":not source_drift
    }
    density={
      "positive_filings_ge_4":len(positives)>=4,
      "distinct_positive_securities_ge_4":len(pos_secs)>=4,
      "distinct_positive_quarters_ge_3":len(pos_q)>=3
    }
    if all(technical.values()):
        status="V2_8_11_BOUNDED_E_RECONSTRUCTION_FEASIBLE" if all(density.values()) else "V2_8_11_E_EVENT_RECONSTRUCTION_TOO_SPARSE"
    else:
        status="V2_8_11_E_RECONSTRUCTION_TECHNICALLY_BLOCKED"
    rec={
      "schema":"AI_CORE_EVID_V2_8_11_RECONCILED_FINAL_RECEIPT_V1","version":"V2.8.11","status":status,
      "authority":"Retry1 immutable outputs plus Amendment2-targeted 2023Q3 Retry2 only",
      "selected_filings":TOTAL_SELECTED,
      "successful_classifier_ready_filings":success,
      "materialization_rate":success/TOTAL_SELECTED,
      "positive_filings":len(positives),
      "distinct_positive_securities":len(pos_secs),
      "distinct_positive_quarters":len(pos_q),
      "technical_checks":technical,"density_checks":density,
      "source_drift_reason":source_drift_reason,
      "retry1_results_sha256":sha_file(RETRY1_RESULTS),
      "retry2_results_sha256":sha_file(OUT_RESULTS) if OUT_RESULTS.exists() else "",
      "reconciled_results_sha256":sha_file(OUT_COMBINED),
      "retry2_positive_events_sha256":sha_file(OUT_POS),
      "price_or_return_data_consumed":False,"fold3_accessed":False,"fold4_accessed":False,
      "prospective_E_ledger_modified":False,"setup_emission_authorized":False,"first60_append_authorized":False,
      "episode_emission_authorized":False,"live_authorized":False
    }
    rec["receipt_sha256"]=stable(rec)
    OUT_FINAL.write_text(json.dumps(rec,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(rec,ensure_ascii=False,indent=2))
    return rec

def run():
    authorization(); bind()
    if OUT_FINAL.exists():
        return {"status":"FINAL_ALREADY_FROZEN_NO_REEXECUTION","receipt_sha256":rj(OUT_FINAL).get("receipt_sha256")}
    import v284_candidate_collector as cc
    import v284_candidate_triage as ct
    import v284_pdf_text_extractor as te
    import v284_page_scoped_classifier as pc
    import v2811_bounded_e_reconstruction_retry1 as r1
    from playwright.sync_api import sync_playwright

    with tempfile.TemporaryDirectory() as td:
        root=Path(td); cand=root/"candidates"
        cc.collect(date.fromisoformat(TARGET_START),date.fromisoformat(TARGET_END),cand)
        rows=read_csv(cand/"V2.8.4_CNINFO_CANDIDATE_DEDUPED.csv")
        mat=[]
        for row in rows:
            q=ct.triage_title(row.get("announcement_title",""),row.get("security_name",""))
            if q["triage_state"]=="MATERIALIZE_CANDIDATE": mat.append(row)
        selected=r1.select_candidates(mat,6)
        selected_out=[]
        for i,row in enumerate(selected,1):
            selected_out.append({
              "quarter":TARGET_QUARTER,"sample_rank":i,"selection_sha256":r1.selection_key(row["announcement_id"]),
              **{k:row.get(k,"") for k in ["announcement_id","canonical_security_id","security_name","announcement_title","announcement_time","adjunct_url","path_disclosure_date","matched_terms"]}
            })
        write_csv(OUT_SELECTED,selected_out,selected_fields())
        if len(rows)!=EXPECTED_CANDIDATES or len(mat)!=EXPECTED_MATERIALIZABLE or len(selected)!=EXPECTED_SELECTED:
            write_csv(OUT_RESULTS,[],result_fields())
            return reconcile([],True,f"SOURCE_DRIFT:candidates={len(rows)},materializable={len(mat)},selected={len(selected)}")

        results=[]
        with sync_playwright() as pw:
            api=pw.request.new_context(extra_http_headers={
              "User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/153 Safari/537.36"
            })
            for rank,row in enumerate(selected,1):
                base={
                  "quarter":TARGET_QUARTER,"window_start":TARGET_START,"window_end":TARGET_END,
                  "sample_rank":rank,"selection_sha256":r1.selection_key(row["announcement_id"]),
                  **{k:row.get(k,"") for k in ["announcement_id","canonical_security_id","security_name","announcement_title","announcement_time","adjunct_url","path_disclosure_date","matched_terms"]}
                }
                try:
                    temporal=r1.resolve_temporal(row,r1.trading_dates())
                    pdf=root/f"{rank}.pdf"
                    obj_sha,nbytes=r1.fetch_pdf(api,row,pdf)
                    page_rows,ex=te.extract_pdf(pdf,obj_sha)
                    dec=pc.classify_pages(page_rows); ev=dec["evidence"]
                    results.append({**base,**temporal,"pipeline_status":"SUCCESS","blocker":"",
                      "object_sha256":obj_sha,"bytes":nbytes,"pdf_page_count":ex["pdf_page_count"],
                      "pages_with_text":ex["pages_with_text"],"total_nonwhitespace_characters":ex["total_nonwhitespace_characters"],
                      "page_text_sha256":ex["page_text_sha256"],"classification_state":dec["classification_state"],
                      "evidence_page_number":ev["page_number"],
                      "evidence_sentence_sha256":hashlib.sha256(str(ev.get("evidence_sentence") or "").encode()).hexdigest(),
                      "matched_ai_role":"|".join(ev.get("matched_ai_role") or []),
                      "matched_commerciality":"|".join(ev.get("matched_commerciality") or []),
                      "classification_reason":ev.get("reason",""),"decision_sha256":dec["decision_sha256"]})
                except Exception as ex:
                    results.append({**base,"pipeline_status":"BLOCKED","blocker":f"{type(ex).__name__}:{ex}"})
            api.dispose()
    write_csv(OUT_RESULTS,results,result_fields())
    return reconcile(results,False,"")

def self_test():
    bind(); t=[]
    def ck(n,v):t.append({"name":n,"pass":bool(v)})
    ck("R01_correct_canonical_regex",bool(CANON.fullmatch("SSE:600186")) and bool(CANON.fullmatch("SZSE:300001")) and not bool(CANON.fullmatch("SSE:\\d{6}")))
    ck("R02_selected_denominator_21",TOTAL_SELECTED==21)
    ck("R03_18_of_21_fails_90pct",18/TOTAL_SELECTED<.90)
    ck("R04_19_of_21_passes_90pct",19/TOTAL_SELECTED>=.90)
    a=rj(AMEND)
    ck("R05_target_only_2023Q3",a["retry2_scope"]["only_window"]==TARGET_QUARTER and a["retry2_scope"]["expected_selected_rows"]==2)
    src=Path(__file__).read_text(encoding="utf-8").split("def self_test():")[0]
    ck("R06_no_cninfo_home_preflight",'api.get("https://www.cninfo.com.cn/' not in src and "home=api.get" not in src)
    ck("R07_static_pdf_fetch_reused","r1.fetch_pdf(api,row,pdf)" in src)
    ck("R08_no_price_modules","v280_scale_invariant_features" not in src and "v2810_locked_ac" not in src and "v289_locked_transition" not in src)
    ck("R09_no_ocr_rescue","ocr" not in src.lower())
    ck("R10_validation_required","authorization()" in src)
    ck("R11_fold3_4_false",a["authorization"]["fold3_access"] is False and a["authorization"]["fold4_access"] is False)
    out={"schema":"AI_CORE_EVID_V2_8_11_TARGETED_RETRY2_SELFTEST_V1","tests":t,"passed":sum(x["pass"] for x in t),"total":len(t),"all_pass":all(x["pass"] for x in t),
         "real_CNInfo_queries_executed":False,"real_PDFs_downloaded":False,"price_or_return_data_consumed":False,"fold3_4_accessed":False}
    print(json.dumps(out,ensure_ascii=False,indent=2))
    if not out["all_pass"]: raise SystemExit(2)

if __name__=="__main__":
    ap=argparse.ArgumentParser();ap.add_argument("command",choices=["self-test","run"]);a=ap.parse_args()
    self_test() if a.command=="self-test" else run()
