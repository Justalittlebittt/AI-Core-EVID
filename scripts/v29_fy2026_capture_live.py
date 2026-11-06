#!/usr/bin/env python3
"""One-time future FY26 free-source capture, with finance-first quote economy.

Reuses the existing two Eastmoney raw collectors, BaoStock exchange calendar,
as-of full-stock listing and ONE raw bar only for financially plausible names.
No scheduled job; don't attempt before FY26 reports or after first entry open.
All market names are retained, even without a financial report or price.
"""
from __future__ import annotations
import argparse
import hashlib
import io
import json
import tarfile
from datetime import datetime, date, timedelta
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

ORIGINAL_Q3_DIR=Path(__file__).resolve().parents[1]/"research/v29_2026q3_original_vendor_sources_20261030"
ORIGINAL_Q3_RECEIPT="SOURCE_VINTAGE_RECEIPT.json"


def load_sealed_q3(root=ORIGINAL_Q3_DIR):
    """Reuse actual 2026-10-30 raw Q3/F10 disclosure vintage, never 2027 vendor restatements.

    The source is NOT the fully disclosed Oct 31 Q3 universe. Issuers absent
    at the 2026-10-29 disclosure cutoff remain missing, not retrofilled.
    """
    root=Path(root)
    receipt_bytes=(root/ORIGINAL_Q3_RECEIPT).read_bytes()
    receipt=json.loads(receipt_bytes)
    if (receipt.get("schema")!="V29_20261030_ORIGINAL_VENDOR_Q3_AND_CORE_ARCHIVE_V1"
            or receipt.get("acquired_on")!="2026-10-30"
            or receipt.get("disclosure_cutoff_exclusive")!="2026-10-30"
            or receipt.get("coverage_limited_to_original_vendor_asof_20261029") is not True):
        raise ValueError("Q3_ORIGINAL_2026_SOURCE_VINTAGE_NOT_CERTIFIED")
    sources={s["source"]:s for s in receipt["source_archives"]}
    if set(sources)!={"growth","core"}:
        raise ValueError("Q3_EXPECTED_ORIGINAL_VENDOR_SOURCE_PAIR_MISSING")
    restored={}
    for name,prefix in (("growth","growth-cutoff-raw/latest"),
                        ("core","core-q3h1/latest")):
        source=sources[name]
        archive_bytes=(root/source["preserved_archive"]).read_bytes()
        if hashlib.sha256(archive_bytes).hexdigest()!=source["preserved_archive_sha256"]:
            raise ValueError("ORIGINAL_"+name+"_ARCHIVE_SHA_MISMATCH")
        with tarfile.open(fileobj=io.BytesIO(archive_bytes),mode="r:gz") as z:
            members={m.name:m for m in z.getmembers() if m.isfile()}
            manifest={v["path"]:v for v in source["files"]}
            if len(manifest)!=source["file_count"] or set(members)!=set(manifest):
                raise ValueError("ORIGINAL_"+name+"_MANIFEST_MISMATCH")
            pages=[]
            for key in sorted(x for x in members if x.startswith(prefix+"/page-") and x.endswith(".json")):
                b=z.extractfile(members[key]).read()
                if (len(b)!=manifest[key]["bytes"]
                        or hashlib.sha256(b).hexdigest()!=manifest[key]["sha256"]):
                    raise ValueError("ORIGINAL_"+name+"_RAW_PAGE_SHA_MISMATCH")
                pages.append(b)
            if not pages or len(pages)>100:
                raise ValueError("ORIGINAL_"+name+"_Q3_RAW_PAGES_UNAVAILABLE")
            if [int(x.split("page-")[-1].split(".")[0]) for x in
                sorted(y for y in members if y.startswith(prefix+"/page-") and y.endswith(".json"))]!=list(range(1,len(pages)+1)):
                raise ValueError("ORIGINAL_"+name+"_Q3_PAGE_SEQUENCE_INVALID")
        restored[name]=pages
    provenance={
        "identity":"2026-10-30_DISCLOSURE_CUTOFF_2026-10-29_ORIGINAL_VENDOR",
        "source_vintage_date":"2026-10-30",
        "disclosure_cutoff_exclusive":"2026-10-30",
        "q3_2026_late_oct30_oct31_not_covered":True,
        "q3_values_queried_again_in_2027":False,
        "source_receipt_sha256":hashlib.sha256(receipt_bytes).hexdigest(),
        "source_git_archive_sha256":{k:sources[k]["preserved_archive_sha256"] for k in ("growth","core")},
    }
    return restored["growth"],restored["core"],provenance


