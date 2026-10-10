from __future__ import annotations

import argparse
import csv
import json
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import v2812_shadow_accumulator as acc
import v284_e_layer_effective_date as ed

AMENDMENT=Path("evidence/V2.8.12_PROSPECTIVE_IDENTITY_COMPLETION_RATIFICATION_AMENDMENT_1.json")
BINDINGS=Path("evidence/V2.8.4_E_LAYER_ISSUER_IDENTITY_BINDINGS.csv")
OBS_LEDGER=Path("evidence/V2.8.4_E_LAYER_OBSERVATION_LEDGER.csv")
RUNS=Path("evidence/v284_prospective_runs")
SHADOW=Path("evidence/V2.8.12_PROSPECTIVE_E_SHADOW_LEDGER.csv")
STATUS=Path("evidence/V2.8.12_SHADOW_INFORMATION_GATE_STATUS.json")
RAT_DIR=Path("evidence/v2812_identity_ratifications")


def load_csv(path:Path)->list[dict]:
    if not path.exists():
        return []
    return list(csv.DictReader(path.read_text(encoding="utf-8").splitlines()))


def normalize_utc(value:str)->str:
    dt=datetime.fromisoformat(str(value).replace("Z","+00:00")).astimezone(timezone.utc)
    return dt.isoformat(timespec="seconds").replace("+00:00","Z")


def later_utc(a:str,b:str)->str:
    aa=datetime.fromisoformat(normalize_utc(a).replace("Z","+00:00"))
    bb=datetime.fromisoformat(normalize_utc(b).replace("Z","+00:00"))
    return normalize_utc(a if aa>=bb else b)


def amendment_guard():
    obj=json.loads(AMENDMENT.read_text(encoding="utf-8"))
    if obj.get("status") not in {
        "FROZEN_BEFORE_GENERIC_RATIFIER_IMPLEMENTATION",
        "ACTIVE_VALIDATED_GENERIC_IDENTITY_COMPLETION_RATIFICATION",
    }:
        raise RuntimeError("IDENTITY_RATIFICATION_AMENDMENT_NOT_ACTIVE_OR_FROZEN")
    g=obj.get("governance") or {}
    required_false=[
        "classifier_changed","triage_changed","identity_rule_changed","effective_date_rule_changed",
        "readiness_thresholds_changed","outcome_research_authorized","price_or_return_data_authorized",
        "historical_full_backfill_authorized","fold3_access","fold4_access","setup_emission_authorized",
        "first60_append_authorized","episode_emission_authorized","live_authorized",
        "brokerage_execution_authorized","autonomous_financial_decision_authorized",
    ]
    if any(g.get(k) is not False for k in required_false):
        raise RuntimeError("IDENTITY_RATIFICATION_GOVERNANCE_BLOCK")
    return obj


def binding_for(cid:str)->dict|None:
    rows=load_csv(BINDINGS)
    matches=[r for r in rows if r.get("canonical_security_id")==cid]
    if not matches:
        return None
    names={r.get("issuer_legal_name","").strip() for r in matches}
    states={r.get("binding_state","").strip() for r in matches}
    if len(names)!=1 or "" in names or states!={"OFFICIAL_CNINFO_IDENTITY_BOUND"}:
        raise RuntimeError(f"IDENTITY_BINDING_CONFLICT:{cid}")
    row=matches[0]
    lines=BINDINGS.read_text(encoding="utf-8").splitlines()
    line_no=None
    for i,line in enumerate(lines[1:],start=2):
        parsed=next(csv.reader([line]))
        if len(parsed)>=3 and parsed[0]==cid and parsed[2]==row["issuer_legal_name"]:
            line_no=i
            break
    if line_no is None:
        raise RuntimeError(f"IDENTITY_BINDING_ROW_NOT_FOUND:{cid}")
    blame=subprocess.check_output(
        ["git","blame","-L",f"{line_no},{line_no}","--porcelain",str(BINDINGS)],text=True
    )
    commit=blame.splitlines()[0].split()[0]
    committed_at=subprocess.check_output(["git","show","-s","--format=%cI",commit],text=True).strip()
    return {**row,"binding_commit_sha":commit,"binding_committed_at_utc":normalize_utc(committed_at)}


