#!/usr/bin/env python3
"""One fixed prospective paper-entry CLOSE source snapshot for the frozen 122 cohort.

Only the first officially scheduled A-share trading date after 2026-10-30,
2026-11-02, may be queried, and only after that trading session has CLOSED.
All 122 names stay in the manifest even when no quote or source is available.
No exits, returns, backfills to a different entry session, or live BUY authority.
"""
from __future__ import annotations

import argparse
import base64
import gzip
import hashlib
import io
import json
import math
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from v29_growth_forward_cohort import load_registered
from v29_2025_filing_to_return_case import records
from v29_forward122_preentry_source_check import (
    baostock_code, TR_ENDPOINT, FIELDS, sha,
)

ROOT=Path(__file__).resolve().parents[1]
PREENTRY=ROOT/"research/V2.9_FORWARD_122_PREENTRY_SOURCE_FEASIBILITY_20261031.json"
ENTRY_DAY=date(2026,11,2)
PRIOR_DAY=date(2026,10,30)
LOCAL=ZoneInfo("Asia/Shanghai")
AFTER_CLOSE=time(16,30)
SCHEMA="V29_122_PROSPECTIVE_FIXED_ENTRY_CLOSE_EVIDENCE_V1"
INDEX="H00300.CSI"
BENCHMARK_API="https://www.csindex.com.cn/csindex-home/perf/index-perf"
EXCHANGE_CALENDAR="https://www.sse.com.cn/disclosure/announcement/general/c/c_20251222_10802507.shtml"
SAMPLE_COUNT=122

def canonical_bytes(obj):
    return (json.dumps(obj,ensure_ascii=False,sort_keys=True,separators=(",",":"))+"\n").encode()

