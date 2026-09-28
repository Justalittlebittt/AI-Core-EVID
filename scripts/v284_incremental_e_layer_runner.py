from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright

import v284_candidate_collector as cc
import v284_candidate_triage as ct
import v284_candidate_materialization as cm
import v284_pdf_text_extractor as te
import v284_page_scoped_classifier as pc
import v284_e_layer_observation_ledger as ledger
import v284_e_layer_effective_date as ed

ACTIVATION = Path("evidence/V2.8.4_PROSPECTIVE_E_LAYER_ACTIVATION.json")
INVENTORY = Path("evidence/V2.7.29_PRIMARY_LOCATOR_INVENTORY.csv")
LEDGER = Path("evidence/V2.8.4_E_LAYER_OBSERVATION_LEDGER.csv")
IDENTITY_BINDINGS = Path("evidence/V2.8.4_E_LAYER_ISSUER_IDENTITY_BINDINGS.csv")
STATIC = "https://static.cninfo.com.cn/"
CACHE_ROOT = Path(".cache/v284_e_layer")

RESULT_FIELDS = [
    "announcement_id","canonical_security_id","security_name","announcement_title",
    "disclosure_date","announcement_time","adjunct_url","matched_terms","triage_state",
    "pipeline_status","object_sha256","bytes","page_text_sha256","pdf_page_count",
    "pages_with_text","total_nonwhitespace_characters","classification_state",
    "evidence_page_number","evidence_sentence","matched_ai_role","matched_commerciality",
    "classification_reason","issuer_legal_name","issuer_identity_basis","decision_sha256","blocker"
]