def last_preopen_capture_day(first_session):
    """Use latest scheduled 2027 May 1-5 opportunity before first market open.

    Does not alter the frozen selection rule or assume May 6 is a holiday
    verified by an exchange. True next session comes from a vendor calendar;
    unverified results retain their provisional provenance.
    """
    next_day=date.fromisoformat(first_session)
    return min(next_day-timedelta(days=1),date(2027,5,5))


def preflight(bs,now):
    """Cheap one-time source-date gate before any 2027 financial HTTP fetch."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("AWARE_CAPTURE_TIME_REQUIRED")
    day=now.astimezone(CN).date()
    if day<date(2027,5,1) or day>date(2027,5,5):
        raise ValueError("OUTSIDE_BOUNDED_2027_FINANCIAL_CAPTURE_WINDOW")
    response=bs.login()
    if response.error_code!="0":
        raise ValueError("BAOSTOCK_CALENDAR_LOGIN_FAILED")
    try:
        calendar=records(bs.query_trade_dates(start_date="2027-04-25",end_date="2027-05-12"))
    finally:
        bs.logout()
    upcoming=min((r["calendar_date"] for r in calendar
                  if r.get("is_trading_day")=="1" and r["calendar_date"]>"2027-04-30"),
                 default=None)
    if upcoming is None:
        raise ValueError("FUTURE_FIRST_EXCHANGE_SESSION_UNKNOWN")
    last=last_preopen_capture_day(upcoming)
    return {"capture_today":day==last,
            "first_trading_session":upcoming,
            "last_preopen_scheduled_day":last.isoformat(),
            "date_checked":day.isoformat(),
            "calendar_source":"BAOSTOCK_UNVERIFIED_VENDOR_CALENDAR"}


def capture(bs,now,summary_collector=collect_summary,core_collector=collect_core,official_calendar=None,clock=None,q3_source_loader=load_sealed_q3):
    if not isinstance(now,datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("AWARE_CAPTURE_TIME_REQUIRED")
    local=now.astimezone(CN)
    if local.date()<date(2027,5,1):
        raise ValueError("FY2026_ANNUAL_DATA_NOT_YET_ELIGIBLE")
    plan,_=plan_source()
    # Keep raw pages, not only the existing positive-growth candidate summaries.
    _,annual=summary_collector("2026-12-31",notice_before="2027-05-01")
    annual_core=core_collector("2026-12-31","2027-05-01")
    # DO NOT requery Q3 in 2027: historical rows could be restated and cannot
    # reconstruct what the October 2026 screening could actually observe.
    q3,q3_core,q3_provenance=q3_source_loader()
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
    frame["q3_original_source_vintage"]=q3_provenance
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
        filename=("FROZEN_EIGHT_RESEARCH_ONLY.json" if candidate.get("calendar_officially_verified")
                  else "PROVISIONAL_EIGHT_RESEARCH_ONLY.json")
        (out/filename).write_text(
            json.dumps(candidate,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--out-dir",type=Path)
    parser.add_argument("--official-calendar",type=Path)
    parser.add_argument("--preflight",action="store_true")
    args=parser.parse_args()
    import baostock
    if args.preflight:
        print(json.dumps(preflight(baostock,datetime.now(CN)),ensure_ascii=False))
        return
    if args.out_dir is None:
        parser.error("--out-dir is required except in --preflight mode")
    if args.out_dir.exists():
        raise ValueError("NO_OVERWRITE_FUTURE_FINANCIAL_EVIDENCE")
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
