#!/usr/bin/env python3
"""Prospective 122-issuer evaluation: future observations only; never a BUY signal."""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import re
from datetime import date, datetime, time, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "research/V2.9_GROWTH_122_FORWARD_EVALUATION_PROTOCOL.json"
SHAPE = "AI_CORE_EVID_V29_FIXED_GROWTH_COHORT_FORWARD_EXPERIMENT_V1"
OUTCOME = "V29_FORWARD_COHORT_OBSERVED_OUTCOMES_V1"
SHA = re.compile(r"^[0-9a-f]{64}$")
CN = ZoneInfo("Asia/Shanghai")


def load_registered(path=PROTOCOL, root=ROOT):
    b = Path(path).read_bytes()
    spec = json.loads(b)
    if (spec["schema"] != SHAPE or
        spec["experiment_id"] != "V29_122_GROWTH_COHORT_PROSPECTIVE_20261030" or
        spec["research_freeze"] != "2026-10-30" or
        spec["baseline"]["id"] != "H00300.CSI" or
        spec["sample"]["size"] != 122 or
        spec["costs"]["round_trip_fraction"] != 0.003 or
        spec["live_buy_eligibility"] != "NOT_AUTHORIZED"):
        raise ValueError("REGISTERED_EXPERIMENT_CHANGED")
    text = (Path(root) / spec["sample"]["manifest"]).read_text(encoding="utf-8")
    parts = text.split("~~~")
    if len(parts) < 3:
        parts = text.split(chr(96)*3)
    ids = parts[1].strip().splitlines()
    if len(ids) != 122 or len(set(ids)) != 122:
        raise ValueError("INVALID_COHORT_CARDINALITY")
    if not all(re.fullmatch(r"(SSE|SZSE):[0-9]{6}", x) for x in ids):
        raise ValueError("INVALID_COHORT_IDENTITY")
    if hashlib.sha256(("\n".join(ids)+"\n").encode()).hexdigest() != spec["sample"]["sha256_linefeed"]:
        raise ValueError("FROZEN_COHORT_HASH_MISMATCH")
    return spec, ids, hashlib.sha256(b).hexdigest()


def readiness(path=PROTOCOL, root=ROOT):
    s, ids, digest = load_registered(path, root)
    return {"experiment_id": s["experiment_id"], "protocol_sha256": digest,
            "cohort_count": len(ids), "status": "FROZEN_NO_FUTURE_OUTCOME_ADMITTED",
            "strategy_evidence_strength": "INSUFFICIENT",
            "live_buy_eligibility": "NOT_AUTHORIZED"}


def positive(name, x):
    if isinstance(x, bool) or not isinstance(x, (float, int)) or not math.isfinite(x) or x <= 0:
        raise ValueError("INVALID_FINITE_POSITIVE_VALUE:" + name)
    return float(x)


def evaluate(outcome, path=PROTOCOL, root=ROOT, now=None):
    s, ids, digest = load_registered(path, root)
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("NOW_MUST_BE_TZ_AWARE")
    if (outcome.get("schema") != OUTCOME or outcome.get("experiment_id") != s["experiment_id"] or
        outcome.get("protocol_sha256") != digest):
        raise ValueError("FUTURE_OUTCOME_IDENTITY_MISMATCH")
    sessions = outcome.get("verified_exchange_sessions")
    if not isinstance(sessions, list) or len(sessions) != 20:
        raise ValueError("REQUIRES_EXACT_20_OFFICIAL_TRADING_SESSIONS")
    days = [date.fromisoformat(x) for x in sessions]
    if (days != sorted(set(days)) or days[0] <= date(2026,10,30) or
        any(x.weekday() > 4 for x in days)):
        raise ValueError("FUTURE_CALENDAR_INVALID")
    if (not outcome.get("calendar_source") or not SHA.fullmatch(outcome.get("calendar_sha256","")) or
        not SHA.fullmatch(outcome.get("raw_outcome_sources_sha256",""))):
        raise ValueError("CALENDAR_OR_SOURCE_NOT_BOUND")
    captured = datetime.fromisoformat(outcome["capture_timestamp"])
    exit_close = datetime.combine(days[-1],time(15,15),tzinfo=CN)
    if captured.tzinfo is None or captured > now or captured.astimezone(CN) < exit_close or now.astimezone(CN) < exit_close:
        raise ValueError("FUTURE_OUTCOME_NOT_YET_OBSERVABLE")
    benchmark = outcome.get("benchmark",{})
    if benchmark.get("security_id") != "H00300.CSI" or not SHA.fullmatch(benchmark.get("source_sha256","")):
        raise ValueError("INVALID_TOTAL_RETURN_BENCHMARK")
    br = positive("benchmark_exit", benchmark["exit_total_return_index_close"]) / positive("benchmark_entry", benchmark["entry_total_return_index_close"]) - 1
    rows = outcome.get("securities")
    if not isinstance(rows,list):
        raise ValueError("OUTCOME_SECURITIES_MISSING")
    valid_ids=set(ids)
    seen=set()
    ret=[]
    incomplete=0
    for r in rows:
        sid=r.get("canonical_security_id")
        if sid not in valid_ids or sid in seen:
            raise ValueError("DUPLICATE_OR_OUT_OF_UNIVERSE")
        seen.add(sid)
        if (r.get("entry_tradeable_at_reference_close") is not True or
            r.get("exit_tradeable_at_reference_close") is not True or
            r.get("corporate_actions_and_dividends_adjusted") is not True or
            not SHA.fullmatch(r.get("raw_quote_sha256","")) or
            r.get("adjusted_entry_close") is None or r.get("adjusted_exit_close") is None):
            incomplete+=1
            continue
        ret.append(positive(sid+"_exit",r["adjusted_exit_close"])/positive(sid+"_entry",r["adjusted_entry_close"])-1)
    complete=len(seen)==122 and len(ret)==122
    base={"experiment_id":s["experiment_id"],"protocol_sha256":digest,
          "frozen_security_count":122,"observed_count":len(seen),
          "computable_count":len(ret),"unavailable_count":122-len(ret),
          "entry_session":sessions[0],"exit_session":sessions[-1],
          "benchmark_total_return":br,"cost_round_trip":0.003,
          "market_source_and_calendar_not_independently_certified":True,
          "one_market_episode_not_generalizable_alpha":True,
          "strategy_validated":False,"live_buy_eligibility":"NOT_AUTHORIZED"}
    if not complete:
        return {**base,"status":"INCOMPLETE_NEVER_DROP_NAMES","mean_net_excess":None}
    net=[x-0.003 for x in ret]
    excess=[x-br for x in net]
    return {**base,"status":"ONE_EPISODE_DESCRIPTIVE_NOT_BUY_EVIDENCE",
            "mean_gross":sum(ret)/122,"mean_net":sum(net)/122,
            "mean_net_excess":sum(excess)/122,
            "outperforming_name_fraction":sum(x>0 for x in excess)/122}


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--outcomes",type=Path)
    args=p.parse_args()
    result=evaluate(json.loads(args.outcomes.read_text(encoding="utf-8"))) if args.outcomes else readiness()
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=="__main__":
    main()
