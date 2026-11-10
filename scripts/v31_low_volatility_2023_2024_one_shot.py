#!/usr/bin/env python3
"""One predeclared historical *falsification*, not stock advice or pristine OOS.

Studies absolute 60-session volatility (not rejected rv10/rv60 ratio) in two
outcome-blind issuer samples fixed separately in early 2023 and 2024.
The vendor's 2026-vintage adjusted bars are NOT certified as originally available
historical corporate-action data. This limitation is retained in the verdict.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import math
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from statistics import mean, median, pstdev

from v29_historical_universe_sampling import select_membership_frame, INTERVALS
from v29_2025_filing_to_return_case import records, validated_calendar

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "research/V3.1_LOW_VOLATILITY_2023_2024_HISTORICAL_ONE_SHOT_SPEC_20261110.json"
SCHEMA = "V31_2023_2024_ABSOLUTE_LOW_VOL_HISTORICAL_ONE_SHOT_RESULT_V1"
CAL_START, CAL_END = "2022-08-01", "2025-01-31"
FIELDS = "date,code,open,close,adjustflag,tradestatus,isST,volume"
INDEX_FIELDS = "date,code,open,close"
MIN_ELIGIBLE = 40
COST = 0.003


def sha(blob):
    return hashlib.sha256(blob).hexdigest()


def load_contract():
    raw = SPEC.read_bytes()
    x = json.loads(raw)
    if (x.get("schema") != "V31_LATE_YEAR_INDEPENDENT_SAMPLE_LOW_ABSOLUTE_VOL_2023_2024_PREOUTCOME_SPEC_V1"
        or x["sample"]["frame_dates"] != ["2023-01-03", "2024-01-02"]
        or x["sample"]["each_frame_count"] != 128
        or x["date_policy"]["quote_capture_start"] != CAL_START
        or x["date_policy"]["quote_capture_end"] != CAL_END
        or x["outcome"]["cost_selected_round_trip_fraction"] != COST
        or x["outcome"]["cost_full_universe_comparator_round_trip_fraction"] != COST
        or x["signal"]["select"] != "bottom ceil(25% of eligible same-day sample), require >=40 eligible same-day stocks"
        or x["decision"]["trade_authorized"] is not False):
        raise ValueError("FIXED_HISTORICAL_RULE_IDENTITY_CHANGED")
    return x, sha(raw)


def frames_for_contract(spec):
    content = INTERVALS.read_bytes()
    if sha(content) != spec["sample"]["expected_source_sha256"]:
        raise ValueError("PIT_INTERVAL_SOURCE_CHANGED")
    records_ = list(csv.DictReader(content.decode("utf-8-sig").splitlines()))
    result = {}
    for year,day,seed in zip([2023,2024],spec["sample"]["frame_dates"],spec["sample"]["seeds"]):
        f = select_membership_frame(records_,date.fromisoformat(day),128,seed)
        if f["sample_count"] != 128 or len(set(f["selected_ids"])) != 128:
            raise ValueError("MEMBERSHIP_COHORT_INTEGRITY_FAILED")
        result[str(year)] = f
    return result, sha(content)


def sid_to_bs(sid):
    exchange,code=sid.split(":")
    if exchange not in ("SSE","SZSE") or len(code)!=6 or not code.isdecimal():
        raise ValueError("INVALID_STOCK_ID")
    return ("sh." if exchange=="SSE" else "sz.")+code


def actual_signal_months(days):
    by_month = {}
    for d in days:
        if ((d.year==2023 and 4<=d.month<=12)
            or (d.year==2024 and 1<=d.month<=11)):
            by_month.setdefault((d.year,d.month),d)
    if len(by_month)!=20:
        raise ValueError("MISSING_2023_OR_2024_SIGNAL_MONTH")
    return [by_month[key] for key in sorted(by_month)]


def checked_bars(rows,expected_code,calendar):
    if rows is None:
        return None
    seen={}
    for item in rows:
        d=date.fromisoformat(item["date"])
        if item["code"]!=expected_code:
            raise ValueError("BAR_SECURITY_ID_MISMATCH")
        if d not in calendar:
            raise ValueError("BAR_OFF_EXCHANGE_CALENDAR:"+d.isoformat())
        if d in seen:
            raise ValueError("DUPLICATE_STOCK_DATE:"+d.isoformat())
        if item.get("adjustflag") != "2":
            raise ValueError("ADJUSTFLAG_NOT_ADJUSTED:date="+d.isoformat()+":observed="+str(item.get("adjustflag")))
        seen[d] = item
    return seen


def val(row,key):
    try:
        v = float(row[key])
        return v if math.isfinite(v) and v>0 else None
    except (TypeError,KeyError,ValueError,OverflowError):
        return None


def at_signal(bars, sessions, i):
    """Return a *pre-outcome* rankable observation or a source-status only."""
    if bars is None:
        return None,"QUOTE_SOURCE_UNAVAILABLE"
    if i < 60:
        return None,"NOT_ENOUGH_PRIOR_EXCHANGE_SESSIONS"
    window = [bars.get(day) for day in sessions[i-60:i+1]]
    if any(q is None or val(q,"close") is None for q in window):
        return None,"INCOMPLETE_61_SESSION_PRICE_WINDOW"
    dbar=window[-1]
    if (dbar.get("tradestatus")!="1" or dbar.get("isST")!="0"
        or val(dbar,"volume") is None):
        return None,"NOT_ACTIVE_NORMAL_WITH_VOLUME_AT_SIGNAL"
    closes=[val(q,"close") for q in window]
    vol=pstdev([math.log(closes[j]/closes[j-1]) for j in range(1,len(closes))])
    if not math.isfinite(vol) or vol<=0:
        return None,"VOLATILITY_NOT_POSITIVE"
    return vol,"RANK_ELIGIBLE"


def realized(bars, entry, exit_date):
    """Only after ranking: use D+1 open and D+20 close; no later-date shift."""
    if bars is None:
        return None,"QUOTE_SOURCE_UNAVAILABLE_AT_OUTCOME"
    first,final=bars.get(entry),bars.get(exit_date)
    if first is None or final is None:
        return None,"ENTRY_OR_EXIT_BAR_MISSING"
    if (first.get("tradestatus")!="1" or first.get("isST")!="0"
        or val(first,"volume") is None):
        return None,"ENTRY_STATUS_OR_VOLUME_UNRESOLVED"
    # ST at exit is conservatively marked unresolved, not deemed impossible
    # to sell: the source cannot guarantee limit-price execution.
    if (final.get("tradestatus")!="1" or final.get("isST")!="0"
        or val(final,"volume") is None):
        return None,"EXIT_STATUS_NOT_CERTIFIED_AS_NORMAL"
    entry_price=val(first,"open")
    exit_price=val(final,"close")
    if entry_price is None or exit_price is None:
        return None,"INVALID_ENTRY_OPEN_OR_EXIT_CLOSE"
    return exit_price/entry_price-1,"PRICE_RETURN_PROXY_ONLY"


def compute(spec, frames, cal, index_rows, quote_rows):
    sessions=validated_calendar(cal)
    if (sessions[0] < date.fromisoformat(CAL_START)
        or sessions[-1] > date.fromisoformat(CAL_END)):
        raise ValueError("CALENDAR_RANGE_WRONG")
    signal_days=actual_signal_months(sessions)
    index={}
    for x in index_rows:
        d=date.fromisoformat(x["date"])
        if x["code"]!="sh.000300" or d not in sessions or d in index:
            raise ValueError("INDEX_ID_DATE_DUPLICATE_FAILURE")
        index[d]=x
    syms={id for f in frames.values() for id in f["selected_ids"]}
    bars={}
    allowed=set(sessions)
    integrity_errors={}
    for sid in syms:
        try:
            bars[sid]=checked_bars(quote_rows.get(sid),sid_to_bs(sid),allowed)
        except (ValueError,KeyError,TypeError) as exc:
            # Never silently replace an invalid security with another. Keep the
            # preselected issuer and record its failed source integrity.
            bars[sid]=None
            integrity_errors[sid]=str(exc)[:180]
    months=[]
    samples=[]
    for d in signal_days:
        y=str(d.year)
        ids=frames[y]["selected_ids"]
        i=sessions.index(d)
        if i+20>=len(sessions):
            raise ValueError("INSUFFICIENT_FUTURE_TRADING_CALENDAR")
        entry,target=sessions[i+1],sessions[i+20]
        candidates=[]
        statuses=defaultdict(int)
        for sid in ids:
            feature,status=at_signal(bars[sid],sessions,i)
            statuses[status]+=1
            if feature is not None:
                candidates.append({"security_id":sid,"volatility60":feature,
                                   "selected":False,"outcome_return":None,
                                   "outcome_status":"NOT_YET_READ"})
        sorted_candidates=sorted(candidates,key=lambda z:(z["volatility60"],z["security_id"]))
        qualifies=len(sorted_candidates)>=MIN_ELIGIBLE
        if qualifies:
            k=math.ceil(len(sorted_candidates)*.25)
            for x in sorted_candidates[:k]:x["selected"]=True
        else:k=0
        # The selection is now fixed; outcome endpoints cannot alter membership.
        for item in candidates:
            q,status=realized(bars[item["security_id"]],entry,target)
            item["outcome_return"]=q
            item["outcome_status"]=status
        selected=[x for x in candidates if x["selected"]]
        sel_done=[x for x in selected if x["outcome_return"] is not None]
        pop_done=[x for x in candidates if x["outcome_return"] is not None]
        selcov=(len(sel_done)/len(selected)) if selected else 0
        popcov=(len(pop_done)/len(candidates)) if candidates else 0
        smean=mean(x["outcome_return"]-COST for x in sel_done) if sel_done else None
        bmean=mean(x["outcome_return"]-COST for x in pop_done) if pop_done else None
        idx0,idx1=index.get(entry),index.get(target)
        idxreturn=(val(idx1,"close")/val(idx0,"open")-1) if (
            idx0 and idx1 and val(idx0,"open") and val(idx1,"close")) else None
        valid=qualifies and selcov>=.95 and popcov>=.95 and idxreturn is not None
        monthrow={"signal_date":d.isoformat(),"year":d.year,
                  "portfolio_entry_date":entry.isoformat(),"portfolio_exit_date":target.isoformat(),
                  "membership_sample_count":len(ids),"signal_eligible_count":len(candidates),
                  "selected_count":k,"signal_ineligible_counts":dict(statuses),
                  "selected_outcome_resolved":len(sel_done),"full_pool_outcome_resolved":len(pop_done),
                  "selected_resolved_fraction":selcov,"full_pool_resolved_fraction":popcov,
                  "selected_mean_net_proxy":smean,"same_day_sample_all_mean_net_proxy":bmean,
                  "csi300_price_index_same_window_return":idxreturn,
                  "selection_minus_pool_net":(smean-bmean) if valid else None,
                  "selection_net_minus_csi300_price_index":(smean-idxreturn) if valid else None,
                  "admissible_descriptive_month":valid,
                  "selected_identities":[x["security_id"] for x in selected],
                  "selected_unresolved_ids":[x["security_id"] for x in selected if x["outcome_return"] is None]}
        months.append(monthrow)
        samples.append({"signal_date":d.isoformat(),"year":d.year,
                        "entry":entry.isoformat(),"exit":target.isoformat(),
                        "candidates":candidates})
    ok=[x for x in months if x["admissible_descriptive_month"]]
    yearmeans={str(year):mean(x["selection_minus_pool_net"] for x in ok if x["year"]==year)
               if any(x["year"]==year for x in ok) else None for year in (2023,2024)}
    diff=[x["selection_minus_pool_net"] for x in ok]
    pass_positive=(len(ok)>=spec["decision"]["minimum_evaluated_months"]
                   and yearmeans["2023"] is not None and yearmeans["2024"] is not None
                   and yearmeans["2023"]>0 and yearmeans["2024"]>0
                   and mean(diff)>0 and sum(x>0 for x in diff)/len(diff)>=.6)
    status=("INSUFFICIENT_SOURCE_COVERAGE" if len(ok)<spec["decision"]["minimum_evaluated_months"]
            else "DESCRIPTIVE_SUPPORT_NOT_ALPHA" if pass_positive
            else "NOT_SUPPORTED_BY_THIS_RETROSPECTIVE_SAMPLE")
    return {
        "schema":SCHEMA,
        "hypothesis":"LOW_ABSOLUTE_60_SESSION_VOLATILITY",
        "prior_factor_rv10_over_rv60_tested_again":False,
        "sampling_policy":"TWO_SEPARATE_EARLY_YEAR_PIT_MEMBERSHIP_HASH_SAMPLES_128_EACH",
        "sample_years":{y:{"asof":f["frame_date"],"population":f["population_count"],
                           "ids":f["selected_ids"],"ids_sha256":f["selected_ids_sha256"]}
                        for y,f in frames.items()},
        "instrument_bar_integrity_error_count":len(integrity_errors),
        "instrument_bar_integrity_errors":dict(sorted(integrity_errors.items())),
        "requested_signal_months":len(months),"valid_descriptive_months":len(ok),
        "selected_event_count":sum(x["selected_count"] for x in months),
        "selected_resolved_count":sum(x["selected_outcome_resolved"] for x in months),
        "valid_months_positive_share":sum(x>0 for x in diff)/len(diff) if diff else None,
        "primary_monthly_equal_weight_excess_selected_net_vs_sample_net":mean(diff) if diff else None,
        "median_valid_monthly_excess":median(diff) if diff else None,
        "year_2023_and_2024_mean_excess":yearmeans,
        "secondary_mean_selected_net_minus_csi300_price":mean(x["selection_net_minus_csi300_price_index"] for x in ok) if ok else None,
        "status":status,"months":months,
        "retrospective_2026_market_vendor_vintage_not_historical_source_sealed":True,
        "corporate_action_economic_return_independently_certified":False,
        "buy_fill_price_limit_certified":False,
        "market_index_price_only_not_total_return":True,
        "small_2_year_sample_not_untouched_independent_oos":True,
        "live_buy_eligibility":"NOT_AUTHORIZED","trade_authorized":False,
    },samples


def collect(bs, folder):
    folder=Path(folder)
    if folder.exists():raise ValueError("ONE_SHOT_RESEARCH_OUTPUT_ALREADY_EXISTS")
    spec, spec_sha = load_contract()
    frames,source_sha=frames_for_contract(spec)
    ids=sorted({sid for f in frames.values() for sid in f["selected_ids"]})
    if len(ids)<128 or len(ids)>256:
        raise ValueError("SAMPLE_SET_NOT_PRESERVED")
    login=bs.login()
    if login.error_code!="0":raise ValueError("BAOSTOCK_LOGIN_FAILED")
    quotes={}
    try:
        cal=records(bs.query_trade_dates(start_date=CAL_START,end_date=CAL_END))
        index=records(bs.query_history_k_data_plus(
            "sh.000300",INDEX_FIELDS,start_date=CAL_START,end_date=CAL_END,
            frequency="d",adjustflag="3"))
        for i,sid in enumerate(ids,1):
            try:
                quotes[sid]=records(bs.query_history_k_data_plus(
                    sid_to_bs(sid),FIELDS,start_date=CAL_START,end_date=CAL_END,
                    frequency="d",adjustflag="2"))
            except (OSError,ValueError,KeyError) as exc:
                quotes[sid]=None
            if i%32==0 or i==len(ids):
                print("BAOSTOCK_SOURCE_PROGRESS",i,len(ids),flush=True)
    finally:
        bs.logout()
    source={"calendar":cal,"benchmark":index,"quotes":quotes,"frames":frames,
            "source":"BAOSTOCK_ADJUSTED_2026_VENDOR_VINTAGE","fields":FIELDS}
    raw=(json.dumps(source,sort_keys=True,ensure_ascii=False,separators=(",",":"))+"\n").encode()
    folder.mkdir(parents=True)
    (folder/"RAW_BAOSTOCK_SOURCE.json.gz").write_bytes(gzip.compress(raw,mtime=0))
    # Keep raw source even if a downstream calculation or serialization fails.
    report,observations=compute(spec,frames,cal,index,quotes)
    report.update({"study_contract_sha256":spec_sha,
                   "membership_interval_sha256":source_sha,
                   "raw_source_sha256":sha(raw),
                   "captured_at_utc":datetime.now(timezone.utc).isoformat(),
                   "issuer_price_query_count":len(ids),
                   "instrument_source_failures":sum(x is None for x in quotes.values()),
                   "opportunities_source_gzip":"OBSERVATIONS.json.gz"})
    (folder/"RESULT.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    obs=(json.dumps(observations,ensure_ascii=False,sort_keys=True,separators=(",",":"))+"\n").encode()
    (folder/"OBSERVATIONS.json.gz").write_bytes(gzip.compress(obs,mtime=0))
    print(json.dumps({k:v for k,v in report.items() if k not in ("months","sample_years")},
                     ensure_ascii=False,sort_keys=True),flush=True)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--out",type=Path,required=True)
    args=parser.parse_args()
    import baostock
    collect(baostock,args.out)


if __name__=="__main__":
    main()
