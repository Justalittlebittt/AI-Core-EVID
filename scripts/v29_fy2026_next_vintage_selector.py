#!/usr/bin/env python3
"""Pre-disclosure frozen FY2026 A-share candidate selector, research only.

This is the FY-vs-Q3 adapted hypothesis, NOT the 2026 Q3-vs-H1 predictor
and NOT a live trading authorization. The existing financial capture tools
supply source pages; this module performs one pure, future-vintage selection.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from datetime import date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT=Path(__file__).resolve().parents[1]
PLAN=ROOT/"research/V2.9_FY2026_NEW_VINTAGE_ADAPTED_GROWTH_PREOUTCOME_20261105.json"
FROZEN_BLOB_SHA="6658fd16f481dbc13e25b256233a9fa10ebf7cf5"
CN=ZoneInfo("Asia/Shanghai")
SHA=re.compile(r"^[0-9a-f]{64}$")
IDENTITY=re.compile(r"^(SSE:(?:60[0135]|68[89])\d{3}|SZSE:(?:00[0-3]|30[01])\d{3})$")
SELECTOR="V29_FY2026_ANNUAL_VS_Q3_ADAPTED_SELECTION_V1"

def plan_source(root=ROOT):
    blob=(Path(root)/PLAN.relative_to(ROOT)).read_bytes()
    h=hashlib.sha1(b"blob "+str(len(blob)).encode()+b"\0"+blob).hexdigest()
    if h!=FROZEN_BLOB_SHA:
        raise ValueError("FUTURE_FINANCIAL_SELECTOR_PREOUTCOME_PLAN_CHANGED")
    p=json.loads(blob)
    if (p["registered_on"]!="2026-11-05"
        or p["selection"]["selected_count"]!=8
        or p["prospective_evaluation"]["transaction_cost_roundtrip_fraction"]!=0.003
        or p["strict_interpretation"]["equity_trade_eligibility"]!="NOT_AUTHORIZED"):
        raise ValueError("FUTURE_STUDY_RULES_CHANGED")
    return p,h

def finite_number(value):
    if type(value) not in (int,float) or not math.isfinite(value):
        return None
    return float(value)

def signed(v, positive=True):
    n=finite_number(v)
    return n is not None and (n>0 if positive else n>=0)

def record_filter(row,rule,reference_day):
    """One issuer's complete, pre-entry annual/Q3 source fields."""
    reasons=[]
    sid=row.get("security_id")
    if not isinstance(sid,str) or not IDENTITY.fullmatch(sid):
        raise ValueError("INVALID_MAINLAND_SECURITY_ID")
    if (row.get("annual_period")!="2026-12-31"
        or row.get("q3_period")!="2026-09-30"):
        raise ValueError("WRONG_REPORT_PERIOD")
    annual_notice=row.get("annual_disclosure_date")
    q3_notice=row.get("q3_disclosure_date")
    if not annual_notice or not q3_notice:
        reasons.append("ANNUAL_OR_Q3_DISCLOSURE_MISSING")
        return reasons,None
    if date.fromisoformat(annual_notice)>date(2027,4,30):
        reasons.append("ANNUAL_REPORT_DISCLOSED_AFTER_CUTOFF")
    if date.fromisoformat(q3_notice)>date(2026,10,31):
        reasons.append("Q3_DISCLOSURE_AFTER_LEGAL_PERIOD")
    if row.get("reference_close_session")!=reference_day:
        reasons.append("REFERENCE_PRICE_SESSION_CHANGED")
    numbers={
        key:finite_number(row.get(key))
        for key in (
            "annual_revenue_yoy_pct","q3_ytd_revenue_yoy_pct",
            "annual_parent_profit_yuan","annual_parent_profit_yoy_pct",
            "annual_deducted_parent_profit_yuan",
            "q3_ytd_deducted_parent_profit_yuan","annual_roe_pct",
            "annual_cfo_per_share_yuan","annual_gross_margin_pct",
            "q3_ytd_gross_margin_pct","annual_nonrecurring_parent_profit_yuan"
        )
    }
    if any(v is None for v in numbers.values()):
        reasons.append("MANDATORY_FUNDAMENTAL_MISSING")
        return reasons,None
    x=numbers
    accel=x["annual_revenue_yoy_pct"]-x["q3_ytd_revenue_yoy_pct"]
    q4_core=x["annual_deducted_parent_profit_yuan"]-x["q3_ytd_deducted_parent_profit_yuan"]
    if not (rule["annual_revenue_yoy_pct_min_exclusive"]<x["annual_revenue_yoy_pct"]
            <=rule["annual_revenue_yoy_pct_max_inclusive"]
            and x["q3_ytd_revenue_yoy_pct"]>rule["q3_ytd_revenue_yoy_pct_min_exclusive"]
            and accel>=rule["annual_minus_q3_ytd_revenue_yoy_acceleration_pp_min_inclusive"]):
        reasons.append("REVENUE_GROWTH_ACCELERATION_RULE_FAILED")
    # The sealed FY2026 rule requires *annual* positive parent-profit growth,
    # not Q3 parent-profit growth. Q3 parent-profit YoY is NOT preregistered;
    # enforcing it would silently alter the candidate population.
    if not (x["annual_parent_profit_yuan"]>rule["annual_parent_profit_yuan_min_exclusive"]
            and x["annual_parent_profit_yoy_pct"]>rule["annual_parent_profit_yoy_pct_min_exclusive"]
            and x["annual_deducted_parent_profit_yuan"]>rule["annual_deducted_parent_profit_yuan_min_exclusive"]
            and q4_core>rule["standalone_q4_deducted_parent_profit_yuan_min_exclusive"]):
        reasons.append("PARENT_OR_STANDALONE_Q4_CORE_PROFIT_RULE_FAILED")
    if not (x["annual_roe_pct"]>=rule["annual_weighted_roe_pct_min_inclusive"]
            and x["annual_cfo_per_share_yuan"]>rule["annual_cfo_per_share_yuan_min_exclusive"]):
        reasons.append("ROE_OR_CASHFLOW_RULE_FAILED")
    if x["annual_gross_margin_pct"]<x["q3_ytd_gross_margin_pct"]:
        reasons.append("ANNUAL_GROSS_MARGIN_DECLINE")
    if (x["annual_parent_profit_yuan"]<=0
            or abs(x["annual_nonrecurring_parent_profit_yuan"])/x["annual_parent_profit_yuan"]
               >rule["annual_nonrecurring_share_of_parent_profit_max_inclusive"]):
        reasons.append("NONRECURRING_PROFIT_EXCESS")
    if row.get("is_st_at_reference_session") is not False:
        reasons.append("ST_OR_ST_STATUS_UNVERIFIED")
    shares=200 if sid.startswith("SSE:688") else 100
    price=finite_number(row.get("reference_close_cny"))
    if price is None:
        reasons.append("REFERENCE_CLOSE_MISSING")
        notional=None
    else:
        notional=round(price*shares,2)
        if notional>rule["maximum_minimum_exchange_lot_notional_cny"] or notional<=0:
            reasons.append("MINIMUM_EXCHANGE_LOT_OUT_OF_BUDGET")
    if reasons:
        return reasons,None
    return [],{
        "security_id":sid,
        "annual_revenue_yoy_pct":x["annual_revenue_yoy_pct"],
        "q3_ytd_revenue_yoy_pct":x["q3_ytd_revenue_yoy_pct"],
        "annual_revenue_acceleration_pp":accel,
        "annual_roe_pct":x["annual_roe_pct"],
        "standalone_q4_deducted_profit_yuan":q4_core,
        "minimum_lot_shares":shares,
        "pre_entry_reference_notional_cny":notional,
        "reference_close_session":reference_day,
        "annual_disclosure_date":row["annual_disclosure_date"],
        "research_only":True,
        "original_filing_verified":row.get("source_original_filing_verified") is True
    }