def stable_sha256(obj)->str:
    b=json.dumps(obj,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()
    return hashlib.sha256(b).hexdigest()

def load_csv(path:Path)->list[dict]:
    if not path.exists():
        return []
    return list(csv.DictReader(path.read_text(encoding="utf-8").splitlines()))

def activation_guard()->dict:
    obj=json.loads(ACTIVATION.read_text(encoding="utf-8"))
    if obj.get("status")!="ACTIVE_PROSPECTIVE_EVIDENCE_LAYER_ONLY":
        raise RuntimeError("PROSPECTIVE_ACTIVATION_NOT_ACTIVE")
    auth=obj.get("authorization") or {}
    required=[
        "prospective_candidate_observation",
        "official_pdf_materialization_for_unseen_candidates",
        "page_text_extraction",
        "page_scoped_classification",
        "append_only_E_layer_observation_ledger",
        "effective_date_computation_for_new_positive_events",
    ]
    if not all(auth.get(k) is True for k in required):
        raise RuntimeError("PROSPECTIVE_ACTIVATION_SCOPE_INCOMPLETE")
    if auth.get("setup_emission") or auth.get("episode_emission") or auth.get("live_trading_or_signal_authorization"):
        raise RuntimeError("PROSPECTIVE_ACTIVATION_SCOPE_TOO_BROAD")
    return obj

def unseen_rows(rows:list[dict], existing:list[dict])->list[dict]:
    seen={str(r.get("announcement_id") or "").strip() for r in existing}
    return [r for r in rows if str(r.get("announcement_id") or "").strip() not in seen]

def load_identity_bindings(path:Path=IDENTITY_BINDINGS)->list[dict]:
    return load_csv(path)

def resolve_issuer_identity(page_rows:list[dict],row:dict,bindings:list[dict])->tuple[str,str]:
    cid=str(row.get("canonical_security_id") or "").strip()
    sn=re.sub(r"\s+","",str(row.get("security_name") or ""))
    exact=[x for x in bindings if str(x.get("canonical_security_id") or "").strip()==cid]
    if not exact:
        return "",""
    names={str(x.get("issuer_legal_name") or "").strip() for x in exact}
    short_names={re.sub(r"\s+","",str(x.get("security_name") or "")) for x in exact}
    if len(names)!=1 or not next(iter(names)) or (sn and short_names!={sn}):
        raise RuntimeError("ISSUER_IDENTITY_BINDING_CONFLICT")
    return next(iter(names)),"PREBOUND_OFFICIAL_ISSUER_IDENTITY"

def normalized_utc(ts:str)->str:
    dt=datetime.fromisoformat(str(ts).replace("Z","+00:00")).astimezone(timezone.utc)
    return dt.isoformat(timespec="seconds").replace("+00:00","Z")

def load_inventory()->list[dict]:
    if not INVENTORY.exists():
        return []
    return load_csv(INVENTORY)

def cache_map_path()->Path:
    return CACHE_ROOT/"locator_map.json"

def load_cache_map()->dict:
    p=cache_map_path()
    if not p.exists():
        return {}
    try:
        obj=json.loads(p.read_text(encoding="utf-8"))
        return obj if isinstance(obj,dict) else {}
    except Exception:
        return {}

def save_cache_map(obj:dict):
    CACHE_ROOT.mkdir(parents=True,exist_ok=True)
    cache_map_path().write_text(json.dumps(obj,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf-8")

def materialize(api,row:dict,inventory:list[dict],tmp:Path)->tuple[Path,dict]:
    column="sse" if row["exchange"]=="SSE" else "szse" if row["exchange"]=="SZSE" else ""
    hit={
        "column":column,
        "sec_code":row["security_code"],
        "announcement_id":row["announcement_id"],
        "adjunct_url":row["adjunct_url"],
    }
    loc=cm.resolve_locator(hit,inventory)
    aid=loc["announcement_id"]
    cmap=load_cache_map()
    cached=cmap.get(aid)
    if cached and cached.get("adjunct_url")==loc["adjunct_url"]:
        sha=str(cached.get("object_sha256") or "")
        cp=CACHE_ROOT/"pdf"/f"{sha}.pdf"
        if sha and cp.exists() and te.validate_pdf(cp,sha)==sha:
            return cp,{"object_sha256":sha,"bytes":cp.stat().st_size,"cache_hit":True,"locator_source":loc["locator_source"]}

    r=api.get(
        loc["official_url"],
        timeout=90000,
        headers={"Referer":"https://www.cninfo.com.cn/","Accept":"application/pdf,*/*;q=0.8"},
    )
    if r.status!=200:
        raise RuntimeError(f"PDF_FETCH_HTTP_{r.status}")
    b=r.body()
    v=cm.validate_pdf_bytes(b)
    cp=CACHE_ROOT/"pdf"/f"{v['object_sha256']}.pdf"
    cp.parent.mkdir(parents=True,exist_ok=True)
    cp.write_bytes(b)
    te.validate_pdf(cp,v["object_sha256"])
    cmap[aid]={"adjunct_url":loc["adjunct_url"],"object_sha256":v["object_sha256"]}
    save_cache_map(cmap)
    return cp,{**v,"cache_hit":False,"locator_source":loc["locator_source"]}

def scan(start:date,end:date,out_dir:Path,run_id:str,activation_sha:str,activation_at:str):
    activation_guard()
    out_dir.mkdir(parents=True,exist_ok=True)
    existing=ledger.load_rows(LEDGER)
    inventory=load_inventory()
    identity_bindings=load_identity_bindings()

    with tempfile.TemporaryDirectory() as td:
        tmp=Path(td)
        cand=tmp/"candidates"
        cc.collect(start,end,cand)
        rows=load_csv(cand/"V2.8.4_CNINFO_CANDIDATE_DEDUPED.csv")
        unseen=unseen_rows(rows,existing)

        skipped=[]
        materializable=[]
        for row in unseen:
            q=ct.triage_title(row.get("announcement_title",""),row.get("security_name",""))
            if q["triage_state"]=="MATERIALIZE_CANDIDATE":
                materializable.append((row,q))
            else:
                skipped.append((row,q))

        results=[]
        for row,q in skipped:
            results.append({
                "announcement_id":row["announcement_id"],
                "canonical_security_id":row["canonical_security_id"],
                "security_name":row["security_name"],
                "announcement_title":row["announcement_title"],
                "disclosure_date":row["path_disclosure_date"],
                "announcement_time":row.get("announcement_time",""),
                "adjunct_url":row["adjunct_url"],
                "matched_terms":row["matched_terms"],
                "triage_state":q["triage_state"],
                "pipeline_status":"SKIPPED_TRIAGE",
                "classification_state":"",
                "blocker":"",
            })

        with sync_playwright() as pw:
            api=pw.request.new_context(extra_http_headers={
                "User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/153 Safari/537.36"
            })
            for row,q in materializable:
                base={
                    "announcement_id":row["announcement_id"],
                    "canonical_security_id":row["canonical_security_id"],
                    "security_name":row["security_name"],
                    "announcement_title":row["announcement_title"],
                    "disclosure_date":row["path_disclosure_date"],
                    "announcement_time":row.get("announcement_time",""),
                    "adjunct_url":row["adjunct_url"],
                    "matched_terms":row["matched_terms"],
                    "triage_state":q["triage_state"],
                }
                try:
                    pdf,mat=materialize(api,row,inventory,tmp)
                    pages,extract=te.extract_pdf(pdf,mat["object_sha256"])
                    decision=pc.classify_pages(pages)
                    ev=decision["evidence"]
                    issuer_name,identity_basis=resolve_issuer_identity(pages,row,identity_bindings)
                    results.append({
                        **base,
                        "pipeline_status":"SUCCESS",
                        "object_sha256":mat["object_sha256"],
                        "bytes":mat["bytes"],
                        "page_text_sha256":extract["page_text_sha256"],
                        "pdf_page_count":extract["pdf_page_count"],
                        "pages_with_text":extract["pages_with_text"],
                        "total_nonwhitespace_characters":extract["total_nonwhitespace_characters"],
                        "classification_state":decision["classification_state"],
                        "evidence_page_number":ev["page_number"],
                        "evidence_sentence":ev["evidence_sentence"],
                        "matched_ai_role":json.dumps(ev.get("matched_ai_role") or [],ensure_ascii=False,separators=(",",":")),
                        "matched_commerciality":json.dumps(ev.get("matched_commerciality") or [],ensure_ascii=False,separators=(",",":")),
                        "classification_reason":ev["reason"],
                        "issuer_legal_name":issuer_name,
                        "issuer_identity_basis":identity_basis,
                        "decision_sha256":decision["decision_sha256"],
                        "blocker":"",
                    })
                except Exception as e:
                    results.append({
                        **base,
                        "pipeline_status":"BLOCKED",
                        "classification_state":"",
                        "blocker":f"{type(e).__name__}:{e}",
                    })
            api.dispose()

    result_path=out_dir/f"V2.8.4_PROSPECTIVE_OBSERVATION_RESULTS_{run_id}.csv"
    with result_path.open("w",encoding="utf-8",newline="") as f:
        w=csv.DictWriter(f,fieldnames=RESULT_FIELDS,lineterminator="\n",extrasaction="ignore")
        w.writeheader()
        w.writerows(results)

    successful=sum(r.get("pipeline_status")=="SUCCESS" for r in results)
    blocked=sum(r.get("pipeline_status")=="BLOCKED" for r in results)
    skipped_count=sum(r.get("pipeline_status")=="SKIPPED_TRIAGE" for r in results)
    states={}
    for r in results:
        s=r.get("classification_state")
        if r.get("pipeline_status")=="SUCCESS" and s:
            states[s]=states.get(s,0)+1

    receipt={
        "schema":"AI_CORE_EVID_V2_8_4_PROSPECTIVE_OBSERVATION_RECEIPT_V1",
        "version":"V2.8.4",
        "status":"OBSERVATION_COMPLETE" if blocked==0 else "OBSERVATION_COMPLETE_WITH_BLOCKERS",
        "run_id":run_id,
        "scan_window_start":start.isoformat(),
        "scan_window_end":end.isoformat(),
        "overlap_calendar_days":(end-start).days+1,
        "activation_commit_sha":activation_sha,
        "activation_committed_at_utc":normalized_utc(activation_at),
        "authoritative_observation_time":"GitHub committed_at of the commit that first adds this receipt",
        "existing_ledger_rows_before_scan":len(existing),
        "candidate_rows":len(rows),
        "already_observed_candidate_rows":len(rows)-len(unseen),
        "unseen_candidate_rows":len(unseen),
        "triage_skipped_count":skipped_count,
        "materialization_attempted_count":len(materializable),
        "successful_filings":successful,
        "blocked_filings":blocked,
        "classification_states":states,
        "results_file":result_path.name,
        "results_file_sha256":te.sha_file(result_path),
        "historical_diagnostic_rows_promoted":0,
        "prospective_backfill":False,
        "same_day_eligibility_activation":False,
        "price_or_return_data_consumed":False,
        "setup_or_episode_authorized":False,
        "live_authorized":False,
    }
    receipt["receipt_sha256"]=stable_sha256(receipt)
    rp=out_dir/f"V2.8.4_PROSPECTIVE_OBSERVATION_RECEIPT_{run_id}.json"
    rp.write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(receipt,ensure_ascii=False,indent=2))

def parsed_list(value)->list:
    if isinstance(value,list):
        return value
    if value in (None,""):
        return []
    try:
        out=json.loads(str(value))
    except json.JSONDecodeError as e:
        raise RuntimeError("EVIDENCE_LIST_JSON_BLOCKED") from e
    if not isinstance(out,list):
        raise RuntimeError("EVIDENCE_LIST_TYPE_BLOCKED")
    return out

def evidence_record(row:dict,observed_at_utc:str)->dict:
    state=row["classification_state"]
    if state!="ELIGIBLE_AI_CORE":
        return {}
    issuer=str(row.get("issuer_legal_name") or "").strip()
    identity_basis=str(row.get("issuer_identity_basis") or "").strip()
    sentence=str(row.get("evidence_sentence") or "").strip()
    page=int(row.get("evidence_page_number") or 0)
    roles=parsed_list(row.get("matched_ai_role"))
    commercial=parsed_list(row.get("matched_commerciality"))
    complete=bool(issuer and identity_basis and sentence and page>0 and roles and commercial)
    rec={
        "canonical_security_id":row["canonical_security_id"],
        "issuer_legal_name":issuer,
        "issuer_identity_basis":identity_basis,
        "document_type":"CNINFO_ISSUER_DISCLOSURE",
        "announcement_id":row["announcement_id"],
        "disclosure_date":row["disclosure_date"],
        "source_object_sha256":row["object_sha256"],
        "page_number":page,
        "evidence_text":sentence,
        "matched_ai_role":roles,
        "matched_commerciality":commercial,
        "classification_state":state,
        "authoritative_observed_at_utc":observed_at_utc,
        "record_complete":complete,
    }
    if complete:
        rec["effective_signal_date"]=ed.effective_date(observed_at_utc).isoformat()
    else:
        rec["eligibility_effect"]="BLOCKED_INCOMPLETE_POSITIVE_EVIDENCE_RECORD"
    return rec

def finalize(results_path:Path,receipt_path:Path,ledger_path:Path,out_path:Path,
             observation_commit_sha:str,observed_at:str):
    activation_guard()
    receipt=json.loads(receipt_path.read_text(encoding="utf-8"))
    if te.sha_file(results_path)!=receipt["results_file_sha256"]:
        raise RuntimeError("OBSERVATION_RESULTS_HASH_MISMATCH")
    observed_utc=normalized_utc(observed_at)
    existing=ledger.load_rows(ledger_path)
    working=[dict(r) for r in existing]
    planned=[]
    duplicate=0

    rows=load_csv(results_path)
    success=[r for r in rows if r.get("pipeline_status")=="SUCCESS"]
    for row in success:
        event={
            "announcement_id":row["announcement_id"],
            "canonical_security_id":row["canonical_security_id"],
            "adjunct_url":row["adjunct_url"],
            "object_sha256":row["object_sha256"],
            "page_text_sha256":row["page_text_sha256"],
            "decision_sha256":row["decision_sha256"],
            "diagnostic_or_prospective_mode":"PROSPECTIVE",
            "classification_state":row["classification_state"],
            "first_observation_commit_sha":observation_commit_sha,
            "first_observed_at_utc":observed_utc,
        }
        state=ledger.assess(working,event)
        if state.startswith("BLOCKED_"):
            raise RuntimeError(f"FINALIZATION_{state}:{row['announcement_id']}")
        if state=="NO_ACTION_DUPLICATE":
            duplicate+=1
            continue
        planned.append(event)
        working.append(event)

    if planned:
        ledger_path.parent.mkdir(parents=True,exist_ok=True)
        with ledger_path.open("w",encoding="utf-8",newline="") as f:
            w=csv.DictWriter(f,fieldnames=ledger.FIELDS,lineterminator="\n")
            w.writeheader()
            w.writerows(working)

    effective_events=[]
    blocked_positive_records=[]
    for row in success:
        rec=evidence_record(row,observed_utc)
        if not rec:
            continue
        if rec.get("record_complete"):
            effective_events.append(rec)
        else:
            blocked_positive_records.append(rec)

    out={
        "schema":"AI_CORE_EVID_V2_8_4_PROSPECTIVE_FINALIZATION_RECEIPT_V1",
        "version":"V2.8.4",
        "status":"FINALIZED" if not blocked_positive_records else "FINALIZED_WITH_BLOCKED_POSITIVE_RECORD",
        "run_id":receipt["run_id"],
        "observation_receipt":receipt_path.name,
        "observation_commit_sha":observation_commit_sha,
        "authoritative_observed_at_utc":observed_utc,
        "successful_observation_rows":len(success),
        "ledger_rows_before":len(existing),
        "ledger_rows_appended":len(planned),
        "ledger_duplicate_noops":duplicate,
        "ledger_rows_after":len(working),
        "effective_positive_events":effective_events,
        "blocked_incomplete_positive_records":blocked_positive_records,
        "historical_backfill":False,
        "same_day_eligibility_activation":False,
        "price_or_return_data_consumed":False,
        "setup_or_episode_authorized":False,
        "live_authorized":False,
    }
    out["receipt_sha256"]=stable_sha256(out)
    out_path.write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(out,ensure_ascii=False,indent=2))

def self_test():
    tests=[]
    def ck(name,cond): tests.append({"name":name,"pass":bool(cond)})

    existing=[{"announcement_id":"1"}]
    rows=[{"announcement_id":"1"},{"announcement_id":"2"}]
    ck("P01_unseen_filters_existing",[r["announcement_id"] for r in unseen_rows(rows,existing)]==["2"])

    bindings=[{
        "canonical_security_id":"SZSE:300634",
        "security_name":"彩讯股份",
        "issuer_legal_name":"彩讯科技股份有限公司",
    }]
    bound_row={"canonical_security_id":"SZSE:300634","security_name":"彩讯股份","security_code":"300634"}
    name,basis=resolve_issuer_identity([{"page_number":1,"text":"无关文本"}],bound_row,bindings)
    ck("P02_prebound_identity_resolves",name=="彩讯科技股份有限公司" and basis=="PREBOUND_OFFICIAL_ISSUER_IDENTITY")

    header_row={"canonical_security_id":"SSE:600001","security_name":"测试科技","security_code":"600001"}
    name2,basis2=resolve_issuer_identity([{
        "page_number":1,
        "text":"证券代码：600001 证券简称：测试科技 北京测试科技股份有限公司 关于人工智能业务的公告",
    }],header_row,[])
    ck("P03_unbound_page1_does_not_guess_identity",name2=="" and basis2=="")

    name3,basis3=resolve_issuer_identity([{
        "page_number":1,
        "text":"公司控股子公司北京云算科技有限公司已签订合同。",
    }],header_row,[])
    ck("P04_subsidiary_without_binding_rejected",name3=="" and basis3=="")

    conflict=False
    try:
        resolve_issuer_identity([],bound_row,bindings+[{
            "canonical_security_id":"SZSE:300634",
            "security_name":"彩讯股份",
            "issuer_legal_name":"错误名称股份有限公司",
        }])
    except RuntimeError:
        conflict=True
    ck("P05_identity_conflict_blocks",conflict)
    ck("P06_normalized_utc",normalized_utc("2026-09-22T14:34:38+08:00")=="2026-09-22T06:34:38Z")

    good={
        "classification_state":"ELIGIBLE_AI_CORE",
        "canonical_security_id":"SSE:600001",
        "issuer_legal_name":"测试股份有限公司",
        "issuer_identity_basis":"PREBOUND_OFFICIAL_ISSUER_IDENTITY",
        "announcement_id":"123",
        "disclosure_date":"2026-09-22",
        "object_sha256":"a"*64,
        "evidence_page_number":"2",
        "evidence_sentence":"公司AI服务器已向客户批量交付。",
        "matched_ai_role":["AI服务器"],
        "matched_commerciality":["批量交付"],
    }
    rec=evidence_record(good,"2026-09-22T06:34:38Z")
    ck("P07_positive_record_complete",rec.get("record_complete") is True)
    ck("P08_positive_next_day_effective",rec.get("effective_signal_date")=="2026-09-23")
    bad={**good,"issuer_identity_basis":""}
    rec2=evidence_record(bad,"2026-09-22T06:34:38Z")
    ck("P09_unbound_positive_blocks_effect",rec2.get("record_complete") is False and "effective_signal_date" not in rec2)
    non={**good,"classification_state":"NOT_ESTABLISHED"}
    ck("P10_nonpositive_has_no_effective_record",evidence_record(non,"2026-09-22T06:34:38Z")=={})
    bad_json=False
    try:
        parsed_list("[bad]")
    except RuntimeError:
        bad_json=True
    ck("P11_invalid_evidence_list_blocks",bad_json)

    result={
        "schema":"AI_CORE_EVID_V2_8_4_INCREMENTAL_PROSPECTIVE_RUNNER_SELFTEST_V4",
        "tests":tests,
        "passed":sum(x["pass"] for x in tests),
        "total":len(tests),
        "all_pass":all(x["pass"] for x in tests),
    }
    result["receipt_sha256"]=stable_sha256(result)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    if not result["all_pass"]:
        raise SystemExit(2)

def main():
    ap=argparse.ArgumentParser()
    sub=ap.add_subparsers(dest="cmd",required=True)
    sub.add_parser("self-test")

    s=sub.add_parser("scan")
    s.add_argument("--start",required=True)
    s.add_argument("--end",required=True)
    s.add_argument("--out",required=True)
    s.add_argument("--run-id",required=True)
    s.add_argument("--activation-sha",required=True)
    s.add_argument("--activation-at",required=True)

    f=sub.add_parser("finalize")
    f.add_argument("--results",required=True)
    f.add_argument("--receipt",required=True)
    f.add_argument("--ledger",default=str(LEDGER))
    f.add_argument("--out",required=True)
    f.add_argument("--observation-commit-sha",required=True)
    f.add_argument("--observed-at",required=True)

    a=ap.parse_args()
    if a.cmd=="self-test":
        self_test()
    elif a.cmd=="scan":
        scan(date.fromisoformat(a.start),date.fromisoformat(a.end),Path(a.out),a.run_id,a.activation_sha,a.activation_at)
    else:
        finalize(Path(a.results),Path(a.receipt),Path(a.ledger),Path(a.out),a.observation_commit_sha,a.observed_at)

if __name__=="__main__":
    main()
