#!/usr/bin/env python3
"""One read-only 2022-2025 historical free-data capability pilot, NOT a backtest.

BaoStock quotes are fetched in 2026: a historical row's date is NOT its capture
or disclosure-time vintage. The original company filing must be separately
archived and first eligible on the session AFTER actual publication date.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from datetime import date, datetime, timezone
from pathlib import Path

CANDIDATES = (
    {"security_id":"SZSE:300408", "baostock":"sz.300408",
     "issuer":"三环集团","financial_period_end":"2024-12-31",
     "initial_report_announcement":"2025-04-24",
     "filing_url":"https://static.cninfo.com.cn/finalpage/2025-04-24/1223237532.PDF"},
    {"security_id":"SSE:688002", "baostock":"sh.688002",
     "issuer":"睿创微纳","financial_period_end":"2024-12-31",
     "initial_report_announcement":"2025-04-11",
     "filing_url":"https://static.cninfo.com.cn/finalpage/2025-04-11/1223058665.PDF"}
)
FIELDS="date,code,close,volume,amount,adjustflag,tradestatus,peTTM,pbMRQ,isST"
YEARS=(2022,2023,2024,2025)


def first_eligible_session(fiscal_period_end, notice_day, exchange_calendar):
    """Conservatively avoid using any filing on same-day close, whatever its time."""
    period=date.fromisoformat(fiscal_period_end)
    notice=date.fromisoformat(notice_day)
    if notice<=period:
        raise ValueError("REPORT_PUBLISHED_BEFORE_FISCAL_PERIOD_END")
    future=sorted({date.fromisoformat(d) for d in exchange_calendar
                   if date.fromisoformat(d)>notice})
    if not future:
        raise ValueError("NO_VERIFIED_POST_NOTICE_TRADING_SESSION")
    return future[0].isoformat()


def _historical_sample(rows, year, expected_code):
    """Validate raw vendor row identity and sample dates once."""
    observed=set()
    summary={"year":year,"rows":0,"active_trading_sessions":0,
             "nonempty_pe_ttm":0,"nonempty_pb_mrq":0,
             "first_bar":None,"last_bar":None}
    for row in rows:
        day=date.fromisoformat(row["date"])
        if row.get("code")!=expected_code or day.year!=year or day.month!=4:
            raise ValueError("HISTORICAL_VENDOR_IDENTITY_OR_DATE_CHANGED")
        if day in observed:
            raise ValueError("DUPLICATE_HISTORICAL_VENDOR_SESSION")
        observed.add(day)
        if row.get("adjustflag")!="3":
            raise ValueError("UNEXPECTED_ADJUSTED_PRICE_VINTAGE")
        if row.get("tradestatus")=="1":
            summary["active_trading_sessions"]+=1
        close=row.get("close")
        if close not in ("",None) and (not math.isfinite(float(close)) or float(close)<=0):
            raise ValueError("INVALID_HISTORICAL_PRICE")
        for field,out in (("peTTM","nonempty_pe_ttm"),("pbMRQ","nonempty_pb_mrq")):
            val=row.get(field)
            if val not in ("",None):
                x=float(val)
                if math.isfinite(x) and x>0:
                    summary[out]+=1
        summary["rows"]+=1
    if observed:
        summary["first_bar"]=min(observed).isoformat()
        summary["last_bar"]=max(observed).isoformat()
    return summary


def _read_result(rs):
    if rs.error_code!="0":
        raise ValueError("BAOSTOCK_QUERY_FAILED:"+str(rs.error_msg))
    out=[]
    while rs.next():
        out.append(dict(zip(rs.fields,rs.get_row_data())))
    return out


def collect(out_dir, baostock_module):
    if out_dir.exists():
        raise ValueError("NO_OVERWRITE_OF_HISTORICAL_SOURCE_SNAPSHOT")
    bs=baostock_module
    status=bs.login()
    if status.error_code!="0":
        raise ValueError("BAOSTOCK_LOGIN_FAILED:"+str(status.error_msg))
    try:
        calendar=_read_result(bs.query_trade_dates(start_date="2025-04-01",end_date="2025-05-12"))
        sessions=[r["calendar_date"] for r in calendar if r.get("is_trading_day")=="1"]
        if len(sessions)<15:
            raise ValueError("HISTORICAL_EXCHANGE_CALENDAR_TOO_SPARSE")
        all_rows=[]
        summary=[]
        for company in CANDIDATES:
            first=first_eligible_session(company["financial_period_end"],
                                         company["initial_report_announcement"],sessions)
            if first<=company["initial_report_announcement"]:
                raise ValueError("REPORT_LEAKED_INTO_SAME_SESSION")
            company_summary={"issuer":company["issuer"],"security_id":company["security_id"],
                             "report_period_end":company["financial_period_end"],
                             "reported_announcement_date":company["initial_report_announcement"],
                             "first_conservative_signal_session":first,
                             "original_disclosure_url":company["filing_url"],
                             "raw_source_pdf_sha256":None,"original_pdf_bytes_preserved":False,
                             "sample_by_year":[]}
            for y in YEARS:
                rows=_read_result(bs.query_history_k_data_plus(
                    company["baostock"],FIELDS,start_date=f"{y}-04-01",
                    end_date=f"{y}-04-30",frequency="d",adjustflag="3"))
                company_summary["sample_by_year"].append(
                    _historical_sample(rows,y,company["baostock"]))
                all_rows.append({"issuer":company["security_id"],"year":y,"data":rows})
            summary.append(company_summary)
    finally:
        bs.logout()
    raw=(json.dumps({"calendar":calendar,"quotes":all_rows},ensure_ascii=False,
                    separators=(",",":"),sort_keys=True)+"\n").encode()
    result={"schema":"V29_2022_2025_FREE_HISTORICAL_SOURCE_PILOT_V1",
            "captured_at":datetime.now(timezone.utc).isoformat(),
            "source":"BaoStock_free_public_data","source_package_pin":"baostock==0.9.4",
            "raw_records_sha256":hashlib.sha256(raw).hexdigest(),
            "sample":summary,
            "external_pdf_vintage_certified":False,
            "historical_market_data_asof_2022_2025_certified":False,
            "full_market_universe_2022_2025_certified":False,
            "complete_dividend_reinvestment_or_total_return_data":False,
            "historical_factor_oos_validated":False,
            "backtest_executed":False,
            "strategy_validated":False,
            "live_buy_eligibility":"NOT_AUTHORIZED"}
    out_dir.mkdir(parents=True)
    (out_dir/"raw_quotes_and_calendar.json").write_bytes(raw)
    (out_dir/"pilot_receipt.json").write_text(
        json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return result


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--output-dir",required=True,type=Path)
    a=p.parse_args()
    import baostock as bs
    data=collect(a.output_dir,bs)
    print(json.dumps(data,ensure_ascii=False,indent=2))


if __name__=="__main__":
    main()
