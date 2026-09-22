from __future__ import annotations

import argparse
import csv
import json
import re
from datetime import date
from pathlib import Path

LEDGER=Path("evidence/V2.8.4_E_LAYER_EFFECTIVE_ELIGIBILITY_EVENTS.csv")
CALENDAR=Path("evidence/V2.7.32_JOINT_A_SHARE_TRADING_CALENDAR_2026.json")
REQUIRED=[
    "canonical_security_id","issuer_legal_name","source_announcement_id",
    "source_object_sha256","decision_sha256","evidence_observation_commit_sha",
    "issuer_identity_binding_commit_sha","eligibility_completeness_time_utc",
    "effective_signal_date","classification_state","ratification_file"
]

def load_rows(path:Path=LEDGER)->list[dict]:
    if not path.exists():
        return []
    return list(csv.DictReader(path.read_text(encoding="utf-8").splitlines()))

def joint_trading_dates(path:Path=CALENDAR)->set[str]:
    obj=json.loads(path.read_text(encoding="utf-8"))
    return {x["date"] for x in obj["dates"] if x["is_joint_a_share_trading_day"]}

def validate_row(r:dict):
    for k in REQUIRED:
        if not str(r.get(k) or "").strip():
            raise RuntimeError(f"E_EVENT_SCHEMA_BLOCKED:{k}")
    if not re.fullmatch(r"(SSE|SZSE):\d{6}",r["canonical_security_id"]):
        raise RuntimeError("E_EVENT_SECURITY_ID_BLOCKED")
    if r["classification_state"]!="ELIGIBLE_AI_CORE":
        raise RuntimeError("E_EVENT_NONPOSITIVE_BLOCKED")
    try:
        date.fromisoformat(r["effective_signal_date"])
    except ValueError as e:
        raise RuntimeError("E_EVENT_EFFECTIVE_DATE_BLOCKED") from e
    if not re.fullmatch(r"[0-9a-f]{64}",r["source_object_sha256"]):
        raise RuntimeError("E_EVENT_OBJECT_SHA_BLOCKED")
    if not re.fullmatch(r"[0-9a-f]{64}",r["decision_sha256"]):
        raise RuntimeError("E_EVENT_DECISION_SHA_BLOCKED")
    if not re.fullmatch(r"[0-9a-f]{40}",r["evidence_observation_commit_sha"]):
        raise RuntimeError("E_EVENT_OBSERVATION_COMMIT_BLOCKED")
    if not re.fullmatch(r"[0-9a-f]{40}",r["issuer_identity_binding_commit_sha"]):
        raise RuntimeError("E_EVENT_IDENTITY_COMMIT_BLOCKED")
    if not r["ratification_file"].startswith("evidence/"):
        raise RuntimeError("E_EVENT_RATIFICATION_PATH_BLOCKED")

def validate_ledger(rows:list[dict]):
    seen={}
    for r in rows:
        validate_row(r)
        key=(r["canonical_security_id"],r["source_announcement_id"])
        if key in seen:
            if seen[key]!=r:
                raise RuntimeError("E_EVENT_CONFLICT_BLOCKED")
            raise RuntimeError("E_EVENT_DUPLICATE_PRIMARY_KEY_BLOCKED")
        seen[key]=dict(r)

def resolve(canonical_security_id:str,signal_date:str,rows:list[dict]|None=None)->dict:
    rows=load_rows() if rows is None else rows
    validate_ledger(rows)
    if not re.fullmatch(r"(SSE|SZSE):\d{6}",canonical_security_id):
        raise RuntimeError("E_STATE_SECURITY_ID_BLOCKED")
    try:
        date.fromisoformat(signal_date)
    except ValueError as e:
        raise RuntimeError("E_STATE_SIGNAL_DATE_BLOCKED") from e
    if signal_date not in joint_trading_dates():
        raise RuntimeError("E_STATE_SIGNAL_DATE_NOT_JOINT_TRADING_DAY")
    hits=[
        r for r in rows
        if r["canonical_security_id"]==canonical_security_id
        and r["effective_signal_date"]<=signal_date
    ]
    if not hits:
        return {
            "canonical_security_id":canonical_security_id,
            "signal_date":signal_date,
            "classification_state":"NOT_ESTABLISHED",
            "effective_event":None,
            "price_or_return_data_consumed":False,
        }
    first=sorted(hits,key=lambda r:(r["effective_signal_date"],r["source_announcement_id"]))[0]
    return {
        "canonical_security_id":canonical_security_id,
        "signal_date":signal_date,
        "classification_state":"ELIGIBLE_AI_CORE",
        "effective_event":{
            "source_announcement_id":first["source_announcement_id"],
            "effective_signal_date":first["effective_signal_date"],
            "decision_sha256":first["decision_sha256"],
            "ratification_file":first["ratification_file"],
        },
        "price_or_return_data_consumed":False,
    }