def result_row(run_id:str,aid:str)->dict:
    p=RUNS/f"V2.8.4_PROSPECTIVE_OBSERVATION_RESULTS_{run_id}.csv"
    hits=[r for r in load_csv(p) if r.get("announcement_id")==aid]
    if len(hits)!=1:
        raise RuntimeError(f"OBSERVATION_RESULT_JOIN_BLOCK:{aid}")
    return hits[0]


def observation_row(aid:str)->dict:
    hits=[r for r in load_csv(OBS_LEDGER) if r.get("announcement_id")==aid]
    if len(hits)!=1:
        raise RuntimeError(f"OBSERVATION_LEDGER_JOIN_BLOCK:{aid}")
    return hits[0]


def plan_candidates()->list[dict]:
    amendment_guard()
    planned=[]
    for fp in sorted(RUNS.glob("V2.8.4_PROSPECTIVE_FINALIZATION_RECEIPT_*.json")):
        f=json.loads(fp.read_text(encoding="utf-8"))
        if f.get("status")!="FINALIZED_WITH_BLOCKED_POSITIVE_RECORD":
            continue
        if f.get("historical_backfill") is not False or f.get("price_or_return_data_consumed") is not False:
            raise RuntimeError(f"FINALIZATION_PROVENANCE_BLOCK:{fp.name}")
        run_id=str(f.get("run_id") or "")
        observation_commit=str(f.get("observation_commit_sha") or "")
        for r in f.get("blocked_incomplete_positive_records") or []:
            if r.get("classification_state")!="ELIGIBLE_AI_CORE":
                continue
            if r.get("record_complete") is not False:
                continue
            if r.get("eligibility_effect")!="BLOCKED_INCOMPLETE_POSITIVE_EVIDENCE_RECORD":
                continue
            if str(r.get("issuer_legal_name") or "").strip() or str(r.get("issuer_identity_basis") or "").strip():
                raise RuntimeError(f"BLOCKED_RECORD_NOT_IDENTITY_ONLY:{r.get('announcement_id')}")
            required=["canonical_security_id","announcement_id","source_object_sha256","page_number","evidence_text","matched_ai_role","matched_commerciality","authoritative_observed_at_utc"]
            if any(r.get(k) in (None,"",[]) for k in required):
                raise RuntimeError(f"BLOCKED_RECORD_OTHER_COMPLETENESS_GAP:{r.get('announcement_id')}")
            cid=str(r["canonical_security_id"])
            aid=str(r["announcement_id"])
            binding=binding_for(cid)
            if binding is None:
                continue
            o=result_row(run_id,aid)
            l=observation_row(aid)
            if o.get("pipeline_status")!="SUCCESS" or o.get("classification_state")!="ELIGIBLE_AI_CORE":
                raise RuntimeError(f"ORIGINAL_CLASSIFICATION_JOIN_BLOCK:{aid}")
            if l.get("diagnostic_or_prospective_mode")!="PROSPECTIVE" or l.get("classification_state")!="ELIGIBLE_AI_CORE":
                raise RuntimeError(f"OBSERVATION_NOT_PROSPECTIVE_ELIGIBLE:{aid}")
            if l.get("first_observation_commit_sha")!=observation_commit:
                raise RuntimeError(f"OBSERVATION_COMMIT_MISMATCH:{aid}")
            if l.get("object_sha256")!=r.get("source_object_sha256") or o.get("object_sha256")!=r.get("source_object_sha256"):
                raise RuntimeError(f"SOURCE_OBJECT_MISMATCH:{aid}")
            if l.get("page_text_sha256")!=o.get("page_text_sha256") or l.get("decision_sha256")!=o.get("decision_sha256"):
                raise RuntimeError(f"DECISION_BINDING_MISMATCH:{aid}")
            observed=normalize_utc(str(r["authoritative_observed_at_utc"]))
            if normalize_utc(l.get("first_observed_at_utc"))!=observed:
                raise RuntimeError(f"OBSERVATION_TIME_MISMATCH:{aid}")
            completeness=later_utc(observed,binding["binding_committed_at_utc"])
            effective=ed.effective_date(completeness).isoformat()
            rat_path=RAT_DIR/f"V2.8.12_IDENTITY_COMPLETION_RATIFICATION_{aid}.json"
            ev={
                "announcement_id":aid,
                "canonical_security_id":cid,
                "issuer_legal_name":binding["issuer_legal_name"],
                "source_object_sha256":r["source_object_sha256"],
                "page_text_sha256":l["page_text_sha256"],
                "decision_sha256":l["decision_sha256"],
                "evidence_sentence_sha256":acc.sentence_hash(r["evidence_text"]),
                "matched_ai_role_json":json.dumps(r["matched_ai_role"],ensure_ascii=False,separators=(",",":")),
                "matched_commerciality_json":json.dumps(r["matched_commerciality"],ensure_ascii=False,separators=(",",":")),
                "evidence_observation_commit_sha":observation_commit,
                "issuer_identity_binding_commit_sha":binding["binding_commit_sha"],
                "authoritative_observed_at_utc":observed,
                "eligibility_completeness_time_utc":completeness,
                "effective_signal_date":effective,
                "source_finalization_receipt":str(fp),
                "source_ratification_file":str(rat_path),
                "historical_reconstruction":"false",
                "price_or_return_data_consumed":"false",
            }
            ev["shadow_event_id"]=acc.event_id(aid,cid,ev["decision_sha256"],effective)
            planned.append({
                "event":ev,
                "run_id":run_id,
                "binding":binding,
                "source_record":r,
                "ratification_path":rat_path,
            })
    planned.sort(key=lambda x:(x["event"]["authoritative_observed_at_utc"],x["event"]["announcement_id"]))
    return planned


