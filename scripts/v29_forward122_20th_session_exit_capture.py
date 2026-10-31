#!/usr/bin/env python3
"""Maturity-gated fixed 20th-session FUTURE outcome of the already frozen 122.

The prior first-close snapshot is mandatory. Never shift entry or 20th exit.
Read both adjusted stock endpoints from one exit-time BaoStock capture vintage
and the official H00300.CSI TOTAL RETURN index from one response.
All 122 names remain, even if the required full-cohort metric is INCOMPLETE.
No permission for actual orders or strategy alpha admission.
"""
from __future__ import annotations

import argparse
import base64
import gzip
import hashlib
import json
import math
from datetime import date, datetime, time, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from v29_growth_forward_cohort import load_registered,evaluate
from v29_2025_filing_to_return_case import records
from v29_forward122_preentry_source_check import FIELDS,baostock_code
from v29_forward122_entry_close_capture import canonical_bytes, sha, numeric_positive

ROOT=Path(__file__).resolve().parents[1]
ENTRY_DIR=ROOT/"research/V2.9_FORWARD_122_ENTRY_20261102"
ENTRY=ENTRY_DIR/"ENTRY_SNAPSHOT_122.json"
ENTRY_RAW=ENTRY_DIR/"RAW_ENTRY_QUOTE_CALENDAR_AND_INDEX.json.gz"
ENTRY_DAY=date(2026,11,2)
EARLIEST_PLAUSIBLE_EXIT=date(2026,11,27)
LOCAL=ZoneInfo("Asia/Shanghai")
CLOSE_GATE=time(16,30)
OFFICIAL_API="https://www.csindex.com.cn/csindex-home/perf/index-perf"
HORIZON=20
N=122
SCHEMA="V29_122_FROZEN_FORWARD_20TH_SESSION_EXIT_EVIDENCE_V1"

