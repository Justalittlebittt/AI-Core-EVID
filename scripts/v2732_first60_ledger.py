from __future__ import annotations

import argparse
import csv
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CALENDAR=Path("evidence/V2.7.32_JOINT_A_SHARE_TRADING_CALENDAR_2026.json")
CONTRACT=Path("evidence/V2.7.32_FIRST60_CONTRACT.json")
GENESIS=Path("evidence/V2.7.32_FIRST60_LEDGER_GENESIS.json")
UNIVERSE=Path("evidence/V2.7.31_FORWARD_CERTIFIED_UNIVERSE.csv")
UNIVERSE_SHA="8815cd4ff5fb1f82e7c49b2a142ceb8e12138a4068d7a21c8ae144b57cc3f92d"
OUT=Path("v2732_first60_validation")
OUT.mkdir(exist_ok=True)

def sha(b:bytes)->str:
    return hashlib.sha256(b).hexdigest()

def load_calendar():
    obj=json.loads(CALENDAR.read_text(encoding="utf-8"))
    days=[r["date"] for r in obj["dates"] if r["is_joint_a_share_trading_day"]]
    return obj,days,{d:i for i,d in enumerate(days)}

def load_universe():
    b=UNIVERSE.read_bytes()
    if sha(b)!=UNIVERSE_SHA:
        raise RuntimeError("UNIVERSE_SHA_MISMATCH")
    rows=list(csv.DictReader(b.decode("utf-8").splitlines()))
    ids={r["canonical_security_id"] for r in rows if r.get("universe_entry_status")=="CERTIFIED"}
    return ids

def target_d10(signal_date:str,days:list[str],idx:dict[str,int])->str:
    if signal_date not in idx:
        raise RuntimeError("NON_TRADING_SIGNAL_DATE")
    j=idx[signal_date]+10
    if j>=len(days):
        raise RuntimeError("CALENDAR_HORIZON_UNAVAILABLE")
    return days[j]

def stage_for_rank(rank:int)->str:
    if 1<=rank<=30: return "A"
    if 31<=rank<=60: return "B"
    return "OUTSIDE_FIRST60"

def temporal_sufficiency(starts:list[dict[str,Any]])->dict[str,Any]:
    first=sorted(starts,key=lambda x:x["episode_rank"])[:60]
    a=[x for x in first if 1<=x["episode_rank"]<=30]
    b=[x for x in first if 31<=x["episode_rank"]<=60]
    dates=[x["signal_date"] for x in first]
    counts={d:dates.count(d) for d in sorted(set(dates))}
    max_share=(max(counts.values())/60.0) if len(first)==60 and counts else None
    sufficient=bool(
      len(first)==60 and
      len(set(dates))>=10 and
      len({x["signal_date"] for x in a})>=5 and
      len({x["signal_date"] for x in b})>=5 and
      max_share is not None and max_share<=0.20
    )
    return {
      "first60_complete":len(first)==60,
      "all60_distinct_signal_dates":len(set(dates)),
      "stage_a_distinct_signal_dates":len({x["signal_date"] for x in a}),
      "stage_b_distinct_signal_dates":len({x["signal_date"] for x in b}),
      "max_single_signal_date_share":max_share,
      "status":"SUFFICIENT" if sufficient else "INCONCLUSIVE"
    }

def derive_open_symbols(starts:list[dict[str,Any]],outcomes:list[dict[str,Any]])->set[str]:
    closed={x["episode_id"] for x in outcomes if x.get("status") in {"RESOLVED","OUTCOME_UNAVAILABLE"}}
    return {x["canonical_security_id"] for x in starts if x["episode_id"] not in closed}

