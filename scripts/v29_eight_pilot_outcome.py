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
ENTRY_SNAPSHOT=ROOT/"research/V2.9_FORWARD_122_ENTRY_20261102/ENTRY_SNAPSHOT_122.json"
ENTRY_GIT_BLOB="f3f8864d669b2f273b71f4fcd2ca97d82799b1fb"
SCHEMA="V29_FROZEN_EIGHT_VS_122_POST_MATURITY_RESEARCH_RESULT_V1"

def minimum_lot_reference(root, selected):
    """Post-entry, pre-exit cash-weighted *sensitivity*, never real fills."""
    data=(root/ENTRY_SNAPSHOT.relative_to(ROOT)).read_bytes()
    git_sha=hashlib.sha1(b"blob "+str(len(data)).encode()+b"\0"+data).hexdigest()
    if git_sha!=ENTRY_GIT_BLOB:
        raise ValueError("SEALED_NOV02_ENTRY_BLOB_CHANGED")
    entry=json.loads(data)
    if (entry["entry_session"]!="2026-11-02"
            or entry["market_source_information_status"]!="COMPLETE_QUOTES_AND_OFFICIAL_TR"
            or entry["source_quote_complete_count"]!=122
            or len(entry["rows"])!=122
            or entry["benchmark"]["security_id"]!="H00300.CSI"):
        raise ValueError("NOV02_ENTRY_NOT_VALID_FOR_LOT_SENSITIVITY")
    names={x["security_id"]:x for x in entry["rows"]}
    if len(names)!=122:
        raise ValueError("ENTRY_IDENTITY_NOT_UNIQUE")
    lots=[]
    for sid in selected:
        row=names[sid]
        if not row["source_bar_pair_complete"]:
            raise ValueError("ORIGINAL_EIGHT_ENTRY_BAR_MISSING")
        # All eight selected symbols are on the main/ChiNext board, 100
        # shares each; this does not infer actual user capital or permissions.
        if sid.startswith("SSE:688"):
            raise ValueError("EIGHT_REFERENCE_LOT_ASSUMPTION_CHANGED")
        notional=round(float(row["entry_unadjusted"]["close"])*100,2)
        if notional<=0:
            raise ValueError("INVALID_MINIMUM_LOT_NOTIONAL")
        lots.append((sid,notional))
    total=round(sum(notional for _,notional in lots),2)
    return {
        "actual_reference_session":"2026-11-02",
        "sealed_entry_snapshot_sha256":hashlib.sha256(data).hexdigest(),
        "min_lot_reference_notional_cny":total,
        "min_lot_fee_and_slippage_excluded_from_reference_cash":True,
        "personal_available_cash_or_risk_budget_unknown":True,
        "tradeable_close_fill_proven":False,
        "weights":[{"security_id":sid,"shares":100,
                    "reference_notional_cny":notional,
                    "capital_weight":notional/total}
                   for sid,notional in lots],
    }

def evaluate(outcome, now=None, root=ROOT):
    root=Path(root)
    blob=(root/PILOT.relative_to(ROOT)).read_bytes()
    # Bind to the pre-close Git blob, rather than copying eight names a second time.
    git_blob_sha=hashlib.sha1(b"blob "+str(len(blob)).encode()+b"\0"+blob).hexdigest()
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
    minimum_lot=minimum_lot_reference(root,selected)
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
        "post_entry_pre_outcome_min_lot_sensitivity":True,
        "minimum_lot_entry_reference":minimum_lot,
        "live_buy_eligibility":"NOT_AUTHORIZED","trade_authorized":False,
    }
    if parent["status"]!="ONE_EPISODE_DESCRIPTIVE_NOT_BUY_EVIDENCE":
        return {**result,"status":"INSUFFICIENT_PARENT_122_NOT_COMPLETE",
                "selected_eight_mean_net":None,
                "selected_eight_minus_parent_122":None,
                "selected_eight_minus_H00300_total_return":None,
                "min_lot_weighted_net_proxy":None,
                "min_lot_minus_equal_eight_net_proxy":None}
    by_id={r["canonical_security_id"]:r for r in outcome["securities"]}
    returns=[
        by_id[sid]["adjusted_exit_close"]/by_id[sid]["adjusted_entry_close"]-1
        for sid in selected
    ]
    gross=sum(returns)/8
    net=gross-.003
    weights=[r["capital_weight"] for r in minimum_lot["weights"]]
    min_lot_net=sum(w*(ret-.003) for w,ret in zip(weights,returns))
    return {**result,"status":"ONE_EPISODE_EXPLORATORY_NOT_BUY_EVIDENCE",
            "selected_eight_mean_gross":gross,
            "selected_eight_mean_net":net,
            "parent_122_mean_net":parent["mean_net"],
            "benchmark_H00300_total_return":parent["benchmark_total_return"],
            "selected_eight_minus_parent_122":net-parent["mean_net"],
            "selected_eight_minus_H00300_total_return":net-parent["benchmark_total_return"],
            "min_lot_weighted_net_proxy":min_lot_net,
            "min_lot_minus_equal_eight_net_proxy":min_lot_net-net,
            "min_lot_minus_H00300_total_return":min_lot_net-parent["benchmark_total_return"],
            "min_lot_same_round_trip_cost_assumption":.003,
            "min_lot_paper_proxy_not_broker_fill":True,
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
