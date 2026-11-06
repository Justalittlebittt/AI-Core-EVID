#!/usr/bin/env python3
"""Prospective FY2026-new-vintage eight-name paper entry/outcome; NO BUY.

Uses the already preregistered annual candidate frame, frozen before first
market open. It never revises the annual candidates or fills missing Q3 data.
Only observed close proxies, fixed 20 verified vendor sessions, and H00300 TR.
Missing official exchange filing/calendar certification remains explicit.
"""
from __future__ import annotations

import argparse
import base64
import gzip
import hashlib
import json
import math
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from zoneinfo import ZoneInfo

from v29_2025_filing_to_return_case import records
from v29_forward122_preentry_source_check import FIELDS, baostock_code
from v29_forward122_entry_close_capture import canonical_bytes, sha
from v29_forward122_20th_session_exit_capture import active_bar, bars_by_day, one_issuer
from v29_temporal_replication import index_fetch, read_index
from v29_fy2026_next_vintage_selector import select, plan_source

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/"research/V2.9_FY2026_NEW_VINTAGE_SOURCE_202705"
ENTRY=ROOT/"research/V2.9_FY2026_NEW_VINTAGE_PAPER_ENTRY/ENTRY_EIGHT.json"
ENTRY_RAW=ENTRY.parent/"RAW_ENTRY_EIGHT.json.gz"
CN=ZoneInfo("Asia/Shanghai")
N=8
COST=0.003

def complete_calendar(calendar,start,end):
    # Don't let missing market-day rows shift the twentieth exit.
    by_day={}
    for r in calendar:
        day=date.fromisoformat(r["calendar_date"])
        if day in by_day or r["is_trading_day"] not in ("0","1") or not start<=day<=end:
            raise ValueError("FUTURE_FINANCIAL_VENDOR_CALENDAR_INVALID")
        by_day[day]=r["is_trading_day"]
    days=[start+timedelta(days=k) for k in range((end-start).days+1)]
    if set(by_day)!=set(days):
        raise ValueError("FUTURE_FINANCIAL_VENDOR_CALENDAR_HAS_MISSING_DATE")
    return [d.isoformat() for d in days if by_day[d]=="1"]

def source_candidates(root=ROOT):
    root=Path(root)
    folder=root/SOURCE.relative_to(ROOT)
    frame_path=folder/"NORMALIZED_ALL_A_FRAME.json"
    if not frame_path.exists():
        raise ValueError("FUTURE_FINANCIAL_SOURCE_NOT_SEALED_BEFORE_ENTRY")
    frame_bytes=frame_path.read_bytes()
    frame=json.loads(frame_bytes)
    possibles=[folder/"FROZEN_EIGHT_RESEARCH_ONLY.json",
               folder/"PROVISIONAL_EIGHT_RESEARCH_ONLY.json"]
    present=[p for p in possibles if p.exists()]
    if len(present)!=1:
        raise ValueError("EXACTLY_ONE_PRE_ENTRY_FY8_SELECTION_REQUIRED")
    selected_bytes=present[0].read_bytes()
    selected=json.loads(selected_bytes)
    captured=datetime.fromisoformat(frame["captured_at"])
    entry_day=date.fromisoformat(frame["first_trading_session_after_cutoff"])
    if captured.tzinfo is None or captured.astimezone(CN)>=datetime.combine(entry_day,time(9,30),tzinfo=CN):
        raise ValueError("PRE_ENTRY_FINANCIAL_SOURCE_TIMING_UNPROVEN")
    if (frame.get("report_period")!="2026-12-31" or frame.get("comparison_period")!="2026-09-30"
        or frame.get("q3_original_source_vintage",{}).get("identity")!=
           "2026-10-30_DISCLOSURE_CUTOFF_2026-10-29_ORIGINAL_VENDOR"
        or selected.get("historical_q3_source_certified_by_original_archive") is not True
        or selected.get("historical_q3_original_vendor_vintage")!=frame.get("q3_original_source_vintage")
        or selected.get("live_buy_eligibility")!="NOT_AUTHORIZED"
        or selected.get("selected_count")!=N):
        raise ValueError("FUTURE_FINANCIAL_PRE_ENTRY_EIGHT_NOT_SOURCE_ELIGIBLE")
    # Recompute original rule against the original frozen full source frame.
    # "now" is the already-frozen timestamp, not today's later time.
    expected=select(frame,captured,allow_vendor_calendar_research_only=not frame["market_calendar_verified"])
    keys=("selected_count","selected_in_frozen_ranking_order","total_rule_eligible",
          "status","source_provenance","calendar_officially_verified")
    if any(selected.get(k)!=expected.get(k) for k in keys):
        raise ValueError("FUTURE_FINANCIAL_FROZEN_EIGHT_SELECTION_CHANGED")
    ids=[r["security_id"] for r in selected["selected_in_frozen_ranking_order"]]
    if len(ids)!=N or len(set(ids))!=N:
        raise ValueError("FUTURE_FINANCIAL_EIGHT_IDENTITIES_CHANGED")
    return frame,selected,ids,sha(frame_bytes),sha(selected_bytes)

