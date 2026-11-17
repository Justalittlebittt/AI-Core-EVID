#!/usr/bin/env python3
"""Single preregistered archived-sample development test of 120-to-20-session momentum.

Do not re-use this test as independent OOS. Outcomes for low-vol and reversal
were already inspected from the same 2026-vintage archive. No market downloads.
"""
import gzip
import hashlib
import json
import math
from collections import Counter
from datetime import date
from pathlib import Path
from statistics import mean

from v31_low_volatility_2023_2024_one_shot import (
    ROOT, actual_signal_months, checked_bars, realized, sid_to_bs, val,
)
from v29_2025_filing_to_return_case import validated_calendar

SPEC=ROOT/"research/V3.1_MEDIUM_TERM_MOMENTUM_SKIP20_DEVELOPMENT_SPEC_20261117.json"
ARCH=ROOT/"research/v31_2023_2024_lowvol_one_shot/RAW_BAOSTOCK_SOURCE.json.gz"
PRIOR=ROOT/"research/v31_2023_2024_lowvol_one_shot/RESULT.json"
SCHEMA="V31_MEDIUM_MOMENTUM_SKIP20_ARCHIVED_DEV_RESULT_V1"

def build():
    sraw=SPEC.read_bytes()
    s=json.loads(sraw)
    if s["schema"]!="V31_MEDIUM_MOMENTUM_SKIP20_ARCHIVED_DEV_ONE_SHOT_SPEC_V1":
        raise ValueError("FROZEN_MOMENTUM_SPEC_MISMATCH")
    raw=gzip.decompress(ARCH.read_bytes())
    sha=hashlib.sha256(raw).hexdigest()
    if sha!=s["source_sha256"]:raise ValueError("FROZEN_SOURCE_CHANGED")
    source=json.loads(raw)
    prior=json.loads(PRIOR.read_bytes())
    if prior["raw_source_sha256"]!=sha:raise ValueError("SOURCE_NOT_IDENTICAL_TO_PAST_RESEARCH")
    sessions=validated_calendar(source["calendar"])
    months=actual_signal_months(sessions)
    if len(months)!=20:raise ValueError("SIGNAL_MONTH_COUNT_NOT_20")
    frames=source["frames"]
    for year in ("2023","2024"):
        if frames[year]["selected_ids"]!=prior["sample_years"][year]["ids"]:
            raise ValueError("SAMPLE_COHORT_CHANGED")
        if len(frames[year]["selected_ids"])!=128:raise ValueError("INVALID_FROZEN_COHORT")
    ids=set(frames["2023"]["selected_ids"])|set(frames["2024"]["selected_ids"])
    allowed=set(sessions)
    bars={}
    errors={}
    for sid in sorted(ids):
        try:
            bars[sid]=checked_bars(source["quotes"].get(sid),sid_to_bs(sid),allowed)
        except (ValueError,TypeError,KeyError) as err:
            bars[sid]=None
            errors[sid]=str(err)[:150]
    results=[]
    for day in months:
        i=sessions.index(day)
        if i<120 or i+20>=len(sessions):raise ValueError("INSUFFICIENT_120_DAY_BEFORE_AND_20_DAY_AFTER")
        entry,exit_day=sessions[i+1],sessions[i+20]
        eligible=[]
        reasons=Counter()
        for sid in frames[str(day.year)]["selected_ids"]:
            quotes=bars[sid]
            if quotes is None:
                reasons["SOURCE_INVALID"]+=1
                continue
            before=quotes.get(sessions[i-120])
            recent=quotes.get(sessions[i-20])
            current=quotes.get(day)
            if any(x is None for x in (before,recent,current)):
                reasons["MISSING_PRE_SIGNAL_BAR"]+=1
                continue
            if (current.get("tradestatus")!="1" or current.get("isST")!="0"
                    or val(current,"volume") is None):
                reasons["NOT_NORMAL_TRADEABLE_ON_SIGNAL"]+=1
                continue
            first,last=val(before,"close"),val(recent,"close")
            if first is None or last is None:
                reasons["INVALID_PRE_SIGNAL_CLOSE"]+=1
                continue
            eligible.append({"security_id":sid,"momentum120_skip20":last/first-1})
        eligible.sort(key=lambda x:(-x["momentum120_skip20"],x["security_id"]))
        k=math.ceil(len(eligible)*.25) if len(eligible)>=40 else 0
        selected_ids={x["security_id"] for x in eligible[:k]}
        selected_done=[]
        whole_done=[]
        missing=[]
        for r in eligible:
            result,status=realized(bars[r["security_id"]],entry,exit_day)
            if result is None:
                missing.append({"security_id":r["security_id"],"selected":r["security_id"] in selected_ids,"reason":status})
            else:
                whole_done.append(result-0.003)
                if r["security_id"] in selected_ids:selected_done.append(result-0.003)
        s_cov=len(selected_done)/k if k else 0
        a_cov=len(whole_done)/len(eligible) if eligible else 0
        valid=bool(k>=10 and s_cov>=.95 and a_cov>=.95)
        spread=mean(selected_done)-mean(whole_done) if valid else None
        row={"signal_date":day.isoformat(),"year":day.year,"entry":entry.isoformat(),
             "exit":exit_day.isoformat(),"pre_signal_eligible":len(eligible),"selected_count":k,
             "resolved_selected":len(selected_done),"resolved_full":len(whole_done),
             "selected_coverage":s_cov,"full_coverage":a_cov,
             "selected_net_proxy":mean(selected_done) if selected_done else None,
             "whole_eligible_net_proxy":mean(whole_done) if whole_done else None,
             "selected_minus_eligible_net_proxy":spread,"valid":valid,
             "selected_ids":[r["security_id"] for r in eligible[:k]],
             "missing":missing,"ineligible_reason_count":dict(reasons)}
        results.append(row)
        print("V31_MOMENTUM_DEV_MONTH="+json.dumps({key:row[key] for key in (
            "signal_date","pre_signal_eligible","selected_count","selected_coverage",
            "full_coverage","selected_minus_eligible_net_proxy","valid")},ensure_ascii=False),flush=True)
    valid=[x for x in results if x["valid"]]
    spreads=[r["selected_minus_eligible_net_proxy"] for r in valid]
    year_means={str(y):mean(r["selected_minus_eligible_net_proxy"] for r in valid if r["year"]==y)
                if any(r["year"]==y for r in valid) else None for y in (2023,2024)}
    checks={"valid_months":len(valid)>=s["decision"]["min_valid_months"],
       "positive_both_years":all(y is not None and y>0 for y in year_means.values()),
       "mean_positive":bool(spreads and mean(spreads)>0),
       "positive_share_at_least_60pct":bool(spreads and sum(x>0 for x in spreads)/len(spreads)>=.6),
       "without_best_positive":bool(len(spreads)>1 and mean(sorted(spreads)[:-1])>0)}
    status="INSUFFICIENT_COVERAGE" if not checks["valid_months"] else (
        "DESCRIPTIVE_SUPPORT_ONLY_NOT_ALPHA" if all(checks.values())
        else "NOT_SUPPORTED_BY_THIS_RETROSPECTIVE_SAMPLE")
    return {"schema":SCHEMA,"spec_sha256":hashlib.sha256(sraw).hexdigest(),
       "archive_sha256":sha,"status":status,"checks":checks,
       "valid_months":len(valid),"total_months":len(results),
       "positive_share":sum(x>0 for x in spreads)/len(spreads) if spreads else None,
       "mean_monthly_selected_minus_full_net_proxy":mean(spreads) if spreads else None,
       "year_means":year_means,
       "mean_without_best_month":mean(sorted(spreads)[:-1]) if len(spreads)>1 else None,
       "source_integrity_errors":errors,"months":results,
       "historical_archive_previously_opened_for_other_strategies":True,
       "independent_unseen_OOS":False,"true_total_return_certified":False,
       "lot_level_fees_and_auction_fill_verified":False,
       "live_trade_authorized":False,"decision":"NO_BUY"}

if __name__=="__main__":
    out=build()
    print("V31_MOMENTUM_DEV_VERDICT="+json.dumps({k:v for k,v in out.items() if k not in ("months","source_integrity_errors")},ensure_ascii=False),flush=True)
    import argparse
    p=argparse.ArgumentParser()
    p.add_argument("--output",type=Path,required=True)
    args=p.parse_args()
    args.output.write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
