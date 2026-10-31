#!/usr/bin/env python3
"""Retrospective FY2024 disclosure -> 2025 20-session stock/index price study.

Fix the 128-issuer membership and disclosure source BEFORE reading market returns.
Output preserves each failure, source data hashes, unadjusted price-only and
later-vintage adjusted sensitivity. Not original-time PIT, total return, a
pre-registered alpha backtest, or a live BUY permission.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from datetime import date, datetime, timezone
from pathlib import Path
from statistics import mean

from v29_historical_universe_sampling import build_frame
from v29_2025_filing_to_return_case import (
    records, validated_calendar, validated_bars, finite_price, first_signal_and_exit,
)

ROOT = Path(__file__).resolve().parents[1]
PDF_AUDIT = ROOT / "research/v29_original_fy2024_content_audit/PDF_CONTENT_AUDIT_128.json"
START, END = "2025-02-01", "2025-06-30"
HORIZON, COST = 20, 0.003
BAR_FIELDS = "date,code,close,adjustflag,tradestatus,isST,volume,amount"
INDEX_FIELDS = "date,code,close"
SCHEMA = "V29_FY2024_FILING_128_RETROSPECTIVE_20_SESSION_PRICE_PATH_V1"

def digest(raw):
    return hashlib.sha256(raw).hexdigest()

def source_issuers(pdf_audit_path=PDF_AUDIT):
    frame = build_frame()
    blob = Path(pdf_audit_path).read_bytes()
    audit = json.loads(blob)
    if (audit.get("schema") != "V29_2025_FY2024_ORIGINAL_PDF_CONTENT_AUDIT_128_V1"
        or audit.get("requested_count") != 128
        or audit.get("frozen_sample_sha256") != frame["selected_ids_sha256"]
        or len(audit.get("rows", [])) != 128):
        raise ValueError("FROZEN_128_PDF_SOURCE_MISMATCH")
    rows = audit["rows"]
    if [r["security_id"] for r in rows] != frame["selected_ids"]:
        raise ValueError("OUTCOME_BLIND_SAMPLE_ORDER_OR_MEMBERSHIP_CHANGED")
    for r in rows:
        d = r.get("source_announcement_day")
        if not d or date.fromisoformat(d) <= date(2024, 12, 31):
            raise ValueError("DISCLOSURE_AFTER_FISCAL_PERIOD_NOT_VERIFIED")
        if d not in r["vendor_notice_dates"]:
            raise ValueError("ORIGINAL_AND_VENDOR_DISCLOSURE_DATE_CONFLICT")
        if not r.get("pdf_sha256"):
            raise ValueError("ORIGINAL_SOURCE_HASH_UNAVAILABLE")
    return rows, digest(blob), frame["selected_ids_sha256"]

def code_for(sid):
    exchange, code = sid.split(":")
    return ("sh." if exchange == "SSE" else "sz.") + code

def one_price_case(issuer, sessions, benchmark, quote):
    sid = issuer["security_id"]
    item = {
        "security_id": sid,
        "financial_report_period_end": "2024-12-31",
        "original_report_publication_day": issuer["source_announcement_day"],
        "original_report_pdf_sha256_2026_capture": issuer["pdf_sha256"],
        "original_report_content_identity_pass": issuer["full_report_identity_pass"],
        "financial_amount_text_present_not_semantic_certification":
            issuer["both_financial_amounts_have_text_matches"],
        "historical_financial_PIT_certified": False,
        "signal_or_buy_eligibility": "NOT_AUTHORIZED",
        "price_only_not_total_return": True,
    }
    def fail(reason):
        return {**item, "price_observation_status": reason,
                "comparison_eligible": False}
    try:
        entry, exit_day = first_signal_and_exit(
            issuer["source_announcement_day"], sessions, HORIZON)
    except ValueError:
        return fail("INSUFFICIENT_POST_DISCLOSURE_CALENDAR")
    item.update({
        "entry_session": entry.isoformat(),
        "exit_session": exit_day.isoformat(),
        "observation_horizon_sessions_including_entry": HORIZON,
    })
    if quote.get("error"):
        return {**fail("SOURCE_QUERY_FAILED"),"source_failure":quote["error"]}
    ident=code_for(sid)
    try:
        raw=validated_bars(quote["unadjusted"],ident,set(sessions),"3")
        adj=validated_bars(quote["forward_adjusted_2026_vintage"],ident,set(sessions),"2")
    except (ValueError,KeyError) as exc:
        return {**fail("PRICE_BAR_IDENTITY_OR_DUPLICATE_INVALID"),
                "integrity_reason":str(exc)[:150]}
    if entry not in raw:
        return fail("ENTRY_BAR_MISSING_NO_LATER_ENTRY_SUBSTITUTION")
    if exit_day not in raw:
        return fail("FIXED_HORIZON_EXIT_BAR_MISSING_NO_LATER_EXIT_SUBSTITUTION")
    e,x=raw[entry],raw[exit_day]
    if e["tradestatus"] != "1":
        return fail("ENTRY_SESSION_NOT_TRADEABLE")
    if e["isST"] == "1":
        return fail("ENTRY_SESSION_ST_FLAGGED")
    if x["tradestatus"] != "1":
        return fail("EXIT_SESSION_NOT_TRADEABLE")
    if x["isST"] == "1":
        return fail("EXIT_SESSION_ST_FLAGGED")
    if entry not in benchmark or exit_day not in benchmark:
        return fail("BENCHMARK_ENDPOINT_MISSING")
    try:
        price0,price1=finite_price(e["close"]),finite_price(x["close"])
        bench0,bench1=finite_price(benchmark[entry]["close"]),finite_price(benchmark[exit_day]["close"])
    except ValueError:
        return fail("NON_POSITIVE_OR_INVALID_ENDPOINT_PRICE")
    stock_price_only=price1/price0-1
    benchmark_price_only=bench1/bench0-1
    item.update({
        "first_post_disclosure_close_unadjusted":price0,
        "twentieth_session_close_unadjusted":price1,
        "stock_price_only_return":stock_price_only,
        "csi300_price_index_return":benchmark_price_only,
        "price_only_excess_after_30bps_vs_zero_cost_index":
            stock_price_only-COST-benchmark_price_only,
        "round_trip_cost_assumption":COST,
        "close_to_close_is_not_verified_executable_fill":True,
        "cash_dividends_and_corporate_action_economic_return_certified":False,
    })
    if entry in adj and exit_day in adj:
        try:
            adj_return=finite_price(adj[exit_day]["close"])/finite_price(adj[entry]["close"])-1
        except ValueError:
            return {**item, "price_observation_status":"RAW_COMPLETE_ADJUSTED_PRICE_INVALID",
                    "comparison_eligible":True,
                    "later_vintage_forward_adjusted_return":None}
        item.update({
            "later_vintage_forward_adjusted_return":adj_return,
            "price_method_gap_percentage_points":100*(adj_return-stock_price_only),
            "adjusted_prices_2026_vintage_not_asof_2025_certified":True,
        })
        status="PRICE_ENDPOINTS_COMPLETE_WITH_ADJUSTED_SENSITIVITY"
    else:
        item["later_vintage_forward_adjusted_return"]=None
        status="RAW_ENDPOINTS_COMPLETE_ADJUSTED_ENDPOINT_UNAVAILABLE"
    item.update({"price_observation_status":status,
                 "comparison_eligible":True})
    return item

def evaluate(issuers, calendar, index_rows, market):
    sessions=validated_calendar(calendar)
    benchmark=validated_bars(index_rows,"sh.000300",set(sessions))
    output=[]
    for issuer in issuers:
        sid=issuer["security_id"]
        output.append(one_price_case(issuer,sessions,benchmark,market.get(sid,{"error":"NO_QUERY_RESULT"})))
    if len(output)!=128 or len({r["security_id"] for r in output})!=128:
        raise ValueError("SAMPLE_CARDINALITY_VIOLATION")
    valid=[r for r in output if r["comparison_eligible"]]
    statuses={}
    for r in output:
        status=r["price_observation_status"]
        statuses[status]=statuses.get(status,0)+1
    return {
        "schema":SCHEMA,
        "sample_size":len(output),
        "price_comparison_count":len(valid),
        "missing_or_nontradeable_count":len(output)-len(valid),
        "outcome_status_counts":statuses,
        "mean_conditional_price_only_net_excess_vs_csi300":(
            mean(r["price_only_excess_after_30bps_vs_zero_cost_index"] for r in valid)
            if valid else None),
        "median_or_mean_not_an_alpha_strategy_effectiveness_estimate":True,
        "study_cohort_selected_in_2026_after_2025_returns_were_known":True,
        "selection_rule_not_reselected_after_outcomes":True,
        "historical_prices_retrieved_after_event_not_contemporaneous":True,
        "csi300_reference":"CSI300_PRICE_INDEX_NOT_TOTAL_RETURN",
        "round_trip_cost_assumption":COST,
        "complete_dividend_adjusted_economic_return":False,
        "unseen_OOS_validated":False,
        "strategy_validated":False,
        "live_buy_eligibility":"NOT_AUTHORIZED",
        "rows":output,
    }

def collect(bs, out):
    if out.exists():
        raise ValueError("NO_OVERWRITE_OF_FROZEN_PRICE_CAPTURE")
    issuers,source_hash,sample_hash=source_issuers()
    login=bs.login()
    if login.error_code!="0":
        raise ValueError("BAOSTOCK_LOGIN_FAILED:"+str(login.error_msg))
    market={}
    try:
        calendar=records(bs.query_trade_dates(start_date=START,end_date=END))
        index=records(bs.query_history_k_data_plus(
            "sh.000300",INDEX_FIELDS,start_date=START,end_date=END,
            frequency="d",adjustflag="3"))
        for i,r in enumerate(issuers,1):
            sid=r["security_id"]
            code=code_for(sid)
            try:
                raw=records(bs.query_history_k_data_plus(
                    code,BAR_FIELDS,start_date=START,end_date=END,
                    frequency="d",adjustflag="3"))
                adj=records(bs.query_history_k_data_plus(
                    code,BAR_FIELDS,start_date=START,end_date=END,
                    frequency="d",adjustflag="2"))
                market[sid]={"unadjusted":raw,"forward_adjusted_2026_vintage":adj}
                print(f"SOURCE {i:03d}/128 {sid} RAW={len(raw)} ADJ={len(adj)}",flush=True)
            except (ValueError,OSError) as exc:
                market[sid]={"error":type(exc).__name__+":"+str(exc)[:140]}
                print(f"SOURCE {i:03d}/128 {sid} QUERY_ERROR",flush=True)
    finally:
        bs.logout()
    payload={"calendar":calendar,"index":index,"market":market,
             "bar_fields":BAR_FIELDS,"index_fields":INDEX_FIELDS,
             "range_start":START,"range_end":END,"vendor":"baostock==0.9.4",
             "frozen_sample_sha256":sample_hash,
             "pdf_source_manifest_sha256":source_hash}
    raw=(json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(",",":"))+"\n").encode()
    report=evaluate(issuers,calendar,index,market)
    report.update({
        "capture_time_utc":datetime.now(timezone.utc).isoformat(),
        "frozen_sample_sha256":sample_hash,
        "pdf_source_manifest_sha256":source_hash,
        "raw_vendor_snapshot_sha256":digest(raw),
        "vendor":"BaoStock_free_0.9.4",
        "raw_vendor_quote_bar_window":[START,END],
        "raw_vendor_adjustflags":["3_UNADJUSTED","2_FORWARD_ADJUSTED_2026_VINTAGE"],
        "source_failures_preserved":sum(bool(x.get("error")) for x in market.values()),
    })
    out.mkdir(parents=True)
    with (out/"RAW_BAOSTOCK_QUOTES_AND_CALENDAR.json.gz").open("wb") as fh:
        with gzip.GzipFile(fileobj=fh,mode="wb",mtime=0) as gz:
            gz.write(raw)
    (out/"PRICE_PATH_128.json").write_text(
        json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({k:v for k,v in report.items() if k!="rows"},ensure_ascii=False),flush=True)
    return report

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--out",type=Path,required=True)
    args=p.parse_args()
    import baostock
    collect(baostock,args.out)

if __name__=="__main__":
    main()