def require_entry_clock(now,entry_day):
    if not isinstance(now,datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("FUTURE_FINANCIAL_AWARE_TIME_REQUIRED")
    local=now.astimezone(CN)
    if local.date()!=entry_day or local.time()<time(16,30):
        raise ValueError("FUTURE_FINANCIAL_ENTRY_ONLY_SAME_DAY_AFTER_CLOSE")
    return local

def query_bars(bs,ids,begin,end,entry_only=False):
    rows=[]
    for sid in ids:
        code=baostock_code(sid)
        item={"security_id":sid,"raw_unadjusted":[],"forward_adjusted":[]}
        for key,flag in (("raw_unadjusted","3"),("forward_adjusted","2")):
            try:
                item[key]=records(bs.query_history_k_data_plus(
                    code,FIELDS,start_date=begin,end_date=end,
                    frequency="d",adjustflag=flag))
            except (OSError,KeyError,ValueError) as exc:
                item["query_error_"+key]=type(exc).__name__+":"+str(exc)[:120]
        rows.append(item)
    return rows

def capture_entry(bs,now,source_loader=source_candidates,official_fetch=index_fetch):
    frame,selected,ids,frame_sha,selected_sha=source_loader()
    entry_day=date.fromisoformat(frame["first_trading_session_after_cutoff"])
    local=require_entry_clock(now,entry_day)
    ref=date.fromisoformat(frame["reference_close_session"])
    login=bs.login()
    if login.error_code!="0":
        raise ValueError("BAOSTOCK_ENTRY_LOGIN_FAILED")
    try:
        cal=records(bs.query_trade_dates(start_date=ref.isoformat(),end_date=entry_day.isoformat()))
        sessions=complete_calendar(cal,ref,entry_day)
        if sessions[-1]!=entry_day.isoformat() or any(d>ref.isoformat() for d in sessions[:-1]):
            raise ValueError("PRE_ENTRY_NEXT_EXCHANGE_SESSION_CHANGED")
        quotes=query_bars(bs,ids,entry_day.isoformat(),entry_day.isoformat())
    finally:
        bs.logout()
    receipts=[]
    for sid,source in zip(ids,quotes):
        try:
            a=bars_by_day(sid,source["raw_unadjusted"],"3",{entry_day.isoformat()})
            b=bars_by_day(sid,source["forward_adjusted"],"2",{entry_day.isoformat()})
            r=a.get(entry_day.isoformat()); adj=b.get(entry_day.isoformat())
            okay=(r is not None and adj is not None and active_bar(r)
                  and math.isfinite(float(adj["close"])) and float(adj["close"])>0)
        except (ValueError,KeyError,TypeError):
            okay=False
        receipts.append({"security_id":sid,"entry_price_pair_complete":bool(okay),
                         "raw_quote_sha256":sha(canonical_bytes(source))})
    raw_index=None
    try:
        raw_index=official_fetch(entry_day.isoformat(),entry_day.isoformat())
        index=read_index(raw_index,entry_day.isoformat(),entry_day.isoformat())
        index["status"]="OFFICIAL_H00300_ENTRY_VERIFIED"
    except (HTTPError,URLError,TimeoutError,OSError,ValueError,KeyError,TypeError) as exc:
        index={"status":"OFFICIAL_H00300_ENTRY_UNVERIFIED",
               "reason":type(exc).__name__+":"+str(exc)[:140]}
    complete=(all(x["entry_price_pair_complete"] for x in receipts)
              and index["status"]=="OFFICIAL_H00300_ENTRY_VERIFIED")
    source_archive={"quotes":quotes,"calendar":cal,
                    "official_index_http_base64":base64.b64encode(raw_index).decode() if raw_index else None}
    original=canonical_bytes(source_archive)
    report={
        "schema":"V29_FY2026_NEW_VINTAGE_PAPER_ENTRY_EIGHT_V1",
        "selected_eight":ids,"preentry_frame_sha256":frame_sha,
        "preentry_selection_sha256":selected_sha,
        "candidate_status":selected["status"],
        "annual_filing_pit_certified":selected["all_selected_original_filings_verified"],
        "official_exchange_calendar_verified":selected["calendar_officially_verified"],
        "first_entry_session":entry_day.isoformat(),
        "previous_reference_session":ref.isoformat(),
        "capture_time":local.isoformat(),"quotes":receipts,"benchmark":index,
        "raw_sources_sha256":sha(original),
        "status":"PAPER_ENTRY_EIGHT_AND_H00300_COMPLETE" if complete else "INCOMPLETE_PAPER_ENTRY",
        "strategy_validated":False,"trade_authorized":False,"live_buy_eligibility":"NOT_AUTHORIZED",
    }
    return report,original

def load_entry(root=ROOT,source_loader=source_candidates):
    root=Path(root)
    report_bytes=(root/ENTRY.relative_to(ROOT)).read_bytes()
    original=gzip.decompress((root/ENTRY_RAW.relative_to(ROOT)).read_bytes())
    report=json.loads(report_bytes)
    archive=json.loads(original)
    frame,selected,ids,frame_sha,selected_sha=source_loader()
    if (report.get("schema")!="V29_FY2026_NEW_VINTAGE_PAPER_ENTRY_EIGHT_V1"
        or report.get("status")!="PAPER_ENTRY_EIGHT_AND_H00300_COMPLETE"
        or report.get("selected_eight")!=ids
        or report.get("preentry_frame_sha256")!=frame_sha
        or report.get("preentry_selection_sha256")!=selected_sha
        or report.get("first_entry_session")!=frame["first_trading_session_after_cutoff"]
        or report.get("raw_sources_sha256")!=sha(original)
        or report.get("benchmark",{}).get("status")!="OFFICIAL_H00300_ENTRY_VERIFIED"
        or report.get("trade_authorized") is not False
        or [q.get("security_id") for q in archive.get("quotes",[])]!=ids
        or not all(x.get("entry_price_pair_complete") for x in report.get("quotes",[]))):
        raise ValueError("FUTURE_FINANCIAL_PAPER_ENTRY_FROZEN_SOURCE_CHANGED")
    return report,archive,sha(report_bytes),selected

def maturity(calendar,entry_day,now):
    if not isinstance(now,datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("FUTURE_FINANCIAL_AWARE_TIME_REQUIRED")
    local=now.astimezone(CN)
    sessions=complete_calendar(calendar,entry_day,local.date())
    if len(sessions)<20:
        raise ValueError("FUTURE_FINANCIAL_20_SESSION_OUTCOME_NOT_MATURE")
    exit_day=date.fromisoformat(sessions[19])
    if local < datetime.combine(exit_day,time(16,30),tzinfo=CN):
        raise ValueError("FUTURE_FINANCIAL_20_SESSION_CLOSE_NOT_MATURE")
    if local.date()>exit_day+timedelta(days=3):
        raise ValueError("FUTURE_FINANCIAL_EXIT_RETROSPECTIVE_WINDOW_EXPIRED")
    return sessions[:20],exit_day

def capture_outcome(bs,now,entry_loader=load_entry,official_fetch=index_fetch):
    entry,archive,entry_sha,selected=entry_loader()
    begin=date.fromisoformat(entry["first_entry_session"])
    local=now.astimezone(CN)
    login=bs.login()
    if login.error_code!="0":
        raise ValueError("BAOSTOCK_OUTCOME_LOGIN_FAILED")
    try:
        cal=records(bs.query_trade_dates(start_date=begin.isoformat(),end_date=local.date().isoformat()))
        sessions,end=maturity(cal,begin,now)
        quotes=query_bars(bs,entry["selected_eight"],begin.isoformat(),end.isoformat())
    finally:
        bs.logout()
    rows=[]
    for sid,prior,source in zip(entry["selected_eight"],archive["quotes"],quotes):
        result,_=one_issuer(sid,sessions,prior,source["raw_unadjusted"],source["forward_adjusted"])
        rows.append(result)
    raw_index=None
    try:
        raw_index=official_fetch(begin.isoformat(),end.isoformat())
        benchmark=read_index(raw_index,begin.isoformat(),end.isoformat(),
                             entry["benchmark"]["entry_close"])
        benchmark["status"]="OFFICIAL_H00300_BOTH_ENDPOINTS_VERIFIED"
    except (HTTPError,URLError,TimeoutError,OSError,ValueError,TypeError,KeyError) as exc:
        benchmark={"status":"OFFICIAL_H00300_EXIT_UNVERIFIED",
                   "reason":type(exc).__name__+":"+str(exc)[:140]}
    ok=(len(rows)==N and all(r["price_comparison_eligible"] for r in rows)
        and benchmark["status"]=="OFFICIAL_H00300_BOTH_ENDPOINTS_VERIFIED")
    metrics=None
    if ok:
        returns=[r["adjusted_exit_close"]/r["adjusted_entry_close"]-1-COST for r in rows]
        baseline=benchmark["exit_close"]/benchmark["entry_close"]-1
        old={x["security_id"]:x for x in archive["quotes"]}
        actual_cash=[]
        for sid in entry["selected_eight"]:
            b=bars_by_day(sid,old[sid]["raw_unadjusted"],"3",{begin.isoformat()})[begin.isoformat()]
            lot=next(x["minimum_lot_shares"] for x in selected["selected_in_frozen_ranking_order"]
                     if x["security_id"]==sid)
            actual_cash.append(float(b["close"])*lot)
        capital=sum(actual_cash)
        weights=[v/capital for v in actual_cash]
        weighted=sum(w*r for w,r in zip(weights,returns))
        metrics={
            "equal_eight_net":sum(returns)/N,
            "equal_eight_net_excess_vs_H00300":sum(returns)/N-baseline,
            "minimum_lot_cash_weighted_net_posthoc_sensitivity":weighted,
            "minimum_lot_cash_weighted_excess_vs_H00300_posthoc":weighted-baseline,
            "H00300_total_return":baseline,
            "entry_minimum_lot_total_reference_cny":round(capital,2),
            "round_trip_cost":COST,
        }
    packet={"calendar":cal,"quotes":quotes,
            "official_index_http_base64":base64.b64encode(raw_index).decode() if raw_index else None}
    raw=canonical_bytes(packet)
    return {
        "schema":"V29_FY2026_NEW_VINTAGE_TWENTIETH_SESSION_EIGHT_OUTCOME_V1",
        "source_entry_snapshot_sha256":entry_sha,
        "source_preentry_selection_sha256":entry["preentry_selection_sha256"],
        "selected_eight":entry["selected_eight"],
        "first_entry_session":begin.isoformat(),
        "twentieth_session":end.isoformat(),"verified_vendor_sessions":sessions,
        "capture_time":local.isoformat(),"price_eligible":sum(x["price_comparison_eligible"] for x in rows),
        "rows":rows,"benchmark":benchmark,"metrics":metrics,
        "raw_sources_sha256":sha(raw),
        "status":"ONE_NEW_ANNUAL_REPORT_VINTAGE_PAPER_EPISODE_ONLY" if ok else "INCOMPLETE_KEEP_ALL_EIGHT",
        "financial_report_original_filings_all_verified":entry["annual_filing_pit_certified"],
        "official_exchange_calendar_verified":entry["official_exchange_calendar_verified"],
        "one_vendor_adjustment_vintage_not_broker_fills":True,
        "single_annual_cohort_not_predictive_alpha":True,
        "strategy_validated":False,"trade_authorized":False,"live_buy_eligibility":"NOT_AUTHORIZED",
    },raw

def store(folder,phase,report,raw):
    folder=Path(folder)
    if folder.exists():
        raise ValueError("DO_NOT_OVERWRITE_PROSPECTIVE_FY2026_EVIDENCE")
    if (report["raw_sources_sha256"]!=sha(raw)
        or report.get("live_buy_eligibility")!="NOT_AUTHORIZED"
        or report.get("trade_authorized") is not False):
        raise ValueError("PROSPECTIVE_FY2026_SOURCE_IDENTITY_FAILED")
    folder.mkdir(parents=True)
    if phase=="entry":
        file="ENTRY_EIGHT.json"
        compressed="RAW_ENTRY_EIGHT.json.gz"
    elif phase=="outcome":
        file="OUTCOME_EIGHT.json"
        compressed="RAW_OUTCOME_EIGHT.json.gz"
    else:
        raise ValueError("INVALID_PHASE")
    (folder/file).write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    with (folder/compressed).open("wb") as f:
        with gzip.GzipFile(fileobj=f,mode="wb",mtime=0) as gz:
            gz.write(raw)

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--phase",choices=("entry","outcome"),required=True)
    p.add_argument("--out",type=Path,required=True)
    opts=p.parse_args()
    import baostock
    now=datetime.now(timezone.utc)
    # Only registered future periods may load candidate/outcome evidence.
    if now.astimezone(CN).date()<date(2027,5,1):
        raise SystemExit("FY2026_PAPER_RESEARCH_BEFORE_NEW_ANNUAL_VINTAGE")
    if opts.phase=="entry":
        packet,raw=capture_entry(baostock,now)
    else:
        packet,raw=capture_outcome(baostock,now)
    store(opts.out,opts.phase,packet,raw)
    print(json.dumps({"phase":opts.phase,"status":packet["status"],
                      "selected_count":N,"live_buy_eligibility":"NOT_AUTHORIZED"},
                     ensure_ascii=False))

if __name__=="__main__":
    main()