def ratification_document(item:dict,event:dict)->dict:
    r=item["source_record"]
    b=item["binding"]
    doc={
        "schema":"AI_CORE_EVID_V2_8_12_PROSPECTIVE_IDENTITY_COMPLETION_RATIFICATION_V1",
        "version":"V2.8.12",
        "status":"RATIFIED_FOR_PROSPECTIVE_SHADOW_EFFECT",
        "event":{
            "announcement_id":event["announcement_id"],
            "canonical_security_id":event["canonical_security_id"],
            "issuer_legal_name":event["issuer_legal_name"],
            "classification_state":"ELIGIBLE_AI_CORE",
            "source_object_sha256":event["source_object_sha256"],
            "page_text_sha256":event["page_text_sha256"],
            "decision_sha256":event["decision_sha256"],
            "evidence_page_number":int(r["page_number"]),
            "matched_ai_role":r["matched_ai_role"],
            "matched_commerciality":r["matched_commerciality"],
        },
        "classification_authority":{
            "observation_run_id":item["run_id"],
            "observation_commit_sha":event["evidence_observation_commit_sha"],
            "observation_committed_at_utc":event["authoritative_observed_at_utc"],
            "source_finalization_receipt":event["source_finalization_receipt"],
            "original_record_complete":False,
            "original_eligibility_effect":"BLOCKED_INCOMPLETE_POSITIVE_EVIDENCE_RECORD",
            "classifier_semantics_changed":False,
            "decision_recomputed":False,
        },
        "issuer_identity_authority":{
            "contract":"evidence/V2.8.4_E_LAYER_ISSUER_IDENTITY_BINDING_CONTRACT.json",
            "binding_ledger":"evidence/V2.8.4_E_LAYER_ISSUER_IDENTITY_BINDINGS.csv",
            "binding_commit_sha":event["issuer_identity_binding_commit_sha"],
            "binding_committed_at_utc":b["binding_committed_at_utc"],
            "binding_state":b["binding_state"],
            "source_announcement_id":b["source_announcement_id"],
            "source_adjunct_url":b["source_adjunct_url"],
            "identity_only_not_AI_evidence":True,
        },
        "temporal_ratification":{
            "eligibility_completeness_time_utc":event["eligibility_completeness_time_utc"],
            "effective_date_rule":"first joint A-share trading date strictly after eligibility completeness time",
            "effective_signal_date":event["effective_signal_date"],
            "same_day_activation":False,
            "historical_backfill":False,
            "backdating":False,
        },
        "shadow_event":event,
        "governance":{
            "price_or_return_data_consumed":False,
            "outcome_research_authorized":False,
            "setup_or_episode_authorized":False,
            "live_authorized":False,
            "brokerage_execution_authorized":False,
        }
    }
    doc["receipt_sha256"]=acc.stable(doc)
    return doc