def ready_to_query(now):
    if not isinstance(now,datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("AWARE_CAPTURE_CLOCK_REQUIRED")
    local=now.astimezone(LOCAL)
    if local < datetime.combine(ENTRY_DAY,AFTER_CLOSE,LOCAL):
        raise ValueError("ENTRY_CLOSE_NOT_YET_OBSERVABLE")
    if local.date()>date(2026,11,4):
        raise ValueError("ENTRY_CAPTURE_WINDOW_EXPIRED_NO_LATE_HINDSIGHT_BACKFILL")
    return local

def fixed_sources():
    spec,ids,hash_of_protocol=load_registered()
    document=PREENTRY.read_bytes()
    prior=json.loads(document)
    if (len(ids)!=SAMPLE_COUNT or len(set(ids))!=SAMPLE_COUNT
            or prior.get("schema")!="V29_122_PROSPECTIVE_PREENTRY_SOURCE_FEASIBILITY_V1"
            or prior.get("frozen_cohort_count")!=SAMPLE_COUNT
            or prior.get("attempted_count")!=SAMPLE_COUNT
            or prior.get("protocol_sha256")!=hash_of_protocol
            or prior.get("frozen_sample_sha256")!=spec["sample"]["sha256_linefeed"]
            or [r["security_id"] for r in prior["rows"]]!=ids
            or prior.get("stock_reference_bar_both_versions_ok")!=SAMPLE_COUNT
            or prior.get("future_sessions_queried") is not False
            or prior.get("benchmark",{}).get("requested_index")!=INDEX
            or prior.get("benchmark",{}).get("benchmark_source_status")!=
                "OFFICIAL_H00300_PRE_FREEZE_REFERENCE_BAR_VERIFIED"
            or prior.get("benchmark",{}).get("reference_close")!=6001.14):
        raise ValueError("FROZEN_FORWARD_PROTOCOL_PREENTRY_EVIDENCE_CHANGED")
    return spec,ids,hash_of_protocol,sha(document),prior

def verify_calendar(rows):
    if not isinstance(rows,list) or not rows:
        raise ValueError("EMPTY_EXCHANGE_CALENDAR")
    unique={}
    for r in rows:
        d=date.fromisoformat(r["calendar_date"])
        v=r["is_trading_day"]
        if d in unique or v not in ("0","1") or not PRIOR_DAY<d<=ENTRY_DAY:
            raise ValueError("UNEXPECTED_CALENDAR_DATE_DUPLICATE_OR_FLAG")
        unique[d]=v
    if unique.get(date(2026,10,31))!="0" or unique.get(date(2026,11,1))!="0":
        raise ValueError("WEEKEND_NOT_CLOSED_IN_VENDOR_CALENDAR")
    if unique.get(ENTRY_DAY)!="1":
        raise ValueError("FIRST_TRADING_DAY_NOT_OFFICIALLY_CONFIRMED")
    return ENTRY_DAY.isoformat()

def numeric_positive(v):
    try:
        x=float(v)
    except (TypeError,ValueError):
        return None
    return x if math.isfinite(x) and x>0 else None

def validate_bars(sid, raw, adjusted):
    """Validate real one-day sources; do not infer executable closing-auction fills."""
    code=baostock_code(sid)
    def one(rows,flag):
        if not rows:
            return {"status":"ENTRY_BAR_MISSING"}
        if len(rows)!=1:
            return {"status":"DUPLICATE_ENTRY_BAR"}
        r=rows[0]
        if r.get("code")!=code or r.get("date")!=ENTRY_DAY.isoformat() or r.get("adjustflag")!=flag:
            return {"status":"ENTRY_IDENTITY_DATE_OR_ADJUSTMENT_MISMATCH"}
        price=numeric_positive(r.get("close"))
        vol=numeric_positive(r.get("volume"))
        if price is None:
            return {"status":"MISSING_OR_INVALID_CLOSE"}
        if r.get("tradestatus")!="1":
            return {"status":"SESSION_NOT_TRADING","close":price}
        if r.get("isST")=="1":
            return {"status":"ENTRY_DAY_ST_FLAG","close":price}
        if r.get("isST")!="0":
            return {"status":"ENTRY_DAY_ST_FLAG_UNKNOWN","close":price}
        if vol is None:
            return {"status":"ZERO_OR_INVALID_VOLUME","close":price}
        return {"status":"ACTIVE_EOD_QUOTE_NOT_FILL_CERTIFIED","close":price,"volume":vol,
                "isST":"0","tradestatus":"1"}
    a,b=one(raw,"3"),one(adjusted,"2")
    complete=(a["status"]==b["status"]=="ACTIVE_EOD_QUOTE_NOT_FILL_CERTIFIED")
    return {"entry_unadjusted":a,"entry_forward_adjusted_at_capture_vintage":b,
            "source_bar_pair_complete":complete,"paper_entry_executability_verified":False,
            "limit_up_down_trade_fill_verified":False}

def parse_index(raw,reference_close):
    obj=json.loads(raw)
    if not isinstance(obj,dict) or not isinstance(obj.get("data"),list):
        raise ValueError("CSINDEX_OFFICIAL_RESPONSE_SCHEMA_UNVERIFIED")
    by_day={}
    for r in obj["data"]:
        if not isinstance(r,dict):
            raise ValueError("CSINDEX_OFFICIAL_INDEX_ROW_INVALID")
        code=str(r.get("indexCode") or "").upper()
        if code not in ("H00300","H00300.CSI"):
            raise ValueError("CSI300_PRICE_INDEX_SUBSTITUTION_REJECTED")
        v=str(r.get("tradeDate") or "")
        if len(v)==8 and v.isdigit():
            d=datetime.strptime(v,"%Y%m%d").date()
        else:
            d=date.fromisoformat(v)
        if not PRIOR_DAY<=d<=ENTRY_DAY or d in by_day:
            raise ValueError("BENCHMARK_DATE_OUTSIDE_ALLOWED_WINDOW_OR_DUPLICATE")
        close=numeric_positive(r.get("close"))
        if close is None:
            raise ValueError("BENCHMARK_CLOSE_INVALID")
        by_day[d]=close
    if PRIOR_DAY not in by_day or ENTRY_DAY not in by_day:
        raise ValueError("OFFICIAL_TR_PAIR_PRIOR_OR_ENTRY_BAR_MISSING")
    if abs(by_day[PRIOR_DAY]-reference_close)>0.0001:
        raise ValueError("PRIOR_FROZEN_INDEX_CLOSE_REVISED_OR_WRONG_SOURCE")
    return {
        "status":"OFFICIAL_H00300_ENTRY_BAR_VERIFIED",
        "security_id":INDEX,
        "source":BENCHMARK_API,
        "2026_10_30_reference_close":by_day[PRIOR_DAY],
        "entry_total_return_index_close":by_day[ENTRY_DAY],
        "source_sha256":sha(raw),
        "close_is_executable_fill":False,
    }

def fetch_index(opener=urlopen):
    url=BENCHMARK_API+"?"+urlencode({
        "indexCode":"H00300","startDate":"20261030","endDate":"20261102"})
    request=Request(url,headers={
        "User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
        "Accept":"application/json,text/plain,*/*",
        "Referer":"https://www.csindex.com.cn/"})
    with opener(request,timeout=20) as response:
        raw=response.read(900_001)
    if len(raw)>900000:
        raise ValueError("INDEX_HTTP_RESPONSE_TOO_LARGE")
    return raw

def capture(bs,fetch_official=fetch_index,now=None):
    local=ready_to_query(now or datetime.now(timezone.utc))
    spec,ids,protocol_sha,preentry_sha,prior=fixed_sources()
    # Nothing beyond this source gate can query a future close or use a later
    # trading day to replace the frozen Monday entry.
    started=local.isoformat()
    login=bs.login()
    if login.error_code!="0":
        raise ValueError("BAOSTOCK_LOGIN_FAILED:"+str(login.error_msg))
    quote_sources=[]
    try:
        calendar=records(bs.query_trade_dates(
            start_date="2026-10-31",end_date=ENTRY_DAY.isoformat()))
        verified_day=verify_calendar(calendar)
        for i,sid in enumerate(ids,1):
            code=baostock_code(sid)
            raw,adjusted=[],[]
            error=None
            try:
                raw=records(bs.query_history_k_data_plus(
                    code,FIELDS,start_date=verified_day,end_date=verified_day,
                    frequency="d",adjustflag="3"))
                adjusted=records(bs.query_history_k_data_plus(
                    code,FIELDS,start_date=verified_day,end_date=verified_day,
                    frequency="d",adjustflag="2"))
                result=validate_bars(sid,raw,adjusted)
            except (OSError,ValueError,KeyError) as ex:
                error=type(ex).__name__+":"+str(ex)[:170]
                result={"entry_unadjusted":{"status":"SOURCE_QUERY_ERROR"},
                        "entry_forward_adjusted_at_capture_vintage":{"status":"SOURCE_QUERY_ERROR"},
                        "source_bar_pair_complete":False,
                        "paper_entry_executability_verified":False,
                        "limit_up_down_trade_fill_verified":False}
            sources={"security_id":sid,"raw_unadjusted":raw,"forward_adjusted":adjusted}
            result.update({"security_id":sid,"entry_session":verified_day,
                           "source_query_error":error,
                           "per_issuer_raw_bars_sha256":sha(canonical_bytes(sources)),
                           "historical_date_not_shifted":True})
            quote_sources.append((result,sources))
            print(f"ENTRY {i:03d}/{SAMPLE_COUNT} {sid} "
                  f"{'QUOTE_SOURCE_OK' if result['source_bar_pair_complete'] else 'QUOTE_SOURCE_INCOMPLETE'}",flush=True)
    finally:
        bs.logout()

    index_raw=None
    try:
        index_raw=fetch_official()
        index=parse_index(index_raw,prior["benchmark"]["reference_close"])
    except (HTTPError,URLError,TimeoutError,OSError,ValueError,TypeError,KeyError) as ex:
        index={"status":"OFFICIAL_H00300_ENTRY_SOURCE_UNVERIFIED",
               "security_id":INDEX,
               "reason":type(ex).__name__+":"+str(ex)[:170],
               "source_sha256":sha(index_raw) if index_raw is not None else None,
               "entry_total_return_index_close":None}
    rows=[x for x,_ in quote_sources]
    complete=sum(x["source_bar_pair_complete"] for x in rows)
    source_payload={
        "schema":"V29_122_ENTRY_RAW_VENDOR_PROVENANCE_V1",
        "frozen_protocol_sha256":protocol_sha,
        "prior_evidence_sha256":preentry_sha,
        "entry_date":ENTRY_DAY.isoformat(),
        "calendar_source":"BAOSTOCK_QUERY_TRADE_DATES",
        "official_exchange_schedule_reference":EXCHANGE_CALENDAR,
        "baostock_calendar_raw":calendar,
        "index_http_raw_base64":base64.b64encode(index_raw).decode() if index_raw is not None else None,
        "quotes":[x for _,x in quote_sources],
    }
    raw=canonical_bytes(source_payload)
    result={
        "schema":SCHEMA,
        "captured_at_china":started,
        "frozen_protocol_sha256":protocol_sha,
        "frozen_122_ids_sha256":spec["sample"]["sha256_linefeed"],
        "frozen_preentry_evidence_sha256":preentry_sha,
        "frozen_issuer_count":SAMPLE_COUNT,
        "actual_rows_count":len(rows),
        "entry_session":ENTRY_DAY.isoformat(),
        "entry_is_first_vendor_calendar_session_after_2026_10_30":True,
        "exchange_schedule_source":EXCHANGE_CALENDAR,
        "exchange_calendar_vendor":"BAOSTOCK",
        "source_quote_complete_count":complete,
        "source_quote_incomplete_count":SAMPLE_COUNT-complete,
        "benchmark":index,
        "raw_source_bytes_sha256":sha(raw),
        "market_source_information_status":
            "COMPLETE_QUOTES_AND_OFFICIAL_TR" if complete==SAMPLE_COUNT and
            index["status"]=="OFFICIAL_H00300_ENTRY_BAR_VERIFIED"
            else "INCOMPLETE_NO_SUBSTITUTION_OR_ENTRY_SHIFT",
        "same_vendor_corporate_action_dividend_adjusted_exit_still_unobserved":True,
        "future_return_or_twentieth_session_exit_read":False,
        "future_outcome_strategy_performance_computed":False,
        "actual_limit_price_order_book_fill_certified":False,
        "all_122_actual_buy_fills_certified":False,
        "independent_OOS_strategy_validated":False,
        "paper_entry_only":True,
        "live_buy_eligibility":"NOT_AUTHORIZED",
        "rows":rows,
    }
    return result,raw

def write(out,report,raw):
    if out.exists():
        raise ValueError("DO_NOT_OVERWRITE_PRIOR_ENTRY_SOURCE_CAPTURE")
    if (len(report["rows"])!=SAMPLE_COUNT
            or report["source_quote_complete_count"]+
               report["source_quote_incomplete_count"]!=SAMPLE_COUNT
            or sha(raw)!=report["raw_source_bytes_sha256"]):
        raise ValueError("RAW_ENTRY_SOURCE_HASH_OR_DENOMINATOR_INVALID")
    out.mkdir(parents=True)
    (out/"ENTRY_SNAPSHOT_122.json").write_text(
        json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    with (out/"RAW_ENTRY_QUOTE_CALENDAR_AND_INDEX.json.gz").open("wb") as fh:
        with gzip.GzipFile(fileobj=fh,mode="wb",mtime=0) as compressed:
            compressed.write(raw)

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--out",type=Path,required=True)
    args=parser.parse_args()
    import baostock
    result,raw=capture(baostock)
    write(args.out,result,raw)
    print(json.dumps({
        "entry_day":result["entry_session"],
        "sample_count":result["actual_rows_count"],
        "quote_complete":result["source_quote_complete_count"],
        "benchmark":result["benchmark"]["status"],
        "source_status":result["market_source_information_status"],
        "not_an_exit_or_buy_signal":True,
    },ensure_ascii=False),flush=True)

if __name__=="__main__":
    main()
