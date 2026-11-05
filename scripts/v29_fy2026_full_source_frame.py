#!/usr/bin/env python3
"""Normalize full FY2026/Q3 source populations without selecting growth winners.

Input is immutable raw vendor pages from the existing summary/F10 collectors
and an independently saved market-day source payload. This adapter NEVER
treats absent statements or unverified ST/filings as negative/zero facts.
Research only; no provider-dependent work or future outcome is done here.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from v29_growth_candidate_snapshot import _security
from v29_growth_core_earnings import _decode as decode_core, _select as match_core, _value
from v29_fy2026_next_vintage_selector import select

ANNUAL="2026-12-31"
Q3="2026-09-30"
FY_CUTOFF="2027-05-01"
Q3_CUTOFF="2026-11-01"
SCHEMA="V29_FY2026_NORMALIZED_ALL_A_SOURCE_FRAME_V1"
CN=ZoneInfo("Asia/Shanghai")
CORE_KEYS=("KCFJCXSYJLR","PARENTNETPROFIT")
SUMMARY_KEYS=("YSTZ","SJLTZ","PARENT_NETPROFIT","WEIGHTAVG_ROE","MGJYXJJE","XSMLL")

def digest(raw):
    return hashlib.sha256(raw).hexdigest()

def canonical(obj):
    return (json.dumps(obj,ensure_ascii=False,sort_keys=True,separators=(",",":"))+"\n").encode()

def read_pages(folder):
    files=sorted(Path(folder).glob("page-*.json"))
    if not files or [f.name for f in files]!=[f"page-{i:03d}.json" for i in range(1,len(files)+1)]:
        raise ValueError("SOURCE_PAGE_SERIES_INCOMPLETE")
    return [p.read_bytes() for p in files]

def summary_index(pages,period,cutoff):
    """The existing candidate snapshot filters negatives; never use it as a
    full-universe denominator. Keep EVERY recognized issuer in raw pages."""
    expected=None
    rows=[]
    for i,raw in enumerate(pages,1):
        p=json.loads(raw)
        q=p.get("result")
        if p.get("success") is False or not isinstance(q,dict):
            raise ValueError("INVALID_FINANCIAL_SOURCE")
        count,page_count,data=q.get("count"),q.get("pages"),q.get("data")
        if type(count) is not int or type(page_count) is not int or not isinstance(data,list) or count<1:
            raise ValueError("INVALID_FINANCIAL_PAGINATION")
        if expected is None:expected=(count,page_count)
        if expected!=(count,page_count):raise ValueError("FINANCIAL_PAGINATION_CHANGED")
        rows.extend(data)
    if expected!=(len(rows),len(pages)):
        raise ValueError("FINANCIAL_PAGES_INCOMPLETE")
    index={}
    ignored=0
    for row in rows:
        sid=_security(row)
        if sid is None:
            ignored+=1
            continue
        if sid in index:
            raise ValueError("DUPLICATE_FINANCIAL_ISSUER")
        if str(row.get("REPORTDATE",""))[:10]!=period:
            raise ValueError("FINANCIAL_PERIOD_CHANGED")
        disclosed=str(row.get("NOTICE_DATE") or "")[:10]
        if disclosed and disclosed>=cutoff:
            raise ValueError("DISCLOSURE_AFTER_SOURCE_CUTOFF")
        index[sid]=row
    return index,{"all_provider_rows":len(rows),"recognized_A":len(index),"non_A":ignored,
                  "page_hashes":[digest(x) for x in pages]}

def code_to_security(code):
    if not isinstance(code,str) or len(code)!=9:
        return None
    prefix,symbol=code.split(".",1) if "." in code else ("","")
    if prefix not in ("sh","sz") or len(symbol)!=6 or not symbol.isdigit():
        return None
    sid=_security({"SECUCODE":symbol+("."+"SH" if prefix=="sh" else ".SZ"),
                   "SECURITY_CODE":symbol})
    return sid

def validate_market(market):
    if market.get("schema")!="V29_FY2026_MARKET_REFERENCE_SOURCE_V1":
        raise ValueError("INVALID_MARKET_REFERENCE_SCHEMA")
    calendar=market["calendar"]
    if not isinstance(calendar,list) or not calendar:
        raise ValueError("MISSING_FUTURE_MARKET_CALENDAR")
    by_day={}
    for r in calendar:
        d=date.fromisoformat(r["calendar_date"]).isoformat()
        if d in by_day or r["is_trading_day"] not in ("0","1"):
            raise ValueError("DUPLICATE_OR_INVALID_MARKET_DAY")
        by_day[d]=r["is_trading_day"]
    ref=max((d for d,v in by_day.items() if d<="2027-04-30" and v=="1"),default=None)
    following=min((d for d,v in by_day.items() if d>"2027-04-30" and v=="1"),default=None)
    if not ref or not following:
        raise ValueError("REFERENCE_OR_FIRST_SESSION_UNAVAILABLE")
    if market.get("official_calendar_verified") is True:
        proof=market.get("official_schedule_record") or {}
        if (proof.get("source_type")!="OFFICIAL_EXCHANGE_SCHEDULE"
                or proof.get("reference_trading_session")!=ref
                or proof.get("first_trading_session")!=following
                or not proof.get("source_url","").startswith(
                    ("https://www.sse.com.cn/","https://www.szse.cn/"))):
            raise ValueError("OFFICIAL_SCHEDULE_ATTESTATION_REQUIRED")
    # Exchange dates in the seam must be continuous, not assumed weekdays.
    dates=sorted(d for d in by_day if ref<=d<=following)
    expected=[(date.fromisoformat(ref).toordinal()+i)
              for i in range(date.fromisoformat(following).toordinal()-date.fromisoformat(ref).toordinal()+1)]
    if [date.fromisoformat(d).toordinal() for d in dates]!=expected:
        raise ValueError("MARKET_CALENDAR_GAP")
    listed={}
    for r in market["all_stock"]:
        sid=code_to_security(r.get("code"))
        if sid is None:continue
        if sid in listed:raise ValueError("DUPLICATE_LISTED_SECURITY")
        listed[sid]=r
    if not listed:raise ValueError("EMPTY_MARKET_A_SHARE_UNIVERSE")
    bars={}
    for r in market["reference_bars"]:
        sid=code_to_security(r.get("code"))
        if sid is None:raise ValueError("INVALID_REFERENCE_BAR_SECURITY")
        if sid in bars:raise ValueError("DUPLICATE_REFERENCE_BAR")
        if (r.get("date")!=ref or r.get("adjustflag")!="3"
                or sid not in listed):
            raise ValueError("REFERENCE_BAR_DATE_VINTAGE_OR_IDENTITY_INVALID")
        bars[sid]=r
    return ref,following,listed,bars

def build(annual_pages,q3_pages,annual_core_pages,q3_core_pages,market,captured_at):
    capture=datetime.fromisoformat(captured_at)
    if capture.tzinfo is None or capture.utcoffset() is None:
        raise ValueError("AWARE_CAPTURE_TIMESTAMP_REQUIRED")
    if capture.astimezone(CN).date()<date(2027,5,1):
        raise ValueError("FUTURE_YEAR_ANNUAL_SOURCE_NOT_OBSERVABLE")
    annual,audit_annual=summary_index(annual_pages,ANNUAL,FY_CUTOFF)
    q3,audit_q3=summary_index(q3_pages,Q3,Q3_CUTOFF)
    core_ann,ann_hashes,ann_count=decode_core(annual_core_pages,ANNUAL,FY_CUTOFF)
    core_q3,q3_hashes,q3_count=decode_core(q3_core_pages,Q3,Q3_CUTOFF)
    ref,first,listed,bars=validate_market(market)
    if capture.astimezone(CN)>=datetime.fromisoformat(first+"T09:30:00+08:00"):
        raise ValueError("MARKET_SOURCE_AFTER_FIRST_TRADING_OPEN")
    rows=[]
    missing={"annual_summary":0,"q3_summary":0,"annual_core":0,
             "q3_core":0,"reference_bar":0,"st_unknown":0}
    for sid in sorted(listed):
        ann=annual.get(sid)
        prior=q3.get(sid)
        ca,issue_ann=match_core(core_ann,sid,ann,FY_CUTOFF) if ann else (None,"MISSING_ANNUAL_SUMMARY")
        cp,issue_q3=match_core(core_q3,sid,prior,Q3_CUTOFF) if prior else (None,"MISSING_Q3_SUMMARY")
        bar=bars.get(sid)
        live=(bar is not None and bar.get("tradestatus")=="1"
              and bar.get("isST")=="0"
              and (_value(bar,"volume") or 0)>0
              and (_value(bar,"close") or 0)>0)
        ann_parent=_value(ann,"PARENT_NETPROFIT") if ann else None
        ann_core=_value(ca,"KCFJCXSYJLR") if ca else None
        doc={
            "security_id":sid,"annual_period":ANNUAL,"q3_period":Q3,
            "annual_disclosure_date":str(ann.get("NOTICE_DATE") or "")[:10] if ann else None,
            "q3_disclosure_date":str(prior.get("NOTICE_DATE") or "")[:10] if prior else None,
            "source_original_filing_verified":False,
            "reference_close_session":ref,
            "reference_close_cny":_value(bar,"close") if bar else None,
            "is_st_at_reference_session":False if live else None,
            "annual_revenue_yoy_pct":_value(ann,"YSTZ") if ann else None,
            "q3_ytd_revenue_yoy_pct":_value(prior,"YSTZ") if prior else None,
            "annual_parent_profit_yuan":ann_parent,
            "annual_parent_profit_yoy_pct":_value(ann,"SJLTZ") if ann else None,
            "q3_ytd_parent_profit_yoy_pct":_value(prior,"SJLTZ") if prior else None,
            "annual_deducted_parent_profit_yuan":ann_core,
            "q3_ytd_deducted_parent_profit_yuan":_value(cp,"KCFJCXSYJLR") if cp else None,
            "annual_roe_pct":_value(ann,"WEIGHTAVG_ROE") if ann else None,
            "annual_cfo_per_share_yuan":_value(ann,"MGJYXJJE") if ann else None,
            "annual_gross_margin_pct":_value(ann,"XSMLL") if ann else None,
            "q3_ytd_gross_margin_pct":_value(prior,"XSMLL") if prior else None,
            "annual_nonrecurring_parent_profit_yuan":ann_parent-ann_core
                if ann_parent is not None and ann_core is not None else None,
            "annual_core_source_status":"MATCHED" if ca else issue_ann,
            "q3_core_source_status":"MATCHED" if cp else issue_q3
        }
        for key,condition in (
            ("annual_summary",not ann),("q3_summary",not prior),
            ("annual_core",not ca),("q3_core",not cp),
            ("reference_bar",bar is None),("st_unknown",not live)):
            if condition:missing[key]+=1
        rows.append(doc)
    market_raw=canonical(market)
    return {"schema":SCHEMA,"report_period":ANNUAL,"comparison_period":Q3,
            "financial_coverage_status":"COMPLETE_VENDOR_ALL_A_CROSS_SECTION",
            "market_calendar_verified":market.get("official_calendar_verified") is True,
            "market_calendar_provenance":("OFFICIAL_EXCHANGE_SCHEDULE_LINK_AND_DATE_ATTESTATION_NOT_AUTOMATICALLY_AUTHENTICATED"
                                         if market.get("official_calendar_verified") is True
                                         else "BAOSTOCK_VENDOR_CALENDAR_ONLY"),
            "source_original_filings_available":False,
            "reference_close_session":ref,
            "first_trading_session_after_cutoff":first,
            "captured_at":capture.isoformat(),
            "raw_source_sha256":{
                "annual":digest(b"".join(annual_pages+annual_core_pages)),
                "q3":digest(b"".join(q3_pages+q3_core_pages)),
                "reference_prices":digest(canonical(market["reference_bars"])),
                "calendar":digest(canonical(market["calendar"]))
            },
            "all_source_counts":{"annual_summary":audit_annual,"q3_summary":audit_q3,
                                 "annual_core_raw_rows":ann_count,
                                 "q3_core_raw_rows":q3_count,
                                 "universe_listed_A":len(listed),
                                 "reference_bars":len(bars),
                                 "missing_by_field_source":missing,
                                 "market_source_sha256":digest(market_raw)},
            "universe_source_count":len(listed),
            "rows":rows,"live_buy_eligibility":"NOT_AUTHORIZED"}

def main():
    cli=argparse.ArgumentParser()
    for arg in ("annual-summary","q3-summary","annual-core","q3-core"):
        cli.add_argument("--"+arg,required=True,type=Path)
    cli.add_argument("--market",required=True,type=Path)
    cli.add_argument("--out",required=True,type=Path)
    cli.add_argument("--select-out",type=Path)
    args=cli.parse_args()
    if args.out.exists() or args.select_out and args.select_out.exists():
        raise ValueError("NO_OVERWRITE_SOURCE_FRAME_OR_FROZEN_SELECTION")
    from datetime import datetime
    market=json.loads(args.market.read_bytes())
    now=datetime.now(CN)
    result=build(read_pages(args.annual_summary),read_pages(args.q3_summary),
                 read_pages(args.annual_core),read_pages(args.q3_core),
                 market,now.isoformat())
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    if args.select_out:
        selected=select(result,now)
        args.select_out.parent.mkdir(parents=True,exist_ok=True)
        args.select_out.write_text(json.dumps(selected,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"universe":len(result["rows"]),
        "missing":result["all_source_counts"]["missing_by_field_source"],
        "calendar_verified":result["market_calendar_verified"],
        "selection_requested":bool(args.select_out),"live_buy_eligibility":"NOT_AUTHORIZED"}))

if __name__=="__main__":
    main()
