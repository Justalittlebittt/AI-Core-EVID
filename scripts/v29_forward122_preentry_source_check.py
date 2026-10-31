#!/usr/bin/env python3
"""Read-only pre-entry source readiness for a 122-name future V2.9 experiment.

Reference day 2026-10-30 is the last completed session at research freeze.
NO 2026-11-02-or-later stock price / future outcome query is allowed here.
Only official CSI300 TOTAL RETURN (H00300.CSI) may satisfy benchmark identity.
No technical or observed result here is BUY authorization.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request,urlopen
from urllib.error import HTTPError,URLError

from v29_growth_forward_cohort import load_registered
from v29_2025_filing_to_return_case import records

TR_ENDPOINT = "https://www.csindex.com.cn/csindex-home/perf/index-perf"
REFERENCE_DAY = "2026-10-30"
LOOKBACK_START = "2026-10-20"
FIELDS = "date,code,close,adjustflag,tradestatus,isST,volume,amount"
SCHEMA = "V29_122_PROSPECTIVE_PREENTRY_SOURCE_FEASIBILITY_V1"

def sha(raw):
    return hashlib.sha256(raw).hexdigest()

def fetch_total_return(opener=urlopen):
    url = TR_ENDPOINT + "?" + urlencode({
        "indexCode":"H00300",
        "startDate":LOOKBACK_START.replace("-",""),
        "endDate":REFERENCE_DAY.replace("-",""),
    })
    request=Request(url,headers={
        "User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
        "Accept":"application/json,text/plain,*/*",
        "Referer":"https://www.csindex.com.cn/",
    })
    raw=None
    try:
        with opener(request,timeout=15) as response:
            raw=response.read(900_001)
        if len(raw)>900000:
            raise ValueError("OFFICIAL_INDEX_RESPONSE_TOO_LARGE")
        result=parse_total_return(raw)
        result["official_raw_sha256"]=sha(raw)
        return result,raw
    except (HTTPError,URLError,TimeoutError,OSError,ValueError,KeyError,TypeError,json.JSONDecodeError) as e:
        reason=(f"HTTP_{e.code}" if isinstance(e,HTTPError) else type(e).__name__)
        # The response is from a public index site, not portfolio/secret data.
        # Preserve a bounded diagnostic and hash to identify source drift.
        preview=raw[:240].decode("utf-8","replace") if raw else None
        return {"source":"CSINDEX_OFFICIAL_INDEX_PERF",
                "requested_index":"H00300.CSI",
                "benchmark_source_status":"UNVERIFIED_OFFICIAL_TOTAL_RETURN_SOURCE",
                "reason":reason,
                "source_response_error_detail":str(e)[:180],
                "source_response_preview":preview,
                "official_raw_sha256":sha(raw) if raw else None},raw

def parse_total_return(raw):
    obj=json.loads(raw)
    if not isinstance(obj,dict) or not isinstance(obj.get("data"),list):
        raise ValueError("CSINDEX_TOTAL_RETURN_RESPONSE_SCHEMA_INVALID")
    data=obj["data"]
    points=[]
    for r in data:
        # Official CSI index-perf returns 16-element sequences in the
        # implementation documented by AKShare stock_zh_index_hist_csindex.
        if isinstance(r,list) and len(r)>=10:
            d,code,close=r[0],r[1],r[9]
        elif isinstance(r,dict):
            d=r.get("tradeDate") or r.get("date") or r.get("日期")
            code=r.get("indexCode") or r.get("指数代码")
            close=r.get("close") or r.get("收盘")
        else:
            raise ValueError("OFFICIAL_INDEX_UNEXPECTED_ROW_SHAPE")
        code=str(code or "").upper()
        if code not in ("H00300","H00300.CSI"):
            raise ValueError("NOT_CSI300_TOTAL_RETURN_IDENTITY")
        date_str=str(d)
        if len(date_str)==8 and date_str.isdigit():
            day=datetime.strptime(date_str,"%Y%m%d").date().isoformat()
        elif len(date_str)==10:
            day=datetime.strptime(date_str,"%Y-%m-%d").date().isoformat()
        else:
            raise ValueError("CSINDEX_UNSUPPORTED_OFFICIAL_DATE_FORMAT")
        if day < LOOKBACK_START or day > REFERENCE_DAY:
            raise ValueError("CSINDEX_INDEX_DATA_OUTSIDE_ALLOWED_PRE_FREEZE_WINDOW")
        value=float(close)
        if not math.isfinite(value) or value<=0:
            raise ValueError("CSINDEX_INDEX_CLOSE_INVALID")
        points.append({"date":day,"index":"H00300.CSI","close":value})
    if len(points)==0 or len({x["date"] for x in points})!=len(points):
        raise ValueError("OFFICIAL_TR_SOURCE_EMPTY_OR_DUPLICATED")
    if REFERENCE_DAY not in {p["date"] for p in points}:
        raise ValueError("OFFICIAL_TR_REFERENCE_DAY_NOT_PRESENT")
    return {
        "source":"CSINDEX_OFFICIAL_INDEX_PERF",
        "requested_index":"H00300.CSI",
        "benchmark_source_status":"OFFICIAL_H00300_PRE_FREEZE_REFERENCE_BAR_VERIFIED",
        "reference_close":next(x["close"] for x in points if x["date"]==REFERENCE_DAY),
        "reference_index_points":points,
    }

def baostock_code(sid):
    exchange,code=sid.split(":")
    return ("sh." if exchange=="SSE" else "sz.")+code

def inspect_reference_quotes(sid, raw, forward):
    code=baostock_code(sid)
    def single(records_,adjustflag):
        if len(records_)==0:
            return {"status":"PRE_FREEZE_BAR_MISSING"}
        if len(records_)!=1:
            raise ValueError("PRE_FREEZE_DUPLICATE_BARS")
        r=records_[0]
        if (r.get("date")!=REFERENCE_DAY or r.get("code")!=code or
                r.get("adjustflag")!=adjustflag):
            raise ValueError("PRE_FREEZE_SECURITY_DATE_OR_ADJUSTMENT_IDENTITY")
        close=float(r.get("close","nan"))
        if not math.isfinite(close) or close<=0:
            return {"status":"PRE_FREEZE_INVALID_QUOTE"}
        try:
            volume=float(r["volume"])
        except (ValueError,KeyError,TypeError):
            volume=None
        status=("REFERENCE_BAR_TRADEABLE_OBSERVED" if
                r.get("tradestatus")=="1" and r.get("isST")=="0" and
                volume is not None and volume>0 else
                "REFERENCE_BAR_ST_SUSPENSION_OR_VOLUME_UNCERTAIN")
        return {"status":status,"close":close,
                "trading_status":r.get("tradestatus"),
                "isST":r.get("isST"),"volume":volume}
    try:
        unadjusted=single(raw,"3")
        adjusted=single(forward,"2")
        return {"unadjusted":unadjusted,"forward_adjusted_2026_vintage":adjusted,
                "reference_valid_both_price_versions":
                    all(p["status"]=="REFERENCE_BAR_TRADEABLE_OBSERVED"
                        for p in (unadjusted,adjusted))}
    except (ValueError,KeyError,TypeError) as ex:
        return {"reference_valid_both_price_versions":False,
                "status":"SOURCE_BAR_IDENTITY_INVALID",
                "reason":str(ex)[:150]}

def collect(bs,limit=122,index_fetch=fetch_total_return):
    if type(limit) is not int or not 1<=limit<=122:
        raise ValueError("INVALID_LIMIT")
    protocol,ids,protocol_sha=load_registered()
    # Explicitly prohibit any post-freeze query. A later observer still
    # executes this as a historical as-of snapshot, NOT an entry-day signal.
    index,rawindex=index_fetch()
    login=bs.login()
    if login.error_code!="0":
        raise ValueError("BAOSTOCK_PREENTRY_LOGIN_FAILED:"+str(login.error_msg))
    rows=[]
    try:
        for i,sid in enumerate(ids[:limit],1):
            code=baostock_code(sid)
            try:
                unadjusted=records(bs.query_history_k_data_plus(
                    code,FIELDS,start_date=REFERENCE_DAY,end_date=REFERENCE_DAY,
                    frequency="d",adjustflag="3"))
                forward=records(bs.query_history_k_data_plus(
                    code,FIELDS,start_date=REFERENCE_DAY,end_date=REFERENCE_DAY,
                    frequency="d",adjustflag="2"))
                x=inspect_reference_quotes(sid,unadjusted,forward)
            except (ValueError,OSError) as e:
                x={"status":"BAOSTOCK_SOURCE_QUERY_FAILED",
                   "reason":type(e).__name__+":"+str(e)[:120],
                   "reference_valid_both_price_versions":False}
                unadjusted,forward=[],[]
            rows.append({"security_id":sid,**x,"raw_quote_sha256":sha(
                json.dumps({"unadjusted":unadjusted,"forward_adjusted":forward},
                           ensure_ascii=False,sort_keys=True,separators=(",",":")).encode())})
            print(f"PREENTRY {i:03d}/{limit} {sid} "
                  f"{'REFERENCE_OK' if x['reference_valid_both_price_versions'] else 'REFERENCE_ISSUE'}",
                  flush=True)
    finally:
        bs.logout()
    return {
        "schema":SCHEMA,
        "captured_at_utc":datetime.now(timezone.utc).isoformat(),
        "protocol_sha256":protocol_sha,
        "frozen_sample_sha256":protocol["sample"]["sha256_linefeed"],
        "frozen_cohort_count":122,
        "attempted_count":len(rows),
        "historical_reference_session":REFERENCE_DAY,
        "future_sessions_queried":False,
        "stock_reference_bar_both_versions_ok":
            sum(x["reference_valid_both_price_versions"] for x in rows),
        "stock_reference_bar_uncertain_count":
            sum(not x["reference_valid_both_price_versions"] for x in rows),
        "benchmark":index,
        "benchmark_raw_response_sha256":sha(rawindex) if rawindex else None,
        "benchmark_type_price_index_substitution_allowed":False,
        "first_future_reference_close_observed":False,
        "exit_future_reference_close_observed":False,
        "prospective_122_price_outcomes_ready":False,
        "strategy_validated":False,
        "live_buy_eligibility":"NOT_AUTHORIZED",
        "rows":rows,
    }

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--out",type=Path,required=True)
    p.add_argument("--limit",type=int,default=122)
    args=p.parse_args()
    if args.out.exists():
        raise ValueError("NO_OVERWRITE_OF_ORIGINAL_SOURCE_FEASIBILITY")
    import baostock
    result=collect(baostock,args.limit)
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",
                        encoding="utf-8")
    print(json.dumps({
        "frozen_cohort":122,"pre_freeze_bar_coverage":
        result["stock_reference_bar_both_versions_ok"],
        "attempted":result["attempted_count"],
        "official_benchmark_status":result["benchmark"]["benchmark_source_status"],
        "prospective_outcomes_ready":False,
        "live_buy_eligibility":"NOT_AUTHORIZED",
    },ensure_ascii=False))

if __name__=="__main__":
    main()
