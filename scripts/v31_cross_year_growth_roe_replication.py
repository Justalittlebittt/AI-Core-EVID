#!/usr/bin/env python3
"""One-shot 2026 cross-year retrospective replication of the FIXED FY2024/2025
growth+ROE baseline. Financial values are 2026 vendor-vintage, not original-
release PIT; 2026 market outcomes were already observable before this study.
Never calls this untouched OOS, independent alpha or a BUY instruction.
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

from v29_2025_filing_source_coverage import acquire_pages, valid_pages
from v29_2025_filing_to_return_case import records, validated_calendar, validated_bars, first_signal_and_exit, finite_price
from v29_growth_candidate_snapshot import fetch_page, _security
from v29_historical_universe_sampling import INTERVALS, INTERVALS_SHA256, select_membership_frame
from v29_growth_quality_matched_baseline_128 import SPEC, MIN_DAY_SIZE, COST, SEED, REPLICATES
from v290_strategy_validity_evaluator import evaluate_observations
from v292_matched_random_baseline import evaluate_matched_random

import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
SCHEMA="V31_FY2025_DISCLOSED_2026_FIXED_RULE_CROSS_YEAR_RETROSPECTIVE_V1"
SEED_2026="V31_2026_NEW_YEAR_IDENTITY_ONLY_SAMPLE_20261110"
REPORT="2025-12-31"
NOTICE_BEFORE="2026-05-01"
START,END="2026-01-01","2026-06-30"
BAR_FIELDS="date,code,close,adjustflag,tradestatus,isST,volume"
INDEX_FIELDS="date,code,close"

def sha(b):
    return hashlib.sha256(b).hexdigest()

def source_selection():
    """Never inspect returns to choose identities; do not reuse frozen 2026Q3 122."""
    raw=INTERVALS.read_bytes()
    if sha(raw)!=INTERVALS_SHA256:
        raise ValueError("RECONSTRUCTED_MEMBERSHIP_SOURCE_CHANGED")
    frame=select_membership_frame(
        list(csv.DictReader(raw.decode("utf-8-sig").splitlines())),
        frame_date=date(2026,1,2), sample_size=128, seed=SEED_2026)
    spec_bytes=SPEC.read_bytes()
    spec=json.loads(spec_bytes)
    if (spec.get("schema")!="V29_2025_FIXED_128_GROWTH_QUALITY_EXPLORATORY_COMPARISON_SPEC_V1"
        or spec["minimum_tradeable_companies_per_same_entry_session"]!=MIN_DAY_SIZE
        or spec["same_day_random_baseline"]["replicates"]!=REPLICATES
        or spec["same_day_random_baseline"]["seed"]!=SEED
        or spec["selection_count"]!="ceil(number of eligible candidates in exact entry session / 3); stable security_id ascending tie-break"
        or not spec["primary_rule"].startswith("Rank highest 2024 annual revenue growth YoY and ROE")
        or COST!=.003):
        raise ValueError("2025_FIXED_PRIMARY_RULE_NOT_REUSED")
    return frame,sha(spec_bytes)

def financial_sample(frame,pages):
    rows,receipts=valid_pages(pages)
    by_id={}
    for row in rows:
        sid=_security(row)
        if sid not in frame["selected_ids"]:
            continue
        if sid in by_id:
            raise ValueError("DUPLICATED_ANNUAL_VENDOR_ISSUER")
        if str(row.get("REPORTDATE",""))[:10]!=REPORT:
            raise ValueError("ANNUAL_PERIOD_NOT_2025")
        if not str(row.get("NOTICE_DATE") or "").startswith("2026-"):
            continue
        if str(row["NOTICE_DATE"])[:10]>=NOTICE_BEFORE:
            continue
        by_id[sid]=row
    selected=[]
    for sid in frame["selected_ids"]:
        source=by_id.get(sid)
        record={"security_id":sid,"status":"NO_VALID_2026_ANNUAL_VENDOR_ROW"}
        if source:
            record["report_notice_day"]=str(source["NOTICE_DATE"])[:10]
            record["vendor_last_update_day"]=str(source.get("UPDATE_DATE") or "")[:10]
            record["vendor_source_row_sha256"]=sha(json.dumps(source,sort_keys=True,ensure_ascii=False,separators=(",",":")).encode())
            vals=[]
            for col in ("YSTZ","WEIGHTAVG_ROE"):
                try: value=float(source.get(col))
                except (TypeError, ValueError): value=float("nan")
                vals.append(value if math.isfinite(value) else None)
            record["revenue_growth_yoy_pct"],record["weighted_roe_pct"]=vals
            record["status"]="FINANCIAL_COMPLETE" if all(v is not None for v in vals) else "FINANCIAL_FIELD_MISSING"
        selected.append(record)
    return selected,receipts,len(rows)

def code(sid):
    exchange,symbol=sid.split(":")
    return ("sh." if exchange=="SSE" else "sz.")+symbol

def active(b):
    if not b or b.get("tradestatus")!="1" or b.get("isST")!="0":
        return False
    try:
        return float(b["volume"])>0 and finite_price(b["close"])>0
    except (ValueError,TypeError,KeyError):
        return False

def evaluate(frame,fin,calendar,index_rows,quotes):
    days=validated_calendar(calendar)
    if not (days[0]>=date.fromisoformat(START) and days[-1]<=date.fromisoformat(END)):
        raise ValueError("WRONG_CALENDAR_YEAR")
    allowed=set(days)
    index=validated_bars(index_rows,"sh.000300",allowed)
    universe=[]
    groups=defaultdict(list)
    for row in fin:
        out={**row,"entry_eligible":False,"selected_by_fixed_rule":False,
             "outcome_complete":False,"net_return":None,"benchmark_return":None}
        if row["status"]!="FINANCIAL_COMPLETE":
            out["status"]="SOURCE_FINANCIAL_NOT_COMPLETE"
            universe.append(out)
            continue
        try:
            entry,exit_day=first_signal_and_exit(row["report_notice_day"],days,20)
        except ValueError:
            out["status"]="NO_TWENTY_POST_DISCLOSURE_SESSIONS"
            universe.append(out)
            continue
        out["entry_session"],out["exit_session"]=entry.isoformat(),exit_day.isoformat()
        sid=row["security_id"]
        raw=quotes.get(sid)
        if not isinstance(raw,list):
            out["status"]="QUOTE_SOURCE_FAILED"
            universe.append(out)
            continue
        bars=validated_bars(raw,code(sid),allowed,"3")
        e=bars.get(entry)
        if not active(e):
            out["status"]="ENTRY_INELIGIBLE_OR_UNKNOWN"
            universe.append(out)
            continue
        # Selection uses only the previously fixed financial features, report
        # notice date, same-day company pool and ENTRY session state.
        out["entry_eligible"]=True
        out["status"]="ENTRY_ELIGIBLE_OUTCOME_NOT_YET_ASSESSED"
        groups[entry.isoformat()].append(out)
        universe.append(out)
    for day,g in groups.items():
        if len(g)<MIN_DAY_SIZE:continue
        k=math.ceil(len(g)/3)
        rev=sorted(g,key=lambda x:(-x["revenue_growth_yoy_pct"],x["security_id"]))
        roe=sorted(g,key=lambda x:(-x["weighted_roe_pct"],x["security_id"]))
        rrank={r["security_id"]:i for i,r in enumerate(rev)}
        orank={r["security_id"]:i for i,r in enumerate(roe)}
        selected=sorted(g,key=lambda x:(rrank[x["security_id"]]+orank[x["security_id"]],x["security_id"]))[:k]
        for x in selected:x["selected_by_fixed_rule"]=True
    # Only now examine exit data, after selection is frozen in the records.
    for row in universe:
        if not row["entry_eligible"]:continue
        sid=row["security_id"]
        entry=date.fromisoformat(row["entry_session"])
        end=date.fromisoformat(row["exit_session"])
        bars=validated_bars(quotes[sid],code(sid),allowed,"3")
        e,x=bars.get(entry),bars.get(end)
        a,b=index.get(entry),index.get(end)
        if not active(x) or not a or not b:
            row["status"]="OUTCOME_MISSING_OR_UNTRADEABLE_RETAIN_ID"
            continue
        row["outcome_complete"]=True
        row["net_return"]=finite_price(x["close"])/finite_price(e["close"])-1-COST
        row["benchmark_return"]=finite_price(b["close"])/finite_price(a["close"])-1
        row["status"]="RETROSPECTIVE_PRICE_ONLY_NOT_EXECUTABLE_FILL"
    eligible=[x for x in universe if x["entry_eligible"]]
    selected=[x for x in eligible if x["selected_by_fixed_rule"]]
    useful_groups={day for day,g in groups.items() if len(g)>=MIN_DAY_SIZE}
    complete_groups={day for day in useful_groups if all(r["outcome_complete"] for r in groups[day])}
    # No lookahead-dependent listwise deletion. If ANY selected cohort or a
    # matched comparison group is incomplete, the PRIMARY result is insufficient.
    full=bool(selected) and len(useful_groups)==len(complete_groups)
    primary={"status":"INSUFFICIENT_FULL_SELECTED_OR_MATCHED_OUTCOMES",
             "reason":"No qualifying groups or missing future endpoints among any primary matched pool"}
    if full:
        events=pd.DataFrame([
            {"observation_id":r["security_id"],"strategy_return":r["net_return"]+COST,
             "benchmark_return":r["benchmark_return"],"transaction_cost":COST}
            for r in selected])
        ev=evaluate_observations(events)
        opportunities=pd.DataFrame([
            {"opportunity_set_id":r["entry_session"],"security_id":r["security_id"],
             "system_selected":r["selected_by_fixed_rule"],"realized_net_return":r["net_return"]}
            for r in eligible if r["entry_session"] in useful_groups])
        random=evaluate_matched_random(opportunities,replicate_count=REPLICATES,seed=SEED)
        primary={"status":"COMPLETE_RETROSPECTIVE_2026_NONPRISTINE",
                 "selected_net_excess_vs_csi300_price_index":ev.metrics["overall"]["mean_excess_return"],
                 "selected_mean_net":ev.metrics["overall"]["mean_net_return"],
                 "selected_median_net":ev.metrics["overall"]["median_net_return"],
                 "selected_positive_net_share":ev.metrics["overall"]["positive_net_return_share"],
                 "selected_minus_same_day_random_mean_net":random.metrics["matched_random"]["mean_net_return"]["system_minus_random_mean"],
                 "random_replicates_at_or_above_selection_share":random.metrics["matched_random"]["mean_net_return"]["random_replicates_at_or_above_system_share"],
                 "random_tail_not_an_unseen_oos_p_value":True}
    return {"schema":SCHEMA,"financial_report_period":REPORT,
            "financial_notice_before":NOTICE_BEFORE,
            "cohort_asof":"2026-01-02","cohort_size":len(universe),
            "entry_eligible_count":len(eligible),"selected_count":len(selected),
            "comparison_day_group_count":len(useful_groups),
            "complete_comparison_day_group_count":len(complete_groups),
            "selected_outcome_coverage":sum(x["outcome_complete"] for x in selected),
            "unselected_eligible_count":len(eligible)-len(selected),
            "primary":primary,"rows":universe,
            "original_2026_filing_pit_certified":False,
            "current_2026_vendor_financial_fields_not_asof_release_certified":True,
            "2026_outcomes_already_known_when_study_created":True,
            "original_2025_rule_selection_method_changed_only_to_remove_exit_dependent_eligibility":True,
            "independent_untouched_oos":False,
            "returns_are_unadjusted_price_only_not_dividend_total_return":True,
            "benchmark_is_csi300_price_index_not_total_return":True,
            "buy_fill_certified":False,"strategy_validated":False,
            "trade_authorized":False,"live_buy_eligibility":"NOT_AUTHORIZED"}

def capture(bs,folder):
    folder=Path(folder)
    if folder.exists():raise ValueError("DO_NOT_OVERWRITE_ONE_SHOT_REPLICATION")
    frame,spec_sha=source_selection()
    financial_pages=acquire_pages(
        lambda period,page,notice_before:fetch_page(REPORT,page,notice_before=NOTICE_BEFORE))
    financial,financial_receipts,all_financial_rows=financial_sample(frame,financial_pages)
    login=bs.login()
    if login.error_code!="0":raise ValueError("BAOSTOCK_LOGIN_FAILED")
    quotes={}
    try:
        calendar=records(bs.query_trade_dates(start_date=START,end_date=END))
        index=records(bs.query_history_k_data_plus(
            "sh.000300",INDEX_FIELDS,start_date=START,end_date=END,frequency="d",adjustflag="3"))
        for k,row in enumerate(financial,1):
            sid=row["security_id"]
            if row["status"]!="FINANCIAL_COMPLETE":
                quotes[sid]=[]
                continue
            try:
                quotes[sid]=records(bs.query_history_k_data_plus(
                    code(sid),BAR_FIELDS,start_date=START,end_date=END,frequency="d",adjustflag="3"))
            except (OSError,ValueError,KeyError):
                quotes[sid]=None
            if k%16==0:
                print("HISTORICAL_2026_QUOTES",k,"of",len(financial),flush=True)
    finally:
        bs.logout()
    source={"sample":frame,"frozen_2025_rule_sha256":spec_sha,
            "financial_raw_page_utf8":[b.decode("utf-8") for b in financial_pages],
            "calendar":calendar,"index":index,"quotes":quotes}
    raw=(json.dumps(source,ensure_ascii=False,sort_keys=True,separators=(",",":"))+"\n").encode()
    report=evaluate(frame,financial,calendar,index,quotes)
    report.update({"source_raw_sha256":sha(raw),"sample_ids_sha256":frame["selected_ids_sha256"],
                   "original_2025_rule_sha256":spec_sha,
                   "financial_source_page_sha256":financial_receipts,
                   "financial_source_total_rows":all_financial_rows,
                   "captured_at_utc":datetime.now(timezone.utc).isoformat()})
    folder.mkdir(parents=True)
    (folder/"RESULT.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    with (folder/"RAW_SOURCE.json.gz").open("wb") as file:
        file.write(gzip.compress(raw,mtime=0))
    print(json.dumps({key:report[key] for key in
        ("cohort_size","entry_eligible_count","selected_count",
         "comparison_day_group_count","complete_comparison_day_group_count",
         "selected_outcome_coverage","primary","strategy_validated","live_buy_eligibility")},
         ensure_ascii=False),flush=True)

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--out",type=Path,required=True)
    args=p.parse_args()
    import baostock
    capture(baostock,args.out)

if __name__=="__main__":
    main()
