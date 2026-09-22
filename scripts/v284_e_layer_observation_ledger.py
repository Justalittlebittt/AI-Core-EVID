from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

FIELDS=[
    "announcement_id","canonical_security_id","adjunct_url","object_sha256",
    "page_text_sha256","decision_sha256","diagnostic_or_prospective_mode",
    "classification_state","first_observation_commit_sha","first_observed_at_utc"
]

def load_rows(path:Path)->list[dict]:
    if not path.exists():
        return []
    return list(csv.DictReader(path.read_text(encoding="utf-8").splitlines()))

def validate_event(e:dict):
    for k in FIELDS:
        if k not in e:
            raise RuntimeError(f"EVENT_SCHEMA_BLOCKED:{k}")
    if not e["announcement_id"] or not e["canonical_security_id"] or not e["object_sha256"]:
        raise RuntimeError("EVENT_IDENTITY_BLOCKED")
    if e["diagnostic_or_prospective_mode"] not in {"DIAGNOSTIC","PROSPECTIVE"}:
        raise RuntimeError("EVENT_MODE_BLOCKED")

def assess(existing:list[dict],event:dict)->str:
    validate_event(event)
    hits=[r for r in existing if r["announcement_id"]==event["announcement_id"]]
    if not hits:
        return "APPEND_ALLOWED"
    if len(hits)!=1:
        raise RuntimeError("LEDGER_DUPLICATE_PRIMARY_KEY_BLOCKED")
    r=hits[0]
    if r["canonical_security_id"]!=event["canonical_security_id"]:
        return "BLOCKED_IDENTITY_CONFLICT"
    if r["adjunct_url"]!=event["adjunct_url"] or r["object_sha256"]!=event["object_sha256"]:
        return "BLOCKED_ANNOUNCEMENT_OBJECT_CONFLICT"
    return "NO_ACTION_DUPLICATE"

def append(path:Path,event:dict)->str:
    rows=load_rows(path)
    state=assess(rows,event)
    if state!="APPEND_ALLOWED":
        return state
    path.parent.mkdir(parents=True,exist_ok=True)
    new=not path.exists()
    with path.open("a",encoding="utf-8",newline="") as f:
        w=csv.DictWriter(f,fieldnames=FIELDS,lineterminator="\n")
        if new: w.writeheader()
        w.writerow({k:event[k] for k in FIELDS})
    return "APPENDED"

def self_test():
    base={
        "announcement_id":"123",
        "canonical_security_id":"SSE:600001",
        "adjunct_url":"finalpage/2026-09-01/123.PDF",
        "object_sha256":"a"*64,
        "page_text_sha256":"b"*64,
        "decision_sha256":"c"*64,
        "diagnostic_or_prospective_mode":"DIAGNOSTIC",
        "classification_state":"NOT_ESTABLISHED",
        "first_observation_commit_sha":"d"*40,
        "first_observed_at_utc":"2026-09-22T00:00:00Z",
    }
    existing=[]
    tests=[]
    def ck(n,v): tests.append({"name":n,"pass":bool(v)})
    ck("L01_new_append_allowed",assess(existing,base)=="APPEND_ALLOWED")
    existing=[base]
    ck("L02_exact_duplicate_no_action",assess(existing,dict(base))=="NO_ACTION_DUPLICATE")
    ck("L03_identity_conflict_blocks",assess(existing,{**base,"canonical_security_id":"SSE:600002"})=="BLOCKED_IDENTITY_CONFLICT")
    ck("L04_object_conflict_blocks",assess(existing,{**base,"object_sha256":"e"*64})=="BLOCKED_ANNOUNCEMENT_OBJECT_CONFLICT")
    dup_block=False
    try: assess([base,base],base)
    except RuntimeError: dup_block=True
    ck("L05_existing_duplicate_primary_key_blocks",dup_block)
    mode_block=False
    try: assess([],{**base,"diagnostic_or_prospective_mode":"LIVE"})
    except RuntimeError: mode_block=True
    ck("L06_mode_fail_closed",mode_block)
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        p=Path(td)/"ledger.csv"
        ck("L07_append_writes",append(p,base)=="APPENDED" and len(load_rows(p))==1)
        ck("L08_duplicate_does_not_rewrite",append(p,base)=="NO_ACTION_DUPLICATE" and len(load_rows(p))==1)
    result={"schema":"AI_CORE_EVID_V2_8_4_E_LAYER_LEDGER_SELFTEST_V1","tests":tests,
            "passed":sum(x["pass"] for x in tests),"total":len(tests),"all_pass":all(x["pass"] for x in tests)}
    print(json.dumps(result,ensure_ascii=False,indent=2))
    if not result["all_pass"]: raise SystemExit(2)

def main():
    ap=argparse.ArgumentParser()
    sub=ap.add_subparsers(dest="cmd",required=True)
    sub.add_parser("self-test")
    a=sub.add_parser("append")
    a.add_argument("--ledger",required=True)
    a.add_argument("--event-json",required=True)
    args=ap.parse_args()
    if args.cmd=="self-test": self_test()
    else:
        event=json.loads(Path(args.event_json).read_text(encoding="utf-8"))
        state=append(Path(args.ledger),event)
        print(json.dumps({"status":state},ensure_ascii=False))

if __name__=="__main__":
    main()