def write_json_idempotent(path:Path,obj:dict):
    text=json.dumps(obj,ensure_ascii=False,indent=2)+"\n"
    if path.exists():
        if path.read_text(encoding="utf-8")!=text:
            raise RuntimeError(f"RATIFICATION_IMMUTABILITY_CONFLICT:{path.name}")
        return False
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(text,encoding="utf-8")
    return True


def ratify(ledger_path:Path=SHADOW,status_path:Path=STATUS,rat_dir:Path=RAT_DIR)->dict:
    amendment_guard()
    existing=acc.rows(ledger_path)
    working=[dict(r) for r in existing]
    appended=0
    duplicate_noops=0
    created_receipts=[]
    planned=plan_candidates()
    for item in planned:
        ev=dict(item["event"])
        state=acc.assess(working,ev)
        if state=="BLOCK_CONFLICT":
            raise RuntimeError(f"SHADOW_CONFLICT:{ev['announcement_id']}")
        if state=="NO_ACTION_DUPLICATE":
            duplicate_noops+=1
            continue
        ev=acc.with_recurrence(working,ev)
        target=rat_dir/f"V2.8.12_IDENTITY_COMPLETION_RATIFICATION_{ev['announcement_id']}.json"
        ev["source_ratification_file"]=str(target)
        doc=ratification_document(item,ev)
        write_json_idempotent(target,doc)
        created_receipts.append(str(target))
        working.append(ev)
        appended+=1
    if appended:
        acc.write_rows(ledger_path,working)
    st=acc.status_document(working)
    status_text=json.dumps(st,ensure_ascii=False,indent=2)+"\n"
    status_changed=(not status_path.exists()) or status_path.read_text(encoding="utf-8")!=status_text
    if status_changed:
        status_path.write_text(status_text,encoding="utf-8")
    return {
        "status":"PASS",
        "planned_candidates":len(planned),
        "appended":appended,
        "duplicate_noops":duplicate_noops,
        "rows_after":len(working),
        "created_receipts":created_receipts,
        "readiness":st,
        "price_or_return_data_consumed":False,
    }