def self_test():
    base={
        "canonical_security_id":"SZSE:300634",
        "issuer_legal_name":"彩讯科技股份有限公司",
        "source_announcement_id":"1225573666",
        "source_object_sha256":"a"*64,
        "decision_sha256":"b"*64,
        "evidence_observation_commit_sha":"c"*40,
        "issuer_identity_binding_commit_sha":"d"*40,
        "eligibility_completeness_time_utc":"2026-09-22T06:47:46Z",
        "effective_signal_date":"2026-09-23",
        "classification_state":"ELIGIBLE_AI_CORE",
        "ratification_file":"evidence/x.json",
    }
    tests=[]
    def ck(name,cond): tests.append({"name":name,"pass":bool(cond)})

    validate_ledger([base])
    ck("S01_before_effective_not_established",resolve("SZSE:300634","2026-09-22",[base])["classification_state"]=="NOT_ESTABLISHED")
    ck("S02_on_effective_is_eligible",resolve("SZSE:300634","2026-09-23",[base])["classification_state"]=="ELIGIBLE_AI_CORE")
    ck("S03_later_date_stays_eligible",resolve("SZSE:300634","2026-09-24",[base])["classification_state"]=="ELIGIBLE_AI_CORE")
    ck("S04_unknown_security_defaults_not_established",resolve("SSE:600000","2026-09-23",[base])["classification_state"]=="NOT_ESTABLISHED")
    ck("S05_first_event_provenance_preserved",resolve("SZSE:300634","2026-09-23",[base])["effective_event"]["source_announcement_id"]=="1225573666")

    nonpositive=False
    try: validate_ledger([{**base,"classification_state":"NOT_ESTABLISHED"}])
    except RuntimeError: nonpositive=True
    ck("S06_nonpositive_event_blocked",nonpositive)

    conflict=False
    try: validate_ledger([base,{**base,"decision_sha256":"e"*64}])
    except RuntimeError: conflict=True
    ck("S07_duplicate_conflict_blocked",conflict)

    weekend=False
    try: resolve("SZSE:300634","2026-09-26",[base])
    except RuntimeError: weekend=True
    ck("S08_nontrading_signal_date_blocked",weekend)

    bad_id=False
    try: resolve("300634","2026-09-23",[base])
    except RuntimeError: bad_id=True
    ck("S09_noncanonical_security_blocked",bad_id)

    later={**base,"source_announcement_id":"1225999999","decision_sha256":"f"*64,"effective_signal_date":"2026-09-24"}
    ck("S10_earliest_positive_event_is_authority",
       resolve("SZSE:300634","2026-09-24",[base,later])["effective_event"]["source_announcement_id"]=="1225573666")

    result={
        "schema":"AI_CORE_EVID_V2_8_4_EFFECTIVE_E_STATE_RESOLVER_SELFTEST_V1",
        "tests":tests,
        "passed":sum(x["pass"] for x in tests),
        "total":len(tests),
        "all_pass":all(x["pass"] for x in tests),
    }
    print(json.dumps(result,ensure_ascii=False,indent=2))
    if not result["all_pass"]:
        raise SystemExit(2)

def main():
    ap=argparse.ArgumentParser()
    sub=ap.add_subparsers(dest="cmd",required=True)
    sub.add_parser("self-test")
    r=sub.add_parser("resolve")
    r.add_argument("--canonical-security-id",required=True)
    r.add_argument("--signal-date",required=True)
    a=ap.parse_args()
    if a.cmd=="self-test":
        self_test()
    else:
        print(json.dumps(resolve(a.canonical_security_id,a.signal_date),ensure_ascii=False,indent=2))

if __name__=="__main__":
    main()
