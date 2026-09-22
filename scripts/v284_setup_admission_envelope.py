from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

import v284_ai_core_setup_eligibility_gate as gate

CID_RE=re.compile(r"^(SSE|SZSE):\d{6}$")
SHA64=re.compile(r"^[0-9a-f]{64}$")

def stable_sha(obj)->str:
    b=json.dumps(obj,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()
    return hashlib.sha256(b).hexdigest()

def validate_strategy_receipt(x:dict):
    req=[
        "canonical_security_id","signal_date","setup_id","setup_spec_version",
        "setup_gate_status","strategy_setup_receipt_sha256","outcome_data_consumed"
    ]
    if any(k not in x for k in req):
        raise RuntimeError("STRATEGY_RECEIPT_SCHEMA_BLOCKED")
    if not CID_RE.fullmatch(str(x["canonical_security_id"])):
        raise RuntimeError("STRATEGY_RECEIPT_IDENTITY_BLOCKED")
    if x["setup_gate_status"]!="PASS":
        raise RuntimeError("STRATEGY_SETUP_NOT_PASS")
    if x["outcome_data_consumed"] is not False:
        raise RuntimeError("STRATEGY_OUTCOME_LEAKAGE_BLOCKED")
    if not str(x["setup_id"]).strip() or not str(x["setup_spec_version"]).strip():
        raise RuntimeError("STRATEGY_SETUP_ID_BLOCKED")
    if not SHA64.fullmatch(str(x["strategy_setup_receipt_sha256"])):
        raise RuntimeError("STRATEGY_RECEIPT_HASH_BLOCKED")

def validate_ai_gate(x:dict):
    if x.get("status")!="PASS_DRY_AI_CORE_CANDIDATE":
        raise RuntimeError("AI_CORE_PRECONDITION_NOT_PASS")
    if not CID_RE.fullmatch(str(x.get("canonical_security_id") or "")):
        raise RuntimeError("AI_CORE_PRECONDITION_IDENTITY_BLOCKED")
    u=x.get("u_authority") or {}
    if not SHA64.fullmatch(str(u.get("universe_snapshot_sha256") or "")):
        raise RuntimeError("AI_CORE_U_PROVENANCE_BLOCKED")
    e=x.get("effective_e_event") or {}
    if not str(e.get("source_announcement_id") or "").strip():
        raise RuntimeError("AI_CORE_E_PROVENANCE_BLOCKED")
    if not SHA64.fullmatch(str(e.get("decision_sha256") or "")):
        raise RuntimeError("AI_CORE_E_PROVENANCE_BLOCKED")
    if not str(e.get("ratification_file") or "").startswith("evidence/"):
        raise RuntimeError("AI_CORE_E_PROVENANCE_BLOCKED")

def build(strategy:dict,ai_gate:dict)->dict:
    validate_strategy_receipt(strategy)
    validate_ai_gate(ai_gate)
    if strategy["canonical_security_id"]!=ai_gate["canonical_security_id"]:
        raise RuntimeError("ADMISSION_IDENTITY_MISMATCH")
    if strategy["signal_date"]!=ai_gate["signal_date"]:
        raise RuntimeError("ADMISSION_SIGNAL_DATE_MISMATCH")
    out={
        "schema":"AI_CORE_EVID_V2_8_4_SETUP_ADMISSION_ENVELOPE_V1",
        "version":"V2.8.4",
        "status":"PASS_DRY_SETUP_ADMISSION_ENVELOPE",
        "canonical_security_id":strategy["canonical_security_id"],
        "signal_date":strategy["signal_date"],
        "setup_id":strategy["setup_id"],
        "setup_spec_version":strategy["setup_spec_version"],
        "strategy_setup_receipt_sha256":strategy["strategy_setup_receipt_sha256"],
        "ai_core_precondition":{
            "status":ai_gate["status"],
            "u_universe_snapshot_sha256":ai_gate["u_authority"]["universe_snapshot_sha256"],
            "e_source_announcement_id":ai_gate["effective_e_event"]["source_announcement_id"],
            "e_effective_signal_date":ai_gate["effective_e_event"]["effective_signal_date"],
            "e_decision_sha256":ai_gate["effective_e_event"]["decision_sha256"],
            "e_ratification_file":ai_gate["effective_e_event"]["ratification_file"],
        },
        "outcome_data_consumed":False,
        "price_or_return_data_recomputed":False,
        "first60_append_authorized":False,
        "episode_emission_authorized":False,
        "live_authorized":False,
    }
    out["envelope_sha256"]=stable_sha(out)
    return out

def self_test():
    tests=[]
    def ck(name,cond): tests.append({"name":name,"pass":bool(cond)})

    cid="SZSE:300634"
    strategy={
        "canonical_security_id":cid,
        "signal_date":"2026-09-23",
        "setup_id":"SYNTH_SETUP_001",
        "setup_spec_version":"SYNTH_V1",
        "setup_gate_status":"PASS",
        "strategy_setup_receipt_sha256":"a"*64,
        "outcome_data_consumed":False,
    }
    ai=gate.assess(cid,"2026-09-23",{cid})
    ai["u_authority"]={
        "authority_file":"evidence/v283_pit_authority/2026-09-23_PIT_DATE_AUTHORITY.json",
        "universe_snapshot_file":"evidence/v283_pit_authority/2026-09-23_PIT_UNIVERSE.csv",
        "universe_snapshot_sha256":"b"*64,
        "universe_count":5221,
    }
    env=build(strategy,ai)
    ck("A01_valid_strategy_and_real_E_pass_envelope",env["status"]=="PASS_DRY_SETUP_ADMISSION_ENVELOPE")
    ck("A02_envelope_hash_deterministic",env["envelope_sha256"]==stable_sha({k:v for k,v in env.items() if k!="envelope_sha256"}))
    ck("A03_no_first60_or_episode_authority",not env["first60_append_authorized"] and not env["episode_emission_authorized"] and not env["live_authorized"])

    bad_gate={**ai,"status":"BLOCK_E_NOT_ELIGIBLE"}
    blocked=False
    try: build(strategy,bad_gate)
    except RuntimeError as e: blocked=str(e)=="AI_CORE_PRECONDITION_NOT_PASS"
    ck("A04_nonpass_AI_gate_blocks",blocked)

    mismatch=False
    try: build({**strategy,"canonical_security_id":"SSE:600000"},ai)
    except RuntimeError as e: mismatch=str(e)=="ADMISSION_IDENTITY_MISMATCH"
    ck("A05_identity_mismatch_blocks",mismatch)

    date_mismatch=False
    try: build({**strategy,"signal_date":"2026-09-24"},ai)
    except RuntimeError as e: date_mismatch=str(e)=="ADMISSION_SIGNAL_DATE_MISMATCH"
    ck("A06_date_mismatch_blocks",date_mismatch)

    strategy_fail=False
    try: build({**strategy,"setup_gate_status":"FAIL"},ai)
    except RuntimeError as e: strategy_fail=str(e)=="STRATEGY_SETUP_NOT_PASS"
    ck("A07_strategy_not_pass_blocks",strategy_fail)

    leakage=False
    try: build({**strategy,"outcome_data_consumed":True},ai)
    except RuntimeError as e: leakage=str(e)=="STRATEGY_OUTCOME_LEAKAGE_BLOCKED"
    ck("A08_outcome_leakage_blocks",leakage)

    bad_hash=False
    try: build({**strategy,"strategy_setup_receipt_sha256":"bad"},ai)
    except RuntimeError as e: bad_hash=str(e)=="STRATEGY_RECEIPT_HASH_BLOCKED"
    ck("A09_bad_strategy_hash_blocks",bad_hash)

    bad_u=json.loads(json.dumps(ai))
    bad_u["u_authority"]["universe_snapshot_sha256"]="bad"
    u_block=False
    try: build(strategy,bad_u)
    except RuntimeError as e: u_block=str(e)=="AI_CORE_U_PROVENANCE_BLOCKED"
    ck("A10_missing_U_provenance_blocks",u_block)

    bad_e=json.loads(json.dumps(ai))
    bad_e["effective_e_event"]=None
    e_block=False
    try: build(strategy,bad_e)
    except RuntimeError as e: e_block=str(e)=="AI_CORE_E_PROVENANCE_BLOCKED"
    ck("A11_missing_E_provenance_blocks",e_block)

    result={
        "schema":"AI_CORE_EVID_V2_8_4_SETUP_ADMISSION_ENVELOPE_SELFTEST_V1",
        "tests":tests,
        "passed":sum(x["pass"] for x in tests),
        "total":len(tests),
        "all_pass":all(x["pass"] for x in tests),
        "real_E_event_integration_tested":True,
        "strategy_setup_is_synthetic_interface_fixture_only":True,
        "first60_append_authorized":False,
        "episode_emission_authorized":False,
        "live_authorized":False,
    }
    print(json.dumps(result,ensure_ascii=False,indent=2))
    if not result["all_pass"]:
        raise SystemExit(2)

def main():
    ap=argparse.ArgumentParser()
    sub=ap.add_subparsers(dest="cmd",required=True)
    sub.add_parser("self-test")
    b=sub.add_parser("build")
    b.add_argument("--strategy-receipt",required=True)
    b.add_argument("--ai-core-gate-receipt",required=True)
    a=ap.parse_args()
    if a.cmd=="self-test":
        self_test()
    else:
        strategy=json.loads(Path(a.strategy_receipt).read_text(encoding="utf-8"))
        ai=json.loads(Path(a.ai_core_gate_receipt).read_text(encoding="utf-8"))
        print(json.dumps(build(strategy,ai),ensure_ascii=False,indent=2))

if __name__=="__main__":
    main()
