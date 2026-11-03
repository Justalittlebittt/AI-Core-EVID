#!/usr/bin/env python3
"""Registered 8-vs-122 post-maturity read-only contrast from ONE parent outcome.
No price fetch, extra scheduler, strategy promotion or broker order path.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from v29_growth_forward_cohort import ROOT, evaluate as evaluate_parent, load_registered

PILOT=ROOT/"research/V2.9_EIGHT_NAME_LOT_AWARE_PROSPECTIVE_PILOT_PREOUTCOME_20261102.json"
SCHEMA="V29_FROZEN_EIGHT_VS_122_POST_MATURITY_RESEARCH_RESULT_V1"

def evaluate(outcome, now=None, root=ROOT):
    root=Path(root)
    blob=(root/PILOT.relative_to(ROOT)).read_bytes()
    # Bind to the pre-close Git blob, rather than copying eight names a second time.
    git_blob_sha=hashlib.sha1(b"blob "+str(len(blob)).encode()+b"\\0"+blob).hexdigest()
    if git_blob_sha!="f33e9c5f68c2202c994fece278322413e18059b1":
        raise ValueError("FROZEN_EIGHT_PREOUTCOME_BLOB_CHANGED")
    pilot=json.loads(blob)
    if (pilot.get("schema")!="V29_PREOUTCOME_EIGHT_NAME_LOT_FEASIBLE_RESEARCH_PILOT_V1"
            or pilot.get("experiment_id")!="V29_20261102_CAPITAL_AWARE_EIGHT_NAME_EXPLORATORY_RESEARCH"
            or pilot.get("live_buy_eligibility")!="NOT_AUTHORIZED"
            or pilot["future_one_episode_observation"]["same_round_trip_cost_fraction"]!=.003):
        raise ValueError("FROZEN_EIGHT_PILOT_CHANGED")
    selected=pilot["pre_outcome_rule"]["selected_ids_in_rank_order"]
    parent_spec,original_ids,_=load_registered(root=root)
    if (len(selected)!=8 or len(set(selected))!=8
            or not set(selected).issubset(original_ids)
            or pilot["pre_outcome_rule"]["required_selected_count"]!=8
            or pilot["future_one_episode_observation"]["parent_experiment_id"]!=parent_spec["experiment_id"]):
        raise ValueError("FROZEN_EIGHT_MEMBERSHIP_OR_PARENT_CHANGED")
    # Parent's existing evaluator owns no-lookahead, exact session, source,
    # corporate action proxy, all-122 coverage and official H00300 validation.
    parent=evaluate_parent(outcome,root=root,now=now)
    result={
        "schema":SCHEMA,"experiment_id":pilot["experiment_id"],
        "parent_experiment_id":parent["experiment_id"],
        "source_parent_protocol_sha256":parent["protocol_sha256"],
        "source_parent_raw_outcome_sha256":outcome["raw_outcome_sources_sha256"],
        "entry_session":parent["entry_session"],"exit_session":parent["exit_session"],
        "selected_eight_ids_in_frozen_rank_order":selected,
        "selected_count":8,"parent_count":122,"cost_round_trip":.003,
        "parent_outcome_status":parent["status"],
        "research_only":True,"not_independent_repeated_alpha":True,
        "not_lot_weighted_cash_portfolio":True,
        "live_buy_eligibility":"NOT_AUTHORIZED","trade_authorized":False,
    }
    if parent["status"]!="ONE_EPISODE_DESCRIPTIVE_NOT_BUY_EVIDENCE":
        return {**result,"status":"INSUFFICIENT_PARENT_122_NOT_COMPLETE",
                "selected_eight_mean_net":None,
                "selected_eight_minus_parent_122":None,
                "selected_eight_minus_H00300_total_return":None}
    by_id={r["canonical_security_id"]:r for r in outcome["securities"]}
    returns=[
        by_id[sid]["adjusted_exit_close"]/by_id[sid]["adjusted_entry_close"]-1
        for sid in selected
    ]
    gross=sum(returns)/8
    net=gross-.003
    return {**result,"status":"ONE_EPISODE_EXPLORATORY_NOT_BUY_EVIDENCE",
            "selected_eight_mean_gross":gross,
            "selected_eight_mean_net":net,
            "parent_122_mean_net":parent["mean_net"],
            "benchmark_H00300_total_return":parent["benchmark_total_return"],
            "selected_eight_minus_parent_122":net-parent["mean_net"],
            "selected_eight_minus_H00300_total_return":net-parent["benchmark_total_return"],
            "per_selected_name_net_return":[
                {"security_id":sid,"net_return":ret-.003}
                for sid,ret in zip(selected,returns)
            ]}

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--parent",type=Path,required=True)
    parser.add_argument("--out",type=Path,required=True)
    args=parser.parse_args()
    now=datetime.now(timezone.utc)
    # Never open future outcomes ahead of the parent trial's maturity.
    if now<datetime(2026,11,27,8,30,tzinfo=timezone.utc):
        raise SystemExit("FUTURE_OUTCOME_EMBARGO")
    if args.out.exists():
        raise ValueError("REFUSE_OVERWRITE_FROZEN_EIGHT_RESEARCH")
    doc=json.loads(args.parent.read_text(encoding="utf-8"))
    result=evaluate(doc,now=now)
    args.out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"status":result["status"],"selected_count":8,
                      "trade_authorized":False},ensure_ascii=False))

if __name__=="__main__":
    main()
