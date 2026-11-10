#!/usr/bin/env python3
"""Verify observed closed-session market context for the frozen 8 stocks.

No account, trade placement, stop-loss inference, or order price. Quotes from
retrospective BaoStock are vendor observations only, not exchange-certified or
executable limit-order fills. Reuses the already sealed 8/122 identity.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
from datetime import datetime,timezone
from pathlib import Path

from v29_eight_portfolio_capacity import sealed_readiness
from v29_2025_filing_to_return_case import records

ROOT=Path(__file__).resolve().parents[1]
DAY="2026-11-10"
START="2026-11-06"
SCHEMA="V31_EIGHT_FIXED_NAMES_20261110_CLOSED_SESSION_CONTEXT_V1"
FIELDS="date,code,open,high,low,close,preclose,volume,amount,adjustflag,tradestatus,pctChg,isST"


def security_code(sid):
    venue,code=sid.split(":")
    if venue not in ("SSE","SZSE") or len(code)!=6 or not code.isdecimal():
        raise ValueError("INVALID_SEALED_SECURITY_ID")
    return ("sh." if venue=="SSE" else "sz.")+code


def parse_positive(row,key):
    try:
        v=float(row[key])
    except (KeyError,ValueError,TypeError):
        return None
    return v if math.isfinite(v) and v>0 else None


def evaluate(reference,observed,target=DAY):
    ids=[x["security_id"] for x in reference["names_in_original_registered_order"]]
    if (reference["schema"]!="V29_EIGHT_FROZEN_REAL_ENTRY_DECISION_READINESS_V1"
        or reference["names"]!=8 or len(set(ids))!=8 or set(observed)!=set(ids)
        or reference["live_buy_eligibility"]!="NOT_AUTHORIZED"):
        raise ValueError("ORIGINAL_EIGHT_SOURCE_CHANGED")
    out=[]
    for expected in reference["names_in_original_registered_order"]:
        sid=expected["security_id"]
        quotes=observed[sid]
        if not isinstance(quotes,list):
            raise ValueError("QUOTE_QUERY_NOT_A_LIST:"+sid)
        by_date={}
        for row in quotes:
            d=row["date"]
            if (row.get("code")!=security_code(sid) or d in by_date
                or d>target or not START<=d):
                raise ValueError("BAR_ID_DATE_OR_DUPLICATE:"+sid)
            if row.get("adjustflag")!="3":
                raise ValueError("BAR_NOT_UNADJUSTED:"+sid)
            by_date[d]=row
        q=by_date.get(target)
        latest=max(by_date) if by_date else None
        status="EOD_VENDOR_BAR_MISSING"
        close=None
        amount=None
        one_lot=None
        if q is not None:
            close=parse_positive(q,"close")
            vol=parse_positive(q,"volume")
            amount=parse_positive(q,"amount")
            if q.get("tradestatus")!="1":
                status="VENDOR_SUSPENSION_OR_NOT_ACTIVE"
            elif q.get("isST")=="1":
                status="VENDOR_ST_FLAG"
            elif q.get("isST")!="0":
                status="VENDOR_ST_UNKNOWN"
            elif close is None or vol is None or amount is None:
                status="EOD_PRICE_OR_TRADING_AMOUNT_INVALID"
            else:
                status="EOD_BAR_PRESENT_NOT_FILL_CERTIFIED"
                one_lot=round(expected["minimum_lot_shares"]*close,2)
        out.append({
            "security_id":sid,
            "board":expected["board"],
            "minimum_lot_shares":expected["minimum_lot_shares"],
            "original_paper_entry_2026_11_02_close_cny":expected["sealed_2026_11_02_entry_close_cny"],
            "latest_vendor_bar_date":latest,
            "target_2026_11_10_eod_close_cny":close,
            "eod_traded_amount_cny_vendor":amount,
            "one_lot_eod_notional_cny":one_lot,
            "status":status,
            "limit_up_or_down_order_eligibility_verified":False,
            "board_permission_broker_confirmed":False,
            "cash_and_position_limits_broker_confirmed":False,
            "buy_fill_certified":False,
            "trade_authorized":False,
        })
    complete=all(x["status"]=="EOD_BAR_PRESENT_NOT_FILL_CERTIFIED" for x in out)
    total=round(sum(x["one_lot_eod_notional_cny"] for x in out),2) if complete else None
    return {
        "schema":SCHEMA,
        "target_session":target,
        "source":"BAOSTOCK_RETROSPECTIVE_UNADJUSTED_A_SHARE_DAILY_BAR_NOT_OFFICIAL",
        "source_observation_is_closing_reference_not_order_fill":True,
        "original_eight_frozen_sealed_entry_sha256":reference["source_entry_sha256"],
        "frozen_eight_identities_preserved":True,
        "sample_count":len(out),
        "nonst_positive_volume_quote_count":sum(x["status"]=="EOD_BAR_PRESENT_NOT_FILL_CERTIFIED" for x in out),
        "basket_min_lot_eod_notional_cny_if_complete":total,
        "buyer_side_order_limit_or_halt_tradability_certified":False,
        "personal_account_and_permissions_available":False,
        "profit_predictability_proven":False,
        "original_financial_signal_independently_validated":False,
        "live_buy_eligibility":"NOT_AUTHORIZED",
        "trade_authorized":False,
        "rows":out,
    }


def capture(bs,out):
    out=Path(out)
    if out.exists():raise ValueError("REFUSE_OVERWRITE_EIGHT_EOD_VINTAGE")
    baseline=sealed_readiness()
    login=bs.login()
    if login.error_code!="0":raise ValueError("BAOSTOCK_LOGIN_FAILED")
    raw={}
    try:
        for r in baseline["names_in_original_registered_order"]:
            sid=r["security_id"]
            try:
                raw[sid]=records(bs.query_history_k_data_plus(
                    security_code(sid),FIELDS,start_date=START,end_date=DAY,
                    frequency="d",adjustflag="3"))
            except (OSError,ValueError,KeyError) as exc:
                raw[sid]=[]
                print("QUOTE_SOURCE_UNAVAILABLE",sid,type(exc).__name__,flush=True)
    finally:
        bs.logout()
    captured_at=datetime.now(timezone.utc).isoformat()
    source={"captured_at_utc":captured_at,"fields":FIELDS,"start":START,
            "end":DAY,"vendor":"baostock==0.9.4",
            "raw":raw}
    blob=(json.dumps(source,ensure_ascii=False,sort_keys=True,separators=(",",":"))+"\n").encode()
    out.mkdir(parents=True)
    (out/"RAW_EIGHT_EOD_SOURCE.json.gz").write_bytes(gzip.compress(blob,mtime=0))
    report=evaluate(baseline,raw)
    report["captured_at_utc"]=captured_at
    report["original_raw_source_sha256"]=hashlib.sha256(blob).hexdigest()
    (out/"RESULT.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({key:report[key] for key in ("sample_count","target_session",
           "nonst_positive_volume_quote_count","basket_min_lot_eod_notional_cny_if_complete",
           "live_buy_eligibility","trade_authorized")},ensure_ascii=False),flush=True)


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--out",type=Path,required=True)
    args=p.parse_args()
    import baostock
    capture(baostock,args.out)


if __name__=="__main__":
    main()
