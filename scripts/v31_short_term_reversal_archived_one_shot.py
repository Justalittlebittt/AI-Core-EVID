#!/usr/bin/env python3
"""One fixed, outcome-later short-term reversal falsification on an existing source archive.

Research only: 2026 vendor-adjusted history is not original-vintage executable data.
The rule is externally motivated and preregistered before this script was run.
No download, no strategy grid, no frozen 2026 forward outcomes, no trading.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import math
from collections import Counter
from datetime import date
from pathlib import Path
from statistics import mean, median

from v31_low_volatility_2023_2024_one_shot import (
    ROOT, actual_signal_months, checked_bars, realized, sid_to_bs, val,
)
from v29_2025_filing_to_return_case import validated_calendar

SPEC = ROOT / "research/V3.1_SHORT_TERM_REVERSAL_ONE_SHOT_SPEC_20261113.json"
ARCH = ROOT / "research/v31_2023_2024_lowvol_one_shot/RAW_BAOSTOCK_SOURCE.json.gz"
PRIOR = ROOT / "research/v31_2023_2024_lowvol_one_shot/RESULT.json"


def build():
    spec_raw = SPEC.read_bytes()
    spec = json.loads(spec_raw)
    if (spec["schema"] != "V31_SHORT_TERM_REVERSAL_FIXED_ONE_SHOT_SPEC_V1"
            or spec["design"]["cost_selected_roundtrip_fraction"] != 0.003
            or spec["design"]["cost_full_eligible_roundtrip_fraction"] != 0.003
            or spec["decision"]["trade_authorized"] is not False):
        raise ValueError("PREDECLARED_REVERSAL_RULE_CHANGED")
    source_raw = gzip.decompress(ARCH.read_bytes())
    if hashlib.sha256(source_raw).hexdigest() != spec["immutable_data"]["uncompressed_raw_sha256"]:
        raise ValueError("FROZEN_PRICE_ARCHIVE_HASH_MISMATCH")
    src = json.loads(source_raw)
    prior = json.loads(PRIOR.read_bytes())
    if prior["raw_source_sha256"] != spec["immutable_data"]["uncompressed_raw_sha256"]:
        raise ValueError("PREVIOUS_SOURCE_PROVENANCE_CHANGED")
    frames = src["frames"]
    for f in spec["immutable_data"]["year_frames"]:
        year = str(f["year"])
        rows = frames[year]["selected_ids"]
        if (rows != prior["sample_years"][year]["ids"]
                or len(rows) != f["sample_size"]
                or len(set(rows)) != f["sample_size"]
                or frames[year]["selected_ids_sha256"] != f["ids_sha256"]):
            raise ValueError("ORIGINAL_128_MEMBER_IDENTITY_CHANGED:" + year)

    sessions = validated_calendar(src["calendar"])
    signal_days = actual_signal_months(sessions)
    assert len(signal_days) == 20
    if str(sessions[0]) != "2022-08-01" or str(sessions[-1]) != "2025-01-31":
        raise ValueError("SOURCE_EXCHANGE_CALENDAR_WRONG")
    allowed = set(sessions)
    identities = {sid for f in frames.values() for sid in f["selected_ids"]}
    source_bars,source_errors = {},{}
    for sid in identities:
        try:
            source_bars[sid] = checked_bars(src["quotes"].get(sid),sid_to_bs(sid),allowed)
        except (KeyError,ValueError,TypeError) as exc:
            source_bars[sid] = None
            source_errors[sid] = str(exc)[:180]
    index = {}
    for item in src["benchmark"]:
        dt = date.fromisoformat(item["date"])
        if item["code"] != "sh.000300" or dt in index or dt not in allowed:
            raise ValueError("INVALID_BENCHMARK_SESSION_OR_ID")
        index[dt] = item
    months = []
    for d in signal_days:
        i = sessions.index(d)
        if i < 20 or i+20 >= len(sessions):
            raise ValueError("INSUFFICIENT_PRE_OUTCOME_SESSIONS")
        entry,exit_date = sessions[i+1],sessions[i+20]
        ids = frames[str(d.year)]["selected_ids"]
        elig,reason_counts = [],Counter()
        for sid in ids:
            data = source_bars[sid]
            if data is None:
                reason_counts["SOURCE_MISSING_OR_BAD"] += 1
                continue
            lookback = [data.get(day) for day in sessions[i-20:i+1]]
            if any(x is None or val(x,"close") is None for x in lookback):
                reason_counts["MISSING_21_PRIOR_VALID_CLOSES"] += 1
                continue
            last = lookback[-1]
            if (last.get("tradestatus") != "1"
                    or last.get("isST") != "0"
                    or val(last,"volume") is None):
                reason_counts["NOT_NORMAL_ACTIVE_AT_SIGNAL"] += 1
                continue
            past = val(last,"close")/val(lookback[0],"close")-1
            if not math.isfinite(past):
                reason_counts["INVALID_RETURN"] += 1
                continue
            elig.append({"security_id":sid,"past_20_session_return":past,
                         "outcome":None,"outcome_status":"NOT_YET_READ"})
        # Fix the selection before reading D+1/D+20 returns for any security.
        ranked = sorted(elig,key=lambda x:(x["past_20_session_return"],x["security_id"]))
        qualified = len(ranked)>=40
        count = math.ceil(len(ranked)*0.25) if qualified else 0
        selected_ids = {r["security_id"] for r in ranked[:count]}
        for x in ranked:
            x["outcome"],x["outcome_status"] = realized(source_bars[x["security_id"]],entry,exit_date)
        selected = [x for x in ranked if x["security_id"] in selected_ids]
        s_ok = [x for x in selected if x["outcome"] is not None]
        a_ok = [x for x in ranked if x["outcome"] is not None]
        s_cov = len(s_ok)/count if count else 0
        a_cov = len(a_ok)/len(ranked) if ranked else 0
        index_first,index_last = index.get(entry),index.get(exit_date)
        idx_ret = (val(index_last,"close")/val(index_first,"open")-1) if (
            index_first and index_last and val(index_first,"open")
            and val(index_last,"close")) else None
        valid = (qualified
                 and s_cov >= spec["decision"]["min_selected_resolved_share"]
                 and a_cov >= spec["decision"]["min_full_eligible_resolved_share"]
                 and idx_ret is not None)
        s_net = mean(x["outcome"]-0.003 for x in s_ok) if s_ok else None
        a_net = mean(x["outcome"]-0.003 for x in a_ok) if a_ok else None
        months.append({
            "signal_date":d.isoformat(),"year":d.year,
            "entry_date":entry.isoformat(),"exit_date":exit_date.isoformat(),
            "pre_signal_eligible":len(ranked),"selected_count":count,
            "resolved_selected":len(s_ok),"resolved_full_eligible":len(a_ok),
            "selected_resolved_share":s_cov,"full_eligible_resolved_share":a_cov,
            "selected_net_proxy":s_net,"all_eligible_net_proxy":a_net,
            "selected_minus_all_eligible_net":(s_net-a_net) if valid else None,
            "selected_net_minus_csi300_price":(s_net-idx_ret) if valid else None,
            "selected_ids":[r["security_id"] for r in ranked[:count]],
            "unresolved_selected":[r["security_id"] for r in selected if r["outcome"] is None],
            "signal_status_count":dict(reason_counts),
            "valid_descriptive_month":valid,
        })
    valid = [x for x in months if x["valid_descriptive_month"]]
    spreads = [x["selected_minus_all_eligible_net"] for x in valid]
    yr = {str(y):[x["selected_minus_all_eligible_net"] for x in valid if x["year"]==y] for y in (2023,2024)}
    yr_mean = {y:mean(v) if v else None for y,v in yr.items()}
    no_best = mean(sorted(spreads)[:-1]) if len(spreads)>1 else None
    tested = (len(valid)>=spec["decision"]["min_valid_months"]
              and len(yr["2023"])>0 and len(yr["2024"])>0)
    supported = (tested and mean(spreads)>0
                 and yr_mean["2023"]>0 and yr_mean["2024"]>0
                 and sum(v>0 for v in spreads)/len(spreads)>=0.6
                 and no_best is not None and no_best>0)
    verdict = ("INSUFFICIENT_COVERAGE" if not tested else
               "DESCRIPTIVE_SUPPORT_ONLY_NOT_ALPHA" if supported else
               "NOT_SUPPORTED_BY_THIS_RETROSPECTIVE_SAMPLE")
    return {
        "schema":"V31_SHORT_TERM_REVERSAL_FROZEN_SOURCE_ONE_SHOT_RESULT_V1",
        "status":verdict,
        "precommitted_spec_sha256":hashlib.sha256(spec_raw).hexdigest(),
        "raw_archive_sha256":hashlib.sha256(source_raw).hexdigest(),
        "archive_data_vintage":"2026-11-10_NOT_ORIGINAL_HISTORICAL_PIT",
        "external_paper_period":"2000-2019_NOT_REPLICATION",
        "source_paper_independently_validates_this_long_only_strategy":False,
        "membership_cohorts_128_each":True,
        "historical_outcomes_in_archive_already_existed_when_rule_registered":True,
        "same_archive_previously_evaluated_for_other_factor":True,
        "signal_only_pre_outcome":True,
        "requested_months":len(months),"valid_months":len(valid),
        "total_selected":sum(x["selected_count"] for x in months),
        "total_selected_resolved":sum(x["resolved_selected"] for x in months),
        "positive_month_fraction":sum(x>0 for x in spreads)/len(spreads) if spreads else None,
        "mean_monthly_selected_minus_full_eligible_net":mean(spreads) if spreads else None,
        "median_monthly_selected_minus_full_eligible_net":median(spreads) if spreads else None,
        "mean_2023_and_2024":yr_mean,
        "mean_excluding_single_best_month":no_best,
        "best_month":max(valid,key=lambda x:x["selected_minus_all_eligible_net"])["signal_date"] if valid else None,
        "mean_selected_net_minus_csi300_price":mean(x["selected_net_minus_csi300_price"] for x in valid) if valid else None,
        "instrument_source_errors":dict(sorted(source_errors.items())),
        "months":months,
        "independent_pristine_oos":False,
        "actual_broker_order_fill_verified":False,
        "economic_total_return_certified":False,
        "strategy_predictive_alpha_validated":False,
        "trade_authorized":False,
        "live_buy_eligibility":"NOT_AUTHORIZED",
    }


def main():
    result = build()
    print("REVERSAL_ONE_SHOT_RESULT="+json.dumps(result,ensure_ascii=False,separators=(",",":")),flush=True)


if __name__=="__main__":
    main()