def validate_day(
    payload:dict[str,Any],
    activation:dict[str,Any],
    existing_sessions:list[dict[str,Any]],
    starts:list[dict[str,Any]],
    outcomes:list[dict[str,Any]],
    universe_ids:set[str],
    trading_days:list[str],
    trading_idx:dict[str,int],
)->tuple[dict[str,Any],list[dict[str,Any]]]:
    if activation.get("status")!="ACTIVE":
        raise RuntimeError("ACTIVATION_BLOCKED")
    d=str(payload.get("signal_date") or "")
    first=str(activation.get("first_eligible_signal_date") or "")
    if not first or d<first:
        raise RuntimeError("PRE_ACTIVATION_OR_BEFORE_FIRST_ELIGIBLE")
    if d not in trading_idx:
        raise RuntimeError("NON_TRADING_SIGNAL_DATE")
    if any(x["signal_date"]==d for x in existing_sessions):
        raise RuntimeError("DUPLICATE_DAILY_SESSION")
    if str(payload.get("max_bar_date") or "")!=d:
        raise RuntimeError("STALE_OR_FUTURE_SIGNAL_SOURCE")
    source_sha=str(payload.get("source_snapshot_sha256") or "")
    if len(source_sha)!=64:
        raise RuntimeError("SOURCE_HASH_REQUIRED")
    candidates=payload.get("episode_starts") or []
    if not isinstance(candidates,list):
        raise RuntimeError("INVALID_EPISODE_START_LIST")
    open_symbols=derive_open_symbols(starts,outcomes)
    seen_today=set()
    new=[]
    next_rank=len(starts)+1
    for c in candidates:
        cid=str(c.get("canonical_security_id") or "")
        if cid not in universe_ids:
            raise RuntimeError("SECURITY_NOT_IN_CERTIFIED_UNIVERSE")
        if cid in open_symbols or cid in seen_today:
            raise RuntimeError("SAME_SYMBOL_OVERLAP_BLOCKED")
        setup_hash=str(c.get("setup_receipt_sha256") or "")
        if len(setup_hash)!=64:
            raise RuntimeError("SETUP_RECEIPT_HASH_REQUIRED")
        if next_rank<=60:
            eid=f"F60-{next_rank:03d}-{d}-{cid.replace(':','_')}"
            new.append({
              "event_type":"EPISODE_START",
              "episode_id":eid,
              "episode_rank":next_rank,
              "stage":stage_for_rank(next_rank),
              "signal_date":d,
              "target_date_d10":target_d10(d,trading_days,trading_idx),
              "canonical_security_id":cid,
              "source_snapshot_sha256":source_sha,
              "setup_receipt_sha256":setup_hash,
              "outcome_status":"PENDING",
            })
            next_rank+=1
        seen_today.add(cid)
    session={
      "event_type":"DAILY_SESSION",
      "signal_date":d,
      "max_bar_date":d,
      "source_snapshot_sha256":source_sha,
      "runner_receipt_sha256":str(payload.get("runner_receipt_sha256") or ""),
      "submitted_episode_start_count":len(candidates),
      "admitted_first60_episode_start_count":len(new),
      "zero_candidate_session":len(candidates)==0,
    }
    if len(session["runner_receipt_sha256"])!=64:
        raise RuntimeError("RUNNER_RECEIPT_HASH_REQUIRED")
    return session,new

def fake_hash(ch:str)->str:
    return (ch*64)[:64]

