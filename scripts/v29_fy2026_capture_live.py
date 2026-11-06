#!/usr/bin/env python3
"""One-time future FY26 free-source capture, with finance-first quote economy.

Reuses the existing two Eastmoney raw collectors, BaoStock exchange calendar,
as-of full-stock listing and ONE raw bar only for financially plausible names.
No scheduled job; don't attempt before FY26 reports or after first entry open.
All market names are retained, even without a financial report or price.
"""
from __future__ import annotations
import argparse
import json
from datetime import datetime, date
from pathlib import Path
from zoneinfo import ZoneInfo

from v29_growth_candidate_snapshot import collect as collect_summary
from v29_growth_core_earnings import collect as collect_core
from v29_2025_filing_to_return_case import records
from v29_forward122_preentry_source_check import baostock_code
from v29_fy2026_full_source_frame import build, canonical, code_to_security, validate_market
from v29_fy2026_next_vintage_selector import plan_source, record_filter, select

CN=ZoneInfo("Asia/Shanghai")
FIELD="date,code,close,volume,tradestatus,isST,adjustflag"
RAW_PAIRS=(("annual-summary","annual"),("q3-summary","q3"),("annual-core","annual_core"),("q3-core","q3_core"))

def capture(bs,now,summary_collector=collect_summary,core_collector=collect_core,official_calendar=None,clock=None):
    if not isinstance(now,datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("AWARE_CAPTURE_TIME_REQUIRED")
    local=now.astimezone(CN)
    if local.date()<date(2027,5,1):
        raise ValueError("FY2026_ANNUAL_DATA_NOT_YET_ELIGIBLE")
    plan,_=plan_source()
    # Keep raw pages, not only the existing positive-growth candidate summaries.
    _,annual=summary_collector("2026-12-31",notice_before="2027-05-01")
    _,q3=summary_collector("2026-09-30",notice_before="2026-11-01")
    annual_core=core_collector("2026-12-31","2027-05-01")
    q3_core=core_collector("2026-09-30","2026-11-01")
    login=bs.login()
    if login.error_code!="0":
        raise ValueError("BAOSTOCK_LOGIN_FAILED")
    try:
        calendar=records(bs.query_trade_dates(start_date="2027-04-25",end_date="2027-05-12"))
        trading=[r["calendar_date"] for r in calendar if r["is_trading_day"]=="1"]
        ref=max((d for d in trading if d<="2027-04-30"),default=None)
        if ref is None:
            raise ValueError("FY26_REFERENCE_SESSION_NOT_FOUND")
        following=min((d for d in trading if d>"2027-04-30"),default=None)
        if following is None:
            raise ValueError("FY26_FIRST_SESSION_NOT_FOUND")
        if local>=datetime.fromisoformat(following+"T09:30:00+08:00"):
            raise ValueError("FY26_SOURCE_NOT_PRE_ENTRY")
        listed=records(bs.query_all_stock(day=ref))
        verified=False
        if official_calendar is not None:
            # The official source proof must be obtained separately from the
            # vendor itself; do not infer official verification from BaoStock.
            if (official_calendar.get("source_type")!="OFFICIAL_EXCHANGE_SCHEDULE"
                or official_calendar.get("first_trading_session")!=following
                or official_calendar.get("reference_trading_session")!=ref
                or not official_calendar.get("source_url","").startswith(
                    ("https://www.sse.com.cn/","https://www.szse.cn/"))):
                raise ValueError("OFFICIAL_EXCHANGE_SCHEDULE_PROOF_MISMATCH")
            verified=True
        market={"schema":"V29_FY2026_MARKET_REFERENCE_SOURCE_V1",
                "official_calendar_verified":verified,
                "calendar":calendar,"all_stock":listed,
                "reference_bars":[],"market_quote_errors":{},
                "provider":"BAOSTOCK_FREE_RESEARCH_SOURCE",
                "official_schedule_record":official_calendar,
                "requested_as_of_reference":ref}
        # Validate the complete listed stock denominator, then financially
        # prefilter. Absence of price is a reason to query, not a fake price.
        preliminary=build(annual,q3,annual_core,q3_core,market,local.isoformat())
        finance_candidates=[]
        for row in preliminary["rows"]:
            reasons,_=record_filter(row,plan["selection"],ref)
            if set(reasons)=={"REFERENCE_CLOSE_MISSING","ST_OR_ST_STATUS_UNVERIFIED"}:
                finance_candidates.append(row["security_id"])
        market["quote_requested_ids"]=finance_candidates
        for sid in finance_candidates:
            try:
                bars=records(bs.query_history_k_data_plus(
                    baostock_code(sid),FIELD,start_date=ref,end_date=ref,
                    frequency="d",adjustflag="3"))
                if len(bars)>1:
                    raise ValueError("DUPLICATE_ASOF_QUOTE")
                if bars:
                    market["reference_bars"].append(bars[0])
                else:
                    market["market_quote_errors"][sid]="REFERENCE_QUOTE_UNAVAILABLE"
            except (ValueError,KeyError,OSError) as e:
                market["market_quote_errors"][sid]=type(e).__name__+":"+str(e)[:100]
    finally:
        bs.logout()
    completed=(clock() if clock else datetime.now(CN)).astimezone(CN)
    if completed>=datetime.fromisoformat(following+"T09:30:00+08:00"):
        raise ValueError("FY26_SOURCE_CAPTURE_COMPLETED_AFTER_ENTRY_OPEN")
    frame=build(annual,q3,annual_core,q3_core,market,completed.isoformat())
    frame["preliminary_financial_qualification_count"]=len(finance_candidates)
    frame["market_source_unverified_original_exchange_filings"]=True
    # Never block an entirely automated, read-only candidate queue solely
    # for absent manual exchange calendar proof. Keep the provisional result
    # explicitly below officially verified selection and always NOT_AUTHORIZED.
    candidate=select(frame,completed,
                     allow_vendor_calendar_research_only=not frame["market_calendar_verified"])
    return frame,candidate,market,{"annual":annual,"q3":q3,
                                  "annual_core":annual_core,"q3_core":q3_core}

def store(out,frame,candidate,market,pages):
    out=Path(out)
    if out.exists():
        raise ValueError("SOURCE_CAPTURE_DESTINATION_ALREADY_EXISTS")
    out.mkdir(parents=True)
    for folder,key in RAW_PAIRS:
        p=out/folder
        p.mkdir()
        for i,b in enumerate(pages[key],1):
            (p/f"page-{i:03}.json").write_bytes(b)
    (out/"MARKET_REFERENCE_SOURCE.json").write_bytes(canonical(market))
    (out/"NORMALIZED_ALL_A_FRAME.json").write_text(
        json.dumps(frame,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    if candidate is not None:
        (out/"FROZEN_EIGHT_RESEARCH_ONLY.json").write_text(
            json.dumps(candidate,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--out-dir",type=Path,required=True)
    parser.add_argument("--official-calendar",type=Path)
    args=parser.parse_args()
    if args.out_dir.exists():
        raise ValueError("NO_OVERWRITE_FUTURE_FINANCIAL_EVIDENCE")
    import baostock
    official=json.loads(args.official_calendar.read_text()) if args.official_calendar else None
    frame,pick,market,pages=capture(baostock,datetime.now(CN),official_calendar=official)
    store(args.out_dir,frame,pick,market,pages)
    print(json.dumps({"all_A":frame["universe_source_count"],
        "prequalified_for_price_capture":frame["preliminary_financial_qualification_count"],
        "reference_quotes_collected":len(market["reference_bars"]),
        "source_missing":frame["all_source_counts"]["missing_by_field_source"],
        "official_calendar_verified":frame["market_calendar_verified"],
        "selected_count":pick["selected_count"] if pick else None,
        "live_buy_eligibility":"NOT_AUTHORIZED"},ensure_ascii=False))

if __name__=="__main__":
    main()