def select(snapshot,now,root=ROOT,*,allow_vendor_calendar_research_only=False):
    p,plan_git_sha=plan_source(root)
    if not isinstance(now,datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("AWARE_DECISION_CLOCK_REQUIRED")
    ts=now.astimezone(CN)
    entry_day=date.fromisoformat(snapshot["first_trading_session_after_cutoff"])
    captured=datetime.fromisoformat(snapshot["captured_at"])
    if captured.tzinfo is None or captured.utcoffset() is None:
        raise ValueError("AWARE_SOURCE_TIMESTAMP_REQUIRED")
    captured=captured.astimezone(CN)
    first_open=datetime.combine(entry_day,time(9,30),tzinfo=CN)
    if not (date(2027,5,1)<=ts.date()<=entry_day
            and datetime(2027,5,1,0,0,tzinfo=CN)<=captured<=ts<first_open):
        raise ValueError("NEW_REPORT_SOURCE_MUST_BE_CAPTURED_AND_LOCKED_BEFORE_ENTRY")
    if (snapshot.get("schema")!="V29_FY2026_NORMALIZED_ALL_A_SOURCE_FRAME_V1"
        or snapshot.get("report_period")!="2026-12-31"
        or snapshot.get("comparison_period")!="2026-09-30"
        or snapshot.get("financial_coverage_status")!="COMPLETE_VENDOR_ALL_A_CROSS_SECTION"):
        raise ValueError("COMPLETE_EXCHANGE_SOURCE_OR_CALENDAR_REQUIRED")
    calendar_certified=snapshot.get("market_calendar_verified") is True
    if not calendar_certified and (
            not allow_vendor_calendar_research_only
            or snapshot.get("market_calendar_provenance")!="BAOSTOCK_VENDOR_CALENDAR_ONLY"):
        raise ValueError("COMPLETE_EXCHANGE_SOURCE_OR_CALENDAR_REQUIRED")
    # A vendor-only market calendar can produce a preliminary *research*
    # ranking before first open; it cannot claim official timing or BUY.

    reference_day=snapshot.get("reference_close_session")
    if not isinstance(reference_day,str) or not date.fromisoformat(reference_day)<=date(2027,4,30) or date.fromisoformat(reference_day)>=entry_day:
        raise ValueError("REFERENCE_CLOSE_MUST_PRECEDE_NEW_ENTRY")
    receipts=snapshot.get("raw_source_sha256")
    if (not isinstance(receipts,dict)
        or set(receipts)!={"annual","q3","reference_prices","calendar"}
        or any(not isinstance(v,str) or not SHA.fullmatch(v) for v in receipts.values())):
        raise ValueError("RAW_SOURCE_RECEIPTS_REQUIRED")
    rows=snapshot.get("rows")
    if not isinstance(rows,list) or len(rows)!=snapshot.get("universe_source_count") or not rows:
        raise ValueError("ALL_SOURCE_ISSUER_DENOMINATOR_NOT_COMPLETE")
    ids=[r.get("security_id") for r in rows]
    if len(ids)!=len(set(ids)):
        raise ValueError("DUPLICATE_SOURCE_ISSUER")
    rule=p["selection"]
    eligible=[]
    reason_counts={}
    for row in rows:
        reasons,candidate=record_filter(row,rule,reference_day)
        for reason in reasons:
            reason_counts[reason]=reason_counts.get(reason,0)+1
        if candidate is not None:
            eligible.append(candidate)
    eligible.sort(key=lambda r:(-r["annual_roe_pct"],-r["annual_revenue_acceleration_pp"],r["security_id"]))
    full=len(eligible)>=rule["selected_count"]
    chosen=eligible[:rule["selected_count"]] if full else []
    # Reuse the actual original frozen cohort, not caller-provided overlap IDs.
    from v29_growth_forward_cohort import load_registered
    _,old_names,_=load_registered()
    previous=set(old_names)
    result={
        "schema":SELECTOR,
        "registered_plan_git_blob_sha":plan_git_sha,
        "captured_at":captured.isoformat(),
        "source_provenance":receipts,
        "historical_q3_original_vendor_vintage":snapshot.get("q3_original_source_vintage"),
        "historical_q3_source_certified_by_original_archive":bool(
            snapshot.get("q3_original_source_vintage",{}).get("identity")==
            "2026-10-30_DISCLOSURE_CUTOFF_2026-10-29_ORIGINAL_VENDOR"),
        "pre_entry_reference_session":reference_day,
        "first_eligible_trading_session":entry_day.isoformat(),
        "total_source_universe":len(rows),
        "total_rule_eligible":len(eligible),
        "selected_count":len(chosen),
        "selected_in_frozen_ranking_order":chosen,
        "not_selected_due_to_insufficient_eligibles":not full,
        "source_exclusion_reason_counts":reason_counts,
        "overlap_with_original_2026q3_122":sum(r["security_id"] in previous for r in chosen),
        "selected_original_filing_verified_count":sum(r["original_filing_verified"] for r in chosen),
        "all_selected_original_filings_verified":bool(chosen) and all(r["original_filing_verified"] for r in chosen),
        "vendor_vintage_not_independent_original_release_pit_certification":True,
        "calendar_officially_verified":calendar_certified,
        "calendar_pending_official_verification":not calendar_certified,
        "preliminary_vendor_calendar_only":not calendar_certified,
        "separate_fy_adapted_hypothesis_not_q3_replication":True,
        "actual_buy_fills_verified":False,
        "strategy_validated":False,
        "live_buy_eligibility":"NOT_AUTHORIZED",
        "status":("FROZEN_NEW_REPORT_CANDIDATES_RESEARCH_ONLY" if calendar_certified
                  else "PROVISIONAL_VENDOR_CALENDAR_RESEARCH_ONLY") if full
                  else "INSUFFICIENT_NO_EIGHT_NO_THRESHOLD_RELAXATION"
    }
    return result

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--source",required=True,type=Path)
    ap.add_argument("--out",required=True,type=Path)
    args=ap.parse_args()
    if args.out.exists():
        raise ValueError("NO_OVERWRITE_NEW_VINTAGE_SELECTION")
    # Do not fetch future annual data or future returns: upstream capture owns
    # official filings, same-vintage metadata and source population coverage.
    now=datetime.now(CN)
    if now<datetime(2027,5,1,tzinfo=CN):
        raise SystemExit("FY2026_ANNUAL_REPORTS_NOT_YET_MATURE")
    result=select(json.loads(args.source.read_text(encoding="utf-8")),now)
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"status":result["status"],"selected_count":result["selected_count"],
                      "trade_authorized":False},ensure_ascii=False))

if __name__=="__main__":
    main()