def after_maturity_gate(now):
    if not isinstance(now,datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("AWARE_MATURITY_CLOCK_REQUIRED")
    local=now.astimezone(LOCAL)
    if local < datetime.combine(EARLIEST_PLAUSIBLE_EXIT,CLOSE_GATE,LOCAL):
        raise ValueError("FROZEN_20TH_SESSION_MATURITY_NOT_YET_OBSERVABLE")
    return local

def load_entry():
    spec,ids,protocol_sha=load_registered()
    if not ENTRY.exists() or not ENTRY_RAW.exists():
        raise ValueError("NO_SEALED_122_ENTRY_SOURCE_SNAPSHOT")
    evidence_bytes=ENTRY.read_bytes()
    data=json.loads(evidence_bytes)
    raw=gzip.decompress(ENTRY_RAW.read_bytes())
    provenance=json.loads(raw)
    if (data.get("schema")!="V29_122_PROSPECTIVE_FIXED_ENTRY_CLOSE_EVIDENCE_V1"
            or data.get("market_source_information_status")!="COMPLETE_QUOTES_AND_OFFICIAL_TR"
            or data.get("entry_session")!=ENTRY_DAY.isoformat()
            or data.get("frozen_protocol_sha256")!=protocol_sha
            or data.get("frozen_122_ids_sha256")!=spec["sample"]["sha256_linefeed"]
            or data.get("frozen_issuer_count")!=N
            or data.get("actual_rows_count")!=N
            or data.get("source_quote_complete_count")!=N
            or data.get("raw_source_bytes_sha256")!=sha(raw)
            or data.get("benchmark",{}).get("status")!="OFFICIAL_H00300_ENTRY_BAR_VERIFIED"
            or data.get("benchmark",{}).get("security_id")!="H00300.CSI"
            or len(provenance.get("quotes",[]))!=N
            or [x["security_id"] for x in data["rows"]]!=ids
            or [x["security_id"] for x in provenance["quotes"]]!=ids
            or any(x.get("source_bar_pair_complete") is not True for x in data["rows"])):
        raise ValueError("SEALED_ENTRY_DATA_OR_IDENTITY_CHANGED")
    return spec,ids,protocol_sha,sha(evidence_bytes),data,provenance

def trading_sessions(calendar,asof):
    seen={}
    for r in calendar:
        day=date.fromisoformat(r["calendar_date"])
        flag=r["is_trading_day"]
        if day in seen or flag not in ("0","1") or day<ENTRY_DAY or day>asof:
            raise ValueError("OFFICIAL_SESSION_SOURCE_INVALID_OR_DUPLICATE")
        seen[day]=flag
    if seen.get(ENTRY_DAY)!="1":
        raise ValueError("FROZEN_ENTRY_NOT_FIRST_OFFICIAL_SESSION")
    days=sorted(day for day,flag in seen.items() if flag=="1")
    if len(days)<HORIZON:
        raise ValueError("FROZEN_20_SESSION_WINDOW_NOT_COMPLETE")
    # SSE's published 2026 closure notice lists no November public-market
    # holidays. Demand an independently expected full Nov 2-27 calendar:
    # missing a single vendor weekday must NOT silently slide the exit to Nov 30.
    # An extraordinary exchange closure requires explicit source reconciliation
    # rather than retroactive horizon/date changes.
    expected=[ENTRY_DAY.fromordinal(n) for n in
              range(ENTRY_DAY.toordinal(),EARLIEST_PLAUSIBLE_EXIT.toordinal()+1)]
    if len([d for d in expected if d.weekday()<5])!=HORIZON:
        raise ValueError("FROZEN_NOVEMBER_REFERENCE_CALENDAR_INCONSISTENT")
    if any(d not in seen for d in expected):
        raise ValueError("NOVEMBER_EXCHANGE_CALENDAR_HAS_MISSING_DATES")
    if any(seen[d]!=("1" if d.weekday()<5 else "0") for d in expected):
        raise ValueError("NOVEMBER_EXCHANGE_CALENDAR_CONFLICTS_WITH_PUBLISHED_CLOSURES")
    if days[HORIZON-1]!=EARLIEST_PLAUSIBLE_EXIT:
        raise ValueError("TWENTIETH_SESSION_SLID_FROM_FROZEN_NOVEMBER_SCHEDULE")
    return [x.isoformat() for x in days[:HORIZON]]

def require_20th_close(sessions,now):
    local=after_maturity_gate(now)
    d=date.fromisoformat(sessions[-1])
    if local < datetime.combine(d,CLOSE_GATE,LOCAL):
        raise ValueError("ACTUAL_20TH_SESSION_NOT_YET_CLOSED")
    return d

def fetch_official_index(exit_session,opener=urlopen):
    url=OFFICIAL_API+"?"+urlencode({
        "indexCode":"H00300",
        "startDate":"20261102",
        "endDate":exit_session.replace("-",""),
    })
    request=Request(url,headers={
        "User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
        "Accept":"application/json,text/plain,*/*",
        "Referer":"https://www.csindex.com.cn/"})
    with opener(request,timeout=20) as response:
        raw=response.read(900_001)
    if len(raw)>900000:
        raise ValueError("CSINDEX_RESPONSE_SIZE_LIMIT")
    return raw

def index_result(raw,exit_session,entry_level):
    obj=json.loads(raw)
    if not isinstance(obj,dict) or not isinstance(obj.get("data"),list):
        raise ValueError("OFFICIAL_TR_RESULT_SCHEMA_INVALID")
    quotes={}
    for row in obj["data"]:
        if not isinstance(row,dict):
            raise ValueError("OFFICIAL_TR_ROW_SCHEMA_INVALID")
        if row.get("indexCode") not in ("H00300","H00300.CSI"):
            raise ValueError("PRICE_INDEX_INSTEAD_OF_FROZEN_TOTAL_RETURN")
        v=str(row.get("tradeDate") or "")
        if len(v)==8 and v.isdigit():
            d=datetime.strptime(v,"%Y%m%d").date().isoformat()
        else:
            d=date.fromisoformat(v).isoformat()
        if d < ENTRY_DAY.isoformat() or d > exit_session or d in quotes:
            raise ValueError("OFFICIAL_TR_UNEXPECTED_DATE_OR_DUPLICATE")
        close=numeric_positive(row.get("close"))
        if close is None:
            raise ValueError("OFFICIAL_TR_NONPOSITIVE_OR_INVALID")
        quotes[d]=close
    if ENTRY_DAY.isoformat() not in quotes or exit_session not in quotes:
        raise ValueError("OFFICIAL_TR_ENTRY_OR_EXIT_UNAVAILABLE")
    if abs(quotes[ENTRY_DAY.isoformat()]-entry_level)>0.0001:
        raise ValueError("ORIGINAL_OFFICIAL_TOTAL_RETURN_ENTRY_PRICE_REVISED")
    return {
        "security_id":"H00300.CSI",
        "source_sha256":sha(raw),
        "entry_total_return_index_close":quotes[ENTRY_DAY.isoformat()],
        "exit_total_return_index_close":quotes[exit_session],
        "source":OFFICIAL_API,
        "official_total_return_identity_verified":True,
    }

def bars_by_day(sid,rows,adjustflag,allowed):
    code=baostock_code(sid)
    result={}
    for r in rows:
        day=r.get("date")
        if (r.get("code")!=code or r.get("adjustflag")!=adjustflag or
                day not in allowed or day in result):
            raise ValueError("QUOTE_DATE_CODE_ADJUSTFLAG_OR_DUPLICATE_FAILED")
        result[day]=r
    return result

def active_bar(bar):
    try:
        close=numeric_positive(bar.get("close"))
        volume=numeric_positive(bar.get("volume"))
    except (TypeError,AttributeError):
        return False
    return (close is not None and volume is not None and
            bar.get("tradestatus")=="1" and bar.get("isST")=="0")

def one_issuer(sid,sessions,entry_provenance,raw,adjusted):
    allowed=set(sessions)
    sources={"security_id":sid,"raw_unadjusted":raw,"forward_adjusted":adjusted}
    receipt={
        "canonical_security_id":sid,
        "entry_session":sessions[0],
        "exit_session":sessions[-1],
        "raw_quote_sha256":sha(canonical_bytes(sources)),
        "adjusted_entry_close":None,
        "adjusted_exit_close":None,
        "entry_tradeable_at_reference_close":False,
        "exit_tradeable_at_reference_close":False,
        "corporate_actions_and_dividends_adjusted":False,
        "actual_entry_fill_proven":False,
        "actual_exit_fill_proven":False,
        "vendor_adjustment_is_independent_total_return_certification":False,
        "price_comparison_eligible":False,
    }
    try:
        raw_map=bars_by_day(sid,raw,"3",allowed)
        adj_map=bars_by_day(sid,adjusted,"2",allowed)
        initial=entry_provenance.get("raw_unadjusted",[])
        if len(initial)!=1:
            receipt["observation_status"]="FROZEN_ENTRY_RAW_SOURCE_MISSING"
            return receipt,sources
        e=raw_map.get(sessions[0])
        x=raw_map.get(sessions[-1])
        ae=adj_map.get(sessions[0])
        ax=adj_map.get(sessions[-1])
        if not e or not x or not ae or not ax:
            receipt["observation_status"]="ENDPOINT_BAR_MISSING_NO_SUBSTITUTION"
            return receipt,sources
        try:
            same_raw_close=(Decimal(str(e.get("close")))==
                            Decimal(str(initial[0].get("close"))))
        except InvalidOperation:
            same_raw_close=False
        if not same_raw_close:
            receipt["observation_status"]="FROZEN_UNADJUSTED_ENTRY_CLOSE_VINTAGE_DRIFT"
            return receipt,sources
        receipt["entry_tradeable_at_reference_close"]=active_bar(e)
        receipt["exit_tradeable_at_reference_close"]=active_bar(x)
        if not receipt["entry_tradeable_at_reference_close"] or not receipt["exit_tradeable_at_reference_close"]:
            receipt["observation_status"]="ENTRY_OR_EXIT_TRADING_ST_VOLUME_NOT_VERIFIED"
            return receipt,sources
        entry_price=numeric_positive(ae.get("close"))
        exit_price=numeric_positive(ax.get("close"))
        if entry_price is None or exit_price is None:
            receipt["observation_status"]="SAME_VINTAGE_ADJUSTED_ENDPOINT_INVALID"
            return receipt,sources
        receipt.update({
            "adjusted_entry_close":entry_price,
            "adjusted_exit_close":exit_price,
            "corporate_actions_and_dividends_adjusted":True,
            "vendor_adjustment":"BAOSTOCK_FORWARD_ADJUSTED_FLAG_2_ONE_EXIT_VINTAGE",
            "vendor_adjustment_is_independent_total_return_certification":False,
            "observation_status":"PAPER_REFERENCE_ADJUSTED_CLOSE_PAIR_OBSERVED",
            "price_comparison_eligible":True,
        })
    except (ValueError,KeyError,TypeError) as e:
        receipt["observation_status"]="QUOTE_SOURCE_SCHEMA_IDENTITY_OR_DATE_FAILED"
        receipt["observation_error"]=type(e).__name__+":"+str(e)[:150]
    return receipt,sources

def capture(bs,now=None,official_fetch=fetch_official_index,entry_sources=None):
    local=after_maturity_gate(now or datetime.now(timezone.utc))
    spec,ids,protocol_sha,entry_sha,entry,archive=entry_sources or load_entry()
    if (len(ids)!=N or entry["entry_session"]!=ENTRY_DAY.isoformat()
            or archive["entry_date"]!=ENTRY_DAY.isoformat()):
        raise ValueError("FROZEN_ENTRY_IDENTITY_DRIFT")
    login=bs.login()
    if login.error_code!="0":
        raise ValueError("BAOSTOCK_LOGIN_FAILED:"+str(login.error_msg))
    results=[]
    try:
        cal=records(bs.query_trade_dates(
            start_date=ENTRY_DAY.isoformat(),end_date=local.date().isoformat()))
        sessions=trading_sessions(cal,local.date())
        exit_day=require_20th_close(sessions,local).isoformat()
        for i,(sid,original) in enumerate(zip(ids,archive["quotes"]),1):
            code=baostock_code(sid)
            raw,adj=[],[]
            query_error=None
            try:
                raw=records(bs.query_history_k_data_plus(
                    code,FIELDS,start_date=ENTRY_DAY.isoformat(),end_date=exit_day,
                    frequency="d",adjustflag="3"))
                adj=records(bs.query_history_k_data_plus(
                    code,FIELDS,start_date=ENTRY_DAY.isoformat(),end_date=exit_day,
                    frequency="d",adjustflag="2"))
                r,source=one_issuer(sid,sessions,original,raw,adj)
            except (OSError,ValueError,KeyError) as e:
                query_error=type(e).__name__+":"+str(e)[:170]
                r,source=one_issuer(sid,sessions,original,[],[])
                r["observation_status"]="SOURCE_QUERY_FAILED"
                r["observation_error"]=query_error
            results.append((r,source))
            print(f"EXIT {i:03d}/{N} {sid} {r['observation_status']}",flush=True)
    finally:
        bs.logout()
    official_raw=None
    benchmark_error=None
    try:
        official_raw=official_fetch(exit_day)
        benchmark=index_result(
            official_raw,exit_day,entry["benchmark"]["entry_total_return_index_close"])
    except (HTTPError,URLError,TimeoutError,OSError,ValueError,TypeError,KeyError) as e:
        benchmark_error=type(e).__name__+":"+str(e)[:170]
        benchmark={"security_id":"H00300.CSI",
                   "source_sha256":sha(official_raw) if official_raw is not None else None,
                   "entry_total_return_index_close":entry["benchmark"]["entry_total_return_index_close"],
                   "exit_total_return_index_close":None,
                   "official_total_return_identity_verified":False}
    saved_raw={
        "schema":"V29_122_20_SESSION_RAW_EXIT_SOURCES_V1",
        "protocol_sha256":protocol_sha,
        "sealed_entry_sha256":entry_sha,
        "selected_20_exchange_sessions":sessions,
        "raw_baostock_calendar":cal,
        "official_index_http_base64":base64.b64encode(official_raw).decode() if official_raw is not None else None,
        "stock_sources":[x for _,x in results],
    }
    source_bytes=canonical_bytes(saved_raw)
    quote_receipts=[r for r,_ in results]
    outcome={
        "schema":"V29_FORWARD_COHORT_OBSERVED_OUTCOMES_V1",
        "experiment_id":spec["experiment_id"],
        "protocol_sha256":protocol_sha,
        "verified_exchange_sessions":sessions,
        "calendar_source":"BAOSTOCK_TRADING_CALENDAR_CROSSCHECKED_WITH_SSE_2026_HOLIDAY_NOTICE",
        "calendar_sha256":sha(canonical_bytes(cal)),
        "raw_outcome_sources_sha256":sha(source_bytes),
        "capture_timestamp":local.isoformat(),
        "benchmark":benchmark,
        "securities":quote_receipts,
    }
    if benchmark["official_total_return_identity_verified"]:
        evaluated=evaluate(outcome,now=local)
    else:
        evaluated={
            "status":"INCOMPLETE_OFFICIAL_BENCHMARK_SOURCE_UNVERIFIED",
            "frozen_security_count":N,
            "observed_count":len(quote_receipts),
            "computable_count":sum(x["price_comparison_eligible"] for x in quote_receipts),
            "unavailable_count":N-sum(x["price_comparison_eligible"] for x in quote_receipts),
            "mean_net_excess":None,
            "strategy_validated":False,
            "live_buy_eligibility":"NOT_AUTHORIZED",
            "reason":benchmark_error,
        }
    report={
        "schema":SCHEMA,
        "frozen_cohort_count":N,
        "fixed_entry_session":ENTRY_DAY.isoformat(),
        "fixed_exit_session":exit_day,
        "calendar_session_count":len(sessions),
        "benchmark_source_status":(
            "OFFICIAL_H00300_ENTRY_AND_EXIT_VERIFIED"
            if benchmark["official_total_return_identity_verified"] else
            "OFFICIAL_H00300_EXIT_UNVERIFIED"),
        "quote_source_eligible_count":sum(x["price_comparison_eligible"] for x in quote_receipts),
        "quote_source_incomplete_count":sum(not x["price_comparison_eligible"] for x in quote_receipts),
        "source_bytes_sha256":sha(source_bytes),
        "entry_snapshot_sha256":entry_sha,
        "protocol_sha256":protocol_sha,
        "outcome_evaluation":evaluated,
        "market_source_independently_certified":False,
        "actual_entry_exit_fills_proven":False,
        "same_vintage_BaoStock_forward_adjusted_source_not_cash_dividend_reinvestment_certified":True,
        "one_market_episode_not_a_generalizable_strategy":True,
        "trade_authorized":False,
        "live_buy_eligibility":"NOT_AUTHORIZED",
    }
    return report,outcome,source_bytes

def save(out,report,outcome,raw):
    if out.exists():
        raise ValueError("REFUSE_OVERWRITE_FUTURE_OUTCOME_CAPTURE")
    if (len(outcome["securities"])!=N or
            report["quote_source_eligible_count"]+report["quote_source_incomplete_count"]!=N or
            report["source_bytes_sha256"]!=sha(raw) or
            report["outcome_evaluation"]["live_buy_eligibility"]!="NOT_AUTHORIZED"):
        raise ValueError("FROZEN_122_OUTCOME_SOURCE_INTEGRITY_FAILED")
    out.mkdir(parents=True)
    (out/"20_SESSION_RESEARCH_VERDICT.json").write_text(
        json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    (out/"OUTCOMES_122.json").write_text(
        json.dumps(outcome,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    with (out/"RAW_VENDOR_STOCK_AND_H00300_INDEX.json.gz").open("wb") as fh:
        with gzip.GzipFile(fileobj=fh,mode="wb",mtime=0) as z:
            z.write(raw)

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--out",type=Path,required=True)
    args=p.parse_args()
    import baostock
    report,outcome,raw=capture(baostock)
    save(args.out,report,outcome,raw)
    print(json.dumps({
        "sessions":report["calendar_session_count"],
        "entry":report["fixed_entry_session"],
        "exit":report["fixed_exit_session"],
        "quote_eligible":report["quote_source_eligible_count"],
        "benchmark":report["benchmark_source_status"],
        "eval_status":report["outcome_evaluation"]["status"],
        "BUY":"NOT_AUTHORIZED",
    },ensure_ascii=False),flush=True)

if __name__=="__main__":
    main()
