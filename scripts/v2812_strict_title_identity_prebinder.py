from __future__ import annotations

import argparse
import ast
import csv
import json
import re
import tempfile
from collections import defaultdict
from pathlib import Path

import v2812_shadow_accumulator as acc

AMENDMENT=Path("evidence/V2.8.12_STRICT_TITLE_IDENTITY_PREBINDING_AMENDMENT_1.json")
BINDINGS=Path("evidence/V2.8.4_E_LAYER_ISSUER_IDENTITY_BINDINGS.csv")
RUNS=Path("evidence/v284_prospective_runs")
RECEIPT_DIR=Path("evidence/v2812_identity_bindings")
BINDING_FIELDS=[
    "canonical_security_id","security_name","issuer_legal_name","source_announcement_id",
    "source_adjunct_url","source_disclosure_date","identity_evidence_text","binding_state"
]
LEGAL_SUFFIXES=("股份有限公司","有限责任公司","有限公司")


def load_csv(path:Path)->list[dict]:
    if not path.exists():
        return []
    return list(csv.DictReader(path.read_text(encoding="utf-8").splitlines()))


def write_bindings(path:Path,rows:list[dict]):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open("w",encoding="utf-8",newline="") as f:
        w=csv.DictWriter(f,fieldnames=BINDING_FIELDS,lineterminator="\n")
        w.writeheader(); w.writerows(rows)


def amendment_guard():
    obj=json.loads(AMENDMENT.read_text(encoding="utf-8"))
    if obj.get("status") not in {"FROZEN_BEFORE_IMPLEMENTATION","ACTIVE_VALIDATED_STRICT_TITLE_IDENTITY_PREBINDING"}:
        raise RuntimeError("STRICT_TITLE_IDENTITY_AMENDMENT_NOT_FROZEN_OR_ACTIVE")
    g=obj.get("governance") or {}
    required_false=[
        "research_semantics_changed","classifier_changed","triage_changed",
        "identity_contract_broadened_beyond_official_cninfo","fuzzy_identity_inference_authorized",
        "readiness_thresholds_changed","outcome_research_authorized","price_or_return_data_authorized",
        "historical_full_backfill_authorized","fold3_access","fold4_access","setup_emission_authorized",
        "first60_append_authorized","episode_emission_authorized","live_authorized",
        "brokerage_execution_authorized","autonomous_financial_decision_authorized",
    ]
    if any(g.get(k) is not False for k in required_false):
        raise RuntimeError("STRICT_TITLE_IDENTITY_GOVERNANCE_BLOCK")
    return obj


def strict_legal_names(title:str,security_name:str)->set[str]:
    title=str(title or "").strip()
    security_name=str(security_name or "").strip()
    if not title or not security_name or len(security_name)<2:
        return set()
    allowed_tail=r"[\u4e00-\u9fffA-Za-z0-9（）()·]{0,24}?"
    suffix=r"(?:股份有限公司|有限责任公司|有限公司)"
    pat=re.compile(re.escape(security_name)+allowed_tail+suffix)
    return {m.group(0) for m in pat.finditer(title)}


def blocked_identity_groups()->dict[str,dict]:
    groups={}
    for fp in sorted(RUNS.glob("V2.8.4_PROSPECTIVE_FINALIZATION_RECEIPT_*.json")):
        obj=json.loads(fp.read_text(encoding="utf-8"))
        if obj.get("status")!="FINALIZED_WITH_BLOCKED_POSITIVE_RECORD":
            continue
        if obj.get("historical_backfill") is not False or obj.get("price_or_return_data_consumed") is not False:
            raise RuntimeError(f"FINALIZATION_PROVENANCE_BLOCK:{fp.name}")
        run_id=str(obj.get("run_id") or "")
        for r in obj.get("blocked_incomplete_positive_records") or []:
            if r.get("classification_state")!="ELIGIBLE_AI_CORE":
                continue
            if r.get("record_complete") is not False:
                continue
            if r.get("eligibility_effect")!="BLOCKED_INCOMPLETE_POSITIVE_EVIDENCE_RECORD":
                continue
            if str(r.get("issuer_legal_name") or "").strip() or str(r.get("issuer_identity_basis") or "").strip():
                raise RuntimeError(f"BLOCKED_RECORD_NOT_IDENTITY_ONLY:{r.get('announcement_id')}")
            cid=str(r.get("canonical_security_id") or "").strip()
            aid=str(r.get("announcement_id") or "").strip()
            if not cid or not aid or not run_id:
                raise RuntimeError("BLOCKED_RECORD_IDENTITY_KEYS_MISSING")
            g=groups.setdefault(cid,{"run_ids":set(),"blocked_announcement_ids":set()})
            g["run_ids"].add(run_id); g["blocked_announcement_ids"].add(aid)
    return groups