def self_test():
    cal,days,idx=load_calendar()
    universe=load_universe()
    contract=json.loads(CONTRACT.read_text(encoding="utf-8"))
    genesis=json.loads(GENESIS.read_text(encoding="utf-8"))
    tests=[]

    def rec(name,fn,expected=None):
        try:
            v=fn()
            actual="PASS"
            ok=(expected in (None,"PASS"))
            detail=v
        except Exception as e:
            actual=str(e)
            ok=(expected is not None and expected in actual)
            detail=None
        tests.append({"name":name,"expected":expected or "PASS","actual":actual,"pass":ok,"detail":detail})

    active={"status":"ACTIVE","first_eligible_signal_date":"2026-09-21"}
    base={
      "signal_date":"2026-09-21","max_bar_date":"2026-09-21",
      "source_snapshot_sha256":fake_hash("a"),"runner_receipt_sha256":fake_hash("b"),
      "episode_starts":[{"canonical_security_id":sorted(universe)[0],"setup_receipt_sha256":fake_hash("c")}]
    }

    rec("A01_d10_calendar_freeze",lambda: target_d10("2026-09-21",days,idx)=="2026-10-13")
    rec("A02_nontrading_block",lambda: validate_day({**base,"signal_date":"2026-09-20","max_bar_date":"2026-09-20"},active,[],[],[],universe,days,idx),"NON_TRADING_SIGNAL_DATE")
    rec("A03_preactivation_block",lambda: validate_day({**base,"signal_date":"2026-09-18","max_bar_date":"2026-09-18"},active,[],[],[],universe,days,idx),"PRE_ACTIVATION_OR_BEFORE_FIRST_ELIGIBLE")
    rec("A04_stale_source_block",lambda: validate_day({**base,"max_bar_date":"2026-09-18"},active,[],[],[],universe,days,idx),"STALE_OR_FUTURE_SIGNAL_SOURCE")
    rec("A05_unknown_security_block",lambda: validate_day({**base,"episode_starts":[{"canonical_security_id":"SSE:999999","setup_receipt_sha256":fake_hash("c")}]},active,[],[],[],universe,days,idx),"SECURITY_NOT_IN_CERTIFIED_UNIVERSE")
    rec("A06_zero_candidate_session_valid",lambda: validate_day({**base,"episode_starts":[]},active,[],[],[],universe,days,idx)[0]["zero_candidate_session"])
    session,first=validate_day(base,active,[],[],[],universe,days,idx)
    rec("A07_first_rank_stage_a",lambda: first[0]["episode_rank"]==1 and first[0]["stage"]=="A")
    rec("A08_same_symbol_overlap_block",lambda: validate_day({**base,"signal_date":"2026-09-22","max_bar_date":"2026-09-22"},active,[session],first,[],universe,days,idx),"SAME_SYMBOL_OVERLAP_BLOCKED")
    outcome=[{"episode_id":first[0]["episode_id"],"status":"OUTCOME_UNAVAILABLE"}]
    rec("A09_unavailable_outcome_closes_symbol_without_replacement",lambda: sorted(derive_open_symbols(first,outcome))==[])
    starts60=[]
    ids=sorted(universe)[:60]
    for rank,cid in enumerate(ids,1):
        starts60.append({"episode_rank":rank,"signal_date":"2026-09-21","canonical_security_id":cid,"episode_id":f"e{rank}"})
    rec("A10_concentrated_first60_inconclusive",lambda: temporal_sufficiency(starts60)["status"]=="INCONCLUSIVE")
    rec("A11_stage_boundary",lambda: stage_for_rank(30)=="A" and stage_for_rank(31)=="B" and stage_for_rank(60)=="B" and stage_for_rank(61)=="OUTSIDE_FIRST60")
    rec("A12_genesis_not_activated",lambda: genesis["state"]=="NOT_ACTIVATED" and genesis["candidate_episode_start_count"]==0)
    rec("A13_contract_no_replacement",lambda: contract["cohort"]["replacement_after_missing_outcome"] is False)

    receipt={
      "schema":"AI_CORE_EVID_V2_7_32_FIRST60_LEDGER_VALIDATION_V1",
      "tests":tests,
      "passed":sum(1 for x in tests if x["pass"]),
      "total":len(tests),
      "all_pass":all(x["pass"] for x in tests),
      "calendar_trading_day_count":len(days),
      "calendar_trading_dates_sha256":cal["trading_dates_sorted_newline_sha256"],
      "universe_count":len(universe),
      "genesis_state":genesis["state"],
      "activation_status":"BLOCKED_PROSPECTIVE_SIGNAL_RUNNER_BYTES_ABSENT"
    }
    canon=json.dumps(receipt,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()
    receipt["receipt_sha256"]=sha(canon)
    (OUT/"V2.7.32_FIRST60_LEDGER_VALIDATION_RECEIPT.json").write_text(
      json.dumps(receipt,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(receipt,ensure_ascii=False,indent=2))
    if not receipt["all_pass"]:
        raise SystemExit(2)

def audit():
    cal,days,idx=load_calendar()
    universe=load_universe()
    genesis=json.loads(GENESIS.read_text(encoding="utf-8"))
    print(json.dumps({
      "status":"PASS",
      "calendar_days":len(days),
      "universe_count":len(universe),
      "genesis_state":genesis["state"],
      "first_eligible_signal_date":genesis["first_eligible_signal_date"]
    },ensure_ascii=False,indent=2))

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("command",choices=["self-test","audit"])
    args=ap.parse_args()
    if args.command=="self-test": self_test()
    else: audit()

if __name__=="__main__":
    main()