def self_test():
    amendment_guard()
    tests=[]
    def ck(name,cond): tests.append({"name":name,"pass":bool(cond)})
    planned=plan_candidates()
    aids=[x["event"]["announcement_id"] for x in planned]
    ck("R01_current_identity_blocked_candidates_discovered",aids==["1225585268","1225585270"])
    ck("R02_binding_commit_is_authoritative",all(x["event"]["issuer_identity_binding_commit_sha"]=="db2ea9a1f5ef6405a4de05e83831af099d04bcce" for x in planned))
    ck("R03_effective_date_is_next_trading_day",all(x["event"]["effective_signal_date"]=="2026-09-30" for x in planned))
    ck("R04_no_backdating",all(x["event"]["eligibility_completeness_time_utc"]=="2026-09-29T07:19:49Z" for x in planned))
    import ast
    tree=ast.parse(Path(__file__).read_text(encoding="utf-8"))
    imported=set()
    called=set()
    for node in ast.walk(tree):
        if isinstance(node,ast.Import):
            imported.update(a.name for a in node.names)
        elif isinstance(node,ast.ImportFrom):
            imported.add(node.module or "")
        elif isinstance(node,ast.Call):
            f=node.func
            if isinstance(f,ast.Name): called.add(f.id)
            elif isinstance(f,ast.Attribute): called.add(f.attr)
    ck("R05_no_classifier_recompute","v284_page_scoped_classifier" not in imported and "classify_pages" not in called)
    ck("R06_no_price_or_outcome_modules","v283_outcome_resolver" not in imported and not ({"fwd5","fwd10","benchmark_return","price_source"} & called))
    with tempfile.TemporaryDirectory() as td:
        td=Path(td)
        lp=td/"shadow.csv"
        sp=td/"status.json"
        rd=td/"rat"
        real_rows=acc.rows(SHADOW)
        genesis=[r for r in real_rows if r["announcement_id"]=="1225573666"]
        ck("R07_genesis_fixture_exactly_one",len(genesis)==1)
        acc.write_rows(lp,genesis)
        sp.write_text(json.dumps(acc.status_document(genesis),ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        out=ratify(lp,sp,rd)
        rows_after=acc.rows(lp)
        bee=[r for r in rows_after if r["canonical_security_id"]=="SZSE:301382"]
        ck("R08_two_events_append_once_from_genesis",out["appended"]==2 and len(rows_after)==3 and len(bee)==2)
        ck("R09_same_issuer_recurrence_preserved",bee[0]["issuer_positive_sequence_number"]=="1" and bee[0]["recurrence_status"]=="FIRST_POSITIVE_FOR_ISSUER" and bee[1]["issuer_positive_sequence_number"]=="2" and bee[1]["prior_positive_announcement_id"]=="1225585268")
        ck("R10_ratification_receipts_created",len(list(rd.glob("*.json")))==2)
        before_l=lp.read_bytes();before_s=sp.read_bytes();before_docs={q.name:q.read_bytes() for q in rd.glob("*.json")}
        out2=ratify(lp,sp,rd)
        after_docs={q.name:q.read_bytes() for q in rd.glob("*.json")}
        ck("R11_fixture_second_run_is_idempotent",out2["appended"]==0 and out2["duplicate_noops"]==2 and lp.read_bytes()==before_l and sp.read_bytes()==before_s and before_docs==after_docs)
        ck("R12_readiness_updates_without_opening_gate",out["rows_after"]==3 and out["readiness"]["full_shadow_event_count"]==3 and out["readiness"]["shadow_event_count"]==2 and out["readiness"]["status"]=="ACCUMULATING_PROSPECTIVE_E_EVENTS")
    with tempfile.TemporaryDirectory() as td:
        td=Path(td)
        lp=td/"current_shadow.csv"
        sp=td/"current_status.json"
        rd=td/"current_rat"
        lp.write_bytes(SHADOW.read_bytes())
        sp.write_bytes(STATUS.read_bytes())
        before_l=lp.read_bytes();before_s=sp.read_bytes()
        out3=ratify(lp,sp,rd)
        ck("R13_current_production_state_is_duplicate_noop",out3["appended"]==0 and out3["duplicate_noops"]==2 and lp.read_bytes()==before_l and sp.read_bytes()==before_s and not list(rd.glob("*.json")))
    result={
        "schema":"AI_CORE_EVID_V2_8_12_IDENTITY_COMPLETION_RATIFIER_SELFTEST_V1",
        "tests":tests,
        "passed":sum(x["pass"] for x in tests),
        "total":len(tests),
        "all_pass":all(x["pass"] for x in tests),
        "real_shadow_ledger_modified":False,
        "price_or_return_data_consumed":False,
        "fold3_4_accessed":False,
    }
    result["receipt_sha256"]=acc.stable(result)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    if not result["all_pass"]:
        raise SystemExit(2)


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("command",choices=["self-test","ratify"])
    a=ap.parse_args()
    if a.command=="self-test":
        self_test()
    else:
        print(json.dumps(ratify(),ensure_ascii=False,indent=2))


if __name__=="__main__":
    main()