def rows_for_runs(run_ids:set[str],cid:str)->list[dict]:
    out=[]
    for run_id in sorted(run_ids):
        p=RUNS/f"V2.8.4_PROSPECTIVE_OBSERVATION_RESULTS_{run_id}.csv"
        if not p.exists():
            raise RuntimeError(f"OBSERVATION_RESULTS_MISSING:{run_id}")
        out.extend(r for r in load_csv(p) if r.get("canonical_security_id")==cid and r.get("pipeline_status")=="SUCCESS")
    return out


def derive_binding(cid:str,group:dict)->dict|None:
    rows=rows_for_runs(group["run_ids"],cid)
    names={str(r.get("security_name") or "").strip() for r in rows if str(r.get("security_name") or "").strip()}
    if len(names)!=1:
        return None
    security_name=next(iter(names))
    candidates=set()
    for r in rows:
        candidates.update(strict_legal_names(r.get("announcement_title",""),security_name))
    if len(candidates)!=1:
        return None
    legal=next(iter(candidates))
    issuer_rows=[r for r in rows if str(r.get("announcement_title") or "").strip().startswith(legal)]
    if not issuer_rows:
        return None
    issuer_rows.sort(key=lambda r:(str(r.get("disclosure_date") or ""),str(r.get("announcement_id") or "")))
    src=issuer_rows[0]
    return {
        "canonical_security_id":cid,
        "security_name":security_name,
        "issuer_legal_name":legal,
        "source_announcement_id":str(src.get("announcement_id") or ""),
        "source_adjunct_url":str(src.get("adjunct_url") or ""),
        "source_disclosure_date":str(src.get("disclosure_date") or ""),
        "identity_evidence_text":str(src.get("announcement_title") or "").strip(),
        "binding_state":"OFFICIAL_CNINFO_IDENTITY_BOUND",
        "blocked_announcement_ids":sorted(group["blocked_announcement_ids"]),
        "source_run_ids":sorted(group["run_ids"]),
    }


def planned_bindings()->list[dict]:
    amendment_guard()
    out=[]
    for cid,group in sorted(blocked_identity_groups().items()):
        b=derive_binding(cid,group)
        if b is not None:
            out.append(b)
    return out


def binding_map(rows:list[dict])->dict[str,dict]:
    by={}
    for r in rows:
        cid=str(r.get("canonical_security_id") or "").strip()
        if not cid:
            raise RuntimeError("EMPTY_CANONICAL_SECURITY_ID_IN_BINDING_LEDGER")
        if cid in by:
            raise RuntimeError(f"DUPLICATE_CANONICAL_SECURITY_BINDING:{cid}")
        by[cid]=r
    return by


