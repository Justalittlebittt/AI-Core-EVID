#!/usr/bin/env python3
"""Historical 2025 post-annual-report two-name prices. Descriptive NOT OOS alpha.

2024 reported annual numbers were transcribed from the company's original
2025 published full annual report. BaoStock prices are retrospectively queried.
2025 outcome windows were already observable when study was created in 2026.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from datetime import date, datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
INPUT=ROOT/"research/V2.9_2025_TWO_ISSUER_FILING_INPUTS.json"
BAR_FIELDS="date,code,close,adjustflag,tradestatus,volume,amount,isST"
INDEX_FIELDS="date,code,close"
START="2025-04-01"
END="2025-06-30"


def finite_price(v):
    try: n=float(v)
    except (ValueError,TypeError): raise ValueError("INVALID_PRICE")
    if not math.isfinite(n) or n<=0: raise ValueError("INVALID_PRICE")
    return n


def load_inputs(path=INPUT):
    blob=Path(path).read_bytes()
    obj=json.loads(blob)
    if obj.get("schema")!="AI_CORE_EVID_V29_HISTORICAL_2025_TWO_ISSUER_CASE_INPUT_V1":
        raise ValueError("WRONG_FINANCIAL_INPUT_SCHEMA")
    if obj["holding_period_sessions_including_entry"]!=20 or obj["round_trip_cost_assumption"]!=.003:
        raise ValueError("PREDECLARED_HORIZON_OR_COST_CHANGED")
    companies=obj["issuers"]
    if len(companies)!=2 or {x["canonical_id"] for x in companies}!={"SSE:688002","SZSE:300408"}:
        raise ValueError("COMPANY_SET_CHANGED")
    for x in companies:
        if not date.fromisoformat(x["financial_report_end"])<date.fromisoformat(x["published_on"]):
            raise ValueError("INVALID_DISCLOSURE_CHRONOLOGY")
        for metric in ("revenue","deduct_parent","cfo"):
            if (not isinstance(x[metric+"_2024_yuan"],(float,int)) or
                not isinstance(x[metric+"_2023_yuan"],(float,int))):
                raise ValueError("INVALID_ISSUER_ACCOUNT")
    return obj,hashlib.sha256(blob).hexdigest()


def records(rs):
    if rs.error_code!="0":raise ValueError("BAOSTOCK_FETCH_ERROR:"+str(rs.error_msg))
    out=[]
    while rs.next():
        out.append(dict(zip(rs.fields,rs.get_row_data())))
    return out


def validated_calendar(rows):
    days=[date.fromisoformat(x["calendar_date"]) for x in rows if x["is_trading_day"]=="1"]
    if days!=sorted(set(days)) or len(days)<40:
        raise ValueError("INVALID_HISTORICAL_EXCHANGE_CALENDAR")
    return days


def validated_bars(rows,code,allowed_sessions,expected_adjustflag=None):
    bars={}
    for x in rows:
        if x["code"]!=code:raise ValueError("HISTORICAL_SECURITY_IDENTITY_MISMATCH")
        d=date.fromisoformat(x["date"])
        if d not in allowed_sessions or d in bars:raise ValueError("BAR_OFF_CALENDAR_OR_DUPLICATE")
        if expected_adjustflag is not None and x["adjustflag"]!=expected_adjustflag:
            raise ValueError("UNEXPECTED_PRICE_ADJUSTMENT_FLAG")
        bars[d]=x
    return bars


def first_signal_and_exit(published_on,calendar,horizon):
    after=[d for d in calendar if d>date.fromisoformat(published_on)]
    if len(after)<horizon:
        raise ValueError("INSUFFICIENT_POST_DISCLOSURE_SESSIONS")
    return after[0],after[horizon-1]


def compute_report(inputs, calendar, quoted):
    sessions=validated_calendar(calendar)
    eligible=set(sessions)
    index=validated_bars(quoted["index"],"sh.000300",eligible)
    results=[]
    for x in inputs["issuers"]:
        sid=x["baostock"]
        entry,exit=first_signal_and_exit(x["published_on"],sessions,20)
        raw=validated_bars(quoted[sid]["unadjusted"],sid,eligible,"3")
        adj=validated_bars(quoted[sid]["forward_adjusted_2026_vintage"],sid,eligible,"2")
        if entry not in raw or exit not in raw or entry not in adj or exit not in adj:
            raise ValueError("ENTRY_OR_EXIT_PRICE_MISSING")
        e,z=raw[entry],raw[exit]
        if e["tradestatus"]!="1" or z["tradestatus"]!="1" or e["isST"]=="1" or z["isST"]=="1":
            raise ValueError("ENTRY_OR_EXIT_NOT_TRADEABLE")
        if entry not in index or exit not in index:
            raise ValueError("BENCHMARK_ENDPOINT_MISSING")
        raw_return=finite_price(z["close"])/finite_price(e["close"])-1
        adjusted=finite_price(adj[exit]["close"])/finite_price(adj[entry]["close"])-1
        benchmark_return=finite_price(index[exit]["close"])/finite_price(index[entry]["close"])-1
        results.append({
            "security_id":x["canonical_id"],"name":x["name"],
            "financial_period_end":x["financial_report_end"],
            "original_annual_report_date":x["published_on"],
            "entry_session":entry.isoformat(),"exit_session":exit.isoformat(),
            "calendar_sessions_count":20,
            "fy2024_revenue_yoy_pct":100*(x["revenue_2024_yuan"]/x["revenue_2023_yuan"]-1),
            "fy2024_deducted_parent_profit_yoy_pct":100*(x["deduct_parent_2024_yuan"]/x["deduct_parent_2023_yuan"]-1),
            "fy2024_operating_cfo_to_deduct_parent":x["cfo_2024_yuan"]/x["deduct_parent_2024_yuan"],
            "first_close_unadjusted":finite_price(e["close"]),
            "twentieth_close_unadjusted":finite_price(z["close"]),
            "raw_price_return":raw_return,
            "later_vintage_adjusted_price_return_sensitivity":adjusted,
            "price_return_method_gap_pp":100*(adjusted-raw_return),
            "csi300_price_index_return":benchmark_return,
            "price_only_net_excess_after_30bps":raw_return-.003-benchmark_return,
            "entry_vendor_pe_not_original_time_certified":None,
            "cash_dividend_and_corporate_action_economic_return_certified":False,
            "historical_PIT_quote_vintage_certified":False,
            "original_pdf_bytes_sealed":False,
            "not_an_unseen_oos_event":True,
            "buy_eligibility":"NOT_AUTHORIZED"
        })
    return {"schema":"V29_2025_TWO_ISSUER_POST_FILING_PRICE_CASE_V1",
            "observations":results,"n":len(results),
            "retrospective_capture_not_genuine_2025_pit":True,
            "benchmark":"CSI300_PRICE_INDEX_NOT_TR",
            "round_trip_cost_assumption":.003,
            "selection_after_inspecting_2026_results":True,
            "evidence_strength":"INSUFFICIENT","strategy_validated":False,
            "live_buy_eligibility":"NOT_AUTHORIZED"}


def capture(bs,out):
    if out.exists():raise ValueError("OUTPUT_ALREADY_EXISTS_NO_OVERWRITE")
    inputs,digest=load_inputs()
    status=bs.login()
    if status.error_code!="0":raise ValueError("BAOSTOCK_LOGIN_FAILED")
    try:
        cal=records(bs.query_trade_dates(start_date=START,end_date=END))
        market={"index":records(bs.query_history_k_data_plus("sh.000300",INDEX_FIELDS,
             start_date=START,end_date=END,frequency="d",adjustflag="3"))}
        for x in inputs["issuers"]:
            ident=x["baostock"]
            market[ident]={
                "unadjusted":records(bs.query_history_k_data_plus(ident,BAR_FIELDS,
                 start_date=START,end_date=END,frequency="d",adjustflag="3")),
                "forward_adjusted_2026_vintage":records(bs.query_history_k_data_plus(ident,BAR_FIELDS,
                 start_date=START,end_date=END,frequency="d",adjustflag="2"))
            }
    finally:
        bs.logout()
    raw=(json.dumps({"exchange_calendar":cal,"market":market},ensure_ascii=False,
                    sort_keys=True,separators=(",",":"))+"\n").encode()
    report=compute_report(inputs,cal,market)
    report["financial_source_sha256"]=digest
    report["retrospective_market_raw_sha256"]=hashlib.sha256(raw).hexdigest()
    report["captured_at_utc"]=datetime.now(timezone.utc).isoformat()
    out.mkdir(parents=True)
    (out/"raw_2025_market_and_calendar.json").write_bytes(raw)
    (out/"two_issuer_retrospective_case.json").write_text(
        json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return report


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--out-dir",type=Path,required=True)
    a=p.parse_args()
    import baostock
    print(json.dumps(capture(baostock,a.out_dir),ensure_ascii=False,indent=2))


if __name__=="__main__":
    main()