def receipt_document(b:dict)->dict:
    doc={
        "schema":"AI_CORE_EVID_V2_8_12_STRICT_TITLE_IDENTITY_PREBINDING_RECEIPT_V1",
        "version":"V2.8.12",
        "status":"PENDING_AUTHORITATIVE_BINDING_COMMIT",
        "canonical_security_id":b["canonical_security_id"],
        "security_name":b["security_name"],
        "issuer_legal_name":b["issuer_legal_name"],
        "source":{
            "source_run_ids":b["source_run_ids"],
            "source_announcement_id":b["source_announcement_id"],
            "source_adjunct_url":b["source_adjunct_url"],
            "source_disclosure_date":b["source_disclosure_date"],
            "identity_evidence_text":b["identity_evidence_text"],
            "authority":"IMMUTABLE_OFFICIAL_CNINFO_OBSERVATION_METADATA"
        },
        "triggering_blocked_positive_announcement_ids":b["blocked_announcement_ids"],
        "strict_checks":{
            "exact_security_name_extension":True,
            "unique_legal_name":True,
            "issuer_authored_title_starts_with_legal_name":True,
            "fuzzy_matching_used":False,
            "AI_classification_recomputed":False
        },
        "temporal_boundary":{
            "binding_authority_time":"GitHub committed_at of the commit that first adds the binding ledger row",
            "backdating":False
        },
        "governance":{
            "price_or_return_data_consumed":False,
            "outcome_research_authorized":False,
            "fold3_access":False,
            "fold4_access":False,
            "setup_or_episode_authorized":False,
            "live_authorized":False,
            "brokerage_execution_authorized":False
        }
    }
    doc["receipt_sha256"]=acc.stable(doc)
    return doc


def write_json_idempotent(path:Path,obj:dict):
    text=json.dumps(obj,ensure_ascii=False,indent=2)+"\n"
    if path.exists():
        if path.read_text(encoding="utf-8")!=text:
            raise RuntimeError(f"IDENTITY_BINDING_RECEIPT_CONFLICT:{path.name}")
        return False
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(text,encoding="utf-8")
    return True


def bind(bindings_path:Path=BINDINGS,receipt_dir:Path=RECEIPT_DIR)->dict:
    amendment_guard()
    existing=load_csv(bindings_path)
    by=binding_map(existing)
    working=[dict(r) for r in existing]
    appended=[]
    duplicate_noops=0
    unresolved=[]
    groups=blocked_identity_groups()
    plans={b["canonical_security_id"]:b for b in planned_bindings()}
    for cid in sorted(groups):
        b=plans.get(cid)
        if b is None:
            unresolved.append(cid); continue
        if cid in by:
            current=by[cid]
            if current.get("issuer_legal_name")!=b["issuer_legal_name"] or current.get("security_name")!=b["security_name"]:
                raise RuntimeError(f"BLOCK_IDENTITY_BINDING_CONFLICT:{cid}")
            duplicate_noops+=1
            continue
        row={k:b[k] for k in BINDING_FIELDS}
        working.append(row); by[cid]=row; appended.append(b)
    if appended:
        working.sort(key=lambda r:r["canonical_security_id"])
        write_bindings(bindings_path,working)
        for b in appended:
            safe=b["canonical_security_id"].replace(":","_")
            path=receipt_dir/f"V2.8.12_STRICT_TITLE_IDENTITY_PREBINDING_{safe}.json"
            write_json_idempotent(path,receipt_document(b))
    return {
        "status":"PASS",
        "blocked_identity_groups":len(groups),
        "strict_plans":len(plans),
        "appended":len(appended),
        "duplicate_noops":duplicate_noops,
        "unresolved_fail_closed":sorted(unresolved),
        "appended_canonical_security_ids":[b["canonical_security_id"] for b in appended],
        "price_or_return_data_consumed":False
    }


def self_test():
    amendment_guard()
    tests=[]
    def ck(name,cond): tests.append({"name":name,"pass":bool(cond)})
    broker="光大证券股份有限公司关于蜂助手股份有限公司签署算力业务日常经营重大合同的核查意见"
    issuer="蜂助手股份有限公司关于签署算力业务日常经营重大合同的公告"
    ck("B01_exact_extension_extracts_target",strict_legal_names(broker,"蜂助手")=={"蜂助手股份有限公司"})
    ck("B02_issuer_title_extracts_same_target",strict_legal_names(issuer,"蜂助手")=={"蜂助手股份有限公司"})
    ck("B03_no_fuzzy_abbreviation_inference",strict_legal_names("彩讯科技股份有限公司关于人工智能业务的公告","彩讯股份")==set())
    ck("B04_unrelated_security_name_rejected",strict_legal_names(issuer,"光大证券")==set())
    plans=planned_bindings()
    bee=[b for b in plans if b["canonical_security_id"]=="SZSE:301382"]
    ck("B05_real_bee_strict_plan_unique",len(bee)==1 and bee[0]["issuer_legal_name"]=="蜂助手股份有限公司")
    ck("B06_real_bee_issuer_authored_source",len(bee)==1 and bee[0]["source_announcement_id"]=="1225585270" and bee[0]["identity_evidence_text"]==issuer)
    with tempfile.TemporaryDirectory() as td:
        td=Path(td); bp=td/"bindings.csv"; rd=td/"receipts"
        real=load_csv(BINDINGS)
        genesis=[r for r in real if r["canonical_security_id"]=="SZSE:300634"]
        write_bindings(bp,genesis)
        out=bind(bp,rd)
        rows=load_csv(bp); bee_rows=[r for r in rows if r["canonical_security_id"]=="SZSE:301382"]
        ck("B07_fixture_appends_one_binding",out["appended"]==1 and len(bee_rows)==1 and bee_rows[0]["issuer_legal_name"]=="蜂助手股份有限公司")
        ck("B08_binding_fields_complete",len(bee_rows)==1 and all(bee_rows[0].get(k) for k in BINDING_FIELDS))
        ck("B09_receipt_created_once",len(list(rd.glob("*.json")))==1)
        before_b=bp.read_bytes(); before_r={p.name:p.read_bytes() for p in rd.glob("*.json")}
        out2=bind(bp,rd); after_r={p.name:p.read_bytes() for p in rd.glob("*.json")}
        ck("B10_second_run_is_duplicate_noop",out2["appended"]==0 and out2["duplicate_noops"]==1 and bp.read_bytes()==before_b and before_r==after_r)
        conflict=[dict(r) for r in genesis]+[{**bee_rows[0],"issuer_legal_name":"错误名称股份有限公司"}]
        cp=td/"conflict.csv"; write_bindings(cp,conflict)
        blocked=False
        try: bind(cp,td/"conflict_receipts")
        except RuntimeError as e: blocked="BLOCK_IDENTITY_BINDING_CONFLICT" in str(e)
        ck("B11_existing_conflicting_binding_blocks",blocked)
    with tempfile.TemporaryDirectory() as td:
        td=Path(td); bp=td/"current.csv"; rd=td/"r"
        bp.write_bytes(BINDINGS.read_bytes())
        out=bind(bp,rd)
        ck("B12_current_production_binding_is_noop",out["appended"]==0 and out["duplicate_noops"]==1 and not list(rd.glob("*.json")))
    tree=ast.parse(Path(__file__).read_text(encoding="utf-8"))
    imported=set()
    for node in ast.walk(tree):
        if isinstance(node,ast.Import): imported.update(a.name for a in node.names)
        elif isinstance(node,ast.ImportFrom): imported.add(node.module or "")
    ck("B13_no_network_or_price_modules",not ({"playwright","requests","urllib","v283_outcome_resolver"} & imported))
    result={
        "schema":"AI_CORE_EVID_V2_8_12_STRICT_TITLE_IDENTITY_PREBINDER_SELFTEST_V1",
        "tests":tests,"passed":sum(x["pass"] for x in tests),"total":len(tests),
        "all_pass":all(x["pass"] for x in tests),"real_binding_ledger_modified":False,
        "price_or_return_data_consumed":False,"fold3_4_accessed":False
    }
    result["receipt_sha256"]=acc.stable(result)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    if not result["all_pass"]: raise SystemExit(2)


def main():
    ap=argparse.ArgumentParser(); ap.add_argument("command",choices=["self-test","bind"]); a=ap.parse_args()
    if a.command=="self-test": self_test()
    else: print(json.dumps(bind(),ensure_ascii=False,indent=2))


if __name__=="__main__":
    main()
