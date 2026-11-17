#!/usr/bin/env python3
"""2018-2020 development-only, fixed Q3 top10 conditional trading economics.

Uses pinned source-only 2018/19/20 candidate JSON, BaoStock daily UNADJUSTED bars,
and official H00300 total-return daily index. Never opens 2021/2022 evaluation.
Not OOS, NOT real auction fill, NOT actual economic TR without corporate actions.
"""
import argparse
import hashlib
import json
import math
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

import baostock as bs

from v29_2025_filing_to_return_case import records
from v31_csi300_tr_2020_source_probe import URL, HEADERS

SOURCE="research/V3.1_Q3_QUALITY_GROWTH_PREOUTCOME_SPEC_20261117.json"
FIELDS="date,code,open,close,preclose,high,low,tradestatus,isST,volume"
YEARS=(2018,2019,2020)
WINDOWS={y:(f"{y}-11-01",f"{y+1}-01-15") for y in YEARS}

def finite(row,field):
    try: v=float(row[field])
    except (TypeError,ValueError,KeyError) as e: raise ValueError("MISSING_NUMERIC_"+field) from e
    if not math.isfinite(v) or v<=0:raise ValueError("NONPOSITIVE_"+field)
    return v

def official_h00300(year):
    start,end=WINDOWS[year]
    query={"indexCode":"H00300","startDate":start.replace("-",""),"endDate":end.replace("-","")}
    req=urllib.request.Request(URL+"?"+urllib.parse.urlencode(query),headers=HEADERS)
    try:
        with urllib.request.urlopen(req,timeout=35) as response:
            raw=response.read(3_000_001)
        if len(raw)>3_000_000:raise ValueError("BENCHMARK_RESPONSE_TOO_LARGE")
        obj=json.loads(raw)
        data=obj.get("data")
        if not isinstance(data,list):raise ValueError("BENCHMARK_DATA_SHAPE")
        rows={}
        for x in data:
            if str(x.get("indexCode"))!="H00300":raise ValueError("BENCHMARK_INDEX_IDENTITY")
            d=str(x["tradeDate"]).replace("-","")
            if not query["startDate"]<=d<=query["endDate"] or d in rows:raise ValueError("BENCHMARK_DATE_OR_DUPLICATE")
            rows[d]=finite(x,"close")
        return rows,{"status":"SOURCE_AVAILABLE","sha256":hashlib.sha256(raw).hexdigest(),"count":len(rows)}
    except (OSError,ValueError,TypeError,KeyError) as exc:
        return {},{"status":"SOURCE_UNAVAILABLE","failure_type":type(exc).__name__,"message":str(exc)[:150]}

def trade_status(bar,side):
    if bar is None:return "MISSING_BAR"
    if bar.get("tradestatus")!="1":return "NOT_TRADING"
    if bar.get("isST")!="0":return "ST_OR_UNKNOWN"
    try:
        if finite(bar,"volume")<=0:return "NO_VOLUME"
        op=finite(bar,"open")
        cl=finite(bar,"close")
        prev=finite(bar,"preclose")
        if side=="BUY" and op>=prev*1.099:
            return "OPEN_NEAR_LIMIT_UP_UNVERIFIED_FILL"
        if side=="SELL" and cl<=prev*0.901:
            return "CLOSE_NEAR_LIMIT_DOWN_UNVERIFIED_FILL"
    except ValueError:return "BAD_PRICE_OR_VOLUME"
    return "POSSIBLE_BAR_LEVEL_ONLY"

def one_year(year,candidates,calendar,bars,benchmark,benchmark_receipt,config):
    sessions=sorted(date.fromisoformat(x["calendar_date"]) for x in calendar
                    if x.get("is_trading_day")=="1")
    after=[s for s in sessions if s>date(year,11,15)]
    if len(after)<20:return {"year":year,"status":"INCOMPLETE_CALENDAR"}
    entry,exit=after[0],after[19]
    ekey,xkey=entry.isoformat(),exit.isoformat()
    holdings=[]
    n=len(candidates)
    initial_cash=float(config["initial_cash_cny"])
    target=initial_cash/n
    total_entry_cost=0.0
    total_exit_proceeds=0.0
    for rank,signal in enumerate(candidates,1):
        sid=signal["symbol"]
        code=sid[-2:].lower()+"."+sid[:6]
        observed=bars.get(sid,{})
        b0=observed.get(ekey)
        b1=observed.get(xkey)
        buy=trade_status(b0,"BUY")
        sell=trade_status(b1,"SELL")
        record={"rank":rank,"security_id":sid,"entry_status":buy,"exit_status":sell}
        if buy=="POSSIBLE_BAR_LEVEL_ONLY" and sell=="POSSIBLE_BAR_LEVEL_ONLY":
            open_price=finite(b0,"open")
            close_price=finite(b1,"close")
            sl=float(config["transaction_costs"]["slippage_each_side_fraction"])
            buy_price=open_price*(1+sl)
            qty=math.floor(target/buy_price/100)*100
            if qty<=0:
                record["entry_status"]="LOT_PRICE_EXCEEDS_TARGET_ALLOCATION"
            else:
                fee_rate=float(config["transaction_costs"]["commission_rate_each_side"])
                fee_min=float(config["transaction_costs"]["min_commission_cny_each_side"])
                tr=float(config["transaction_costs"]["sh_transfer_rate_each_side"]) if sid.endswith(".SH") else 0
                buy_gross=qty*buy_price
                buy_fee=max(fee_min,buy_gross*fee_rate)+buy_gross*tr
                while qty>0 and buy_gross+buy_fee>target:
                    qty-=100
                    buy_gross=qty*buy_price
                    buy_fee=max(fee_min,buy_gross*fee_rate)+buy_gross*tr
                if qty<=0:
                    record["entry_status"]="LOT_AND_FEES_EXCEED_TARGET_ALLOCATION"
                else:
                    sell_gross=qty*close_price*(1-sl)
                    sell_fee=max(fee_min,sell_gross*fee_rate)+sell_gross*tr
                    # In 2018-2020 the actual historic stamp duty was 0.1%.
                    actual_st=0.001
                    sell_fee+=sell_gross*actual_st
                    # All entries are funded simultaneously, without future exit cash.
                    total_entry_cost+=buy_gross+buy_fee
                    total_exit_proceeds+=sell_gross-sell_fee
                    record.update({"quantity":qty,"raw_open":open_price,"raw_close":close_price,
                       "hypothetical_buy_cost":round(buy_gross+buy_fee,2),
                       "hypothetical_sell_proceeds":round(sell_gross-sell_fee,2),
                       "historical_stamp_duty_rate_used":actual_st})
        holdings.append(record)
    blocked=[r for r in holdings if "quantity" not in r]
    be=benchmark.get(entry.strftime("%Y%m%d"))
    bx=benchmark.get(exit.strftime("%Y%m%d"))
    bret=(bx/be-1) if be and bx else None
    # Entry trade uses opening auction; H00300 is daily closing level. Incomparable.
    return {"year":year,"status":"CONDITIONAL_DEV_ONLY_INCOMPLETE" if blocked or bret is None
                     else "CONDITIONAL_DEV_ONLY_NOT_EXECUTION_CERTIFIED",
            "entry_session":ekey,"exit_session":xkey,"candidate_count":n,
            "possible_bar_level_trade_count":n-len(blocked),"blocked_count":len(blocked),
            "holdings":holdings,
            "conditional_portfolio_return_assuming_buy_sell_fills_and_no_corporate_actions":
               ((initial_cash-total_entry_cost+total_exit_proceeds)/initial_cash-1) if not blocked else None,
            "official_h00300_close_close_return_different_entry_timestamp":bret,
            "benchmark_receipt":benchmark_receipt,
            "comparable_after_cost_alpha":None,
            "corporate_actions_and_cash_dividends_verified":False,
            "real_auction_queue_fills_verified":False}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--candidates",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    args=p.parse_args()
    src=json.loads(args.candidates.read_bytes())
    spec=json.loads(Path(SOURCE).read_bytes())
    if src["schema"]!="V31_Q3_GROWTH_SOURCE_ONLY_PREFLIGHT_V1":raise ValueError("WRONG_CANDIDATE_SOURCE")
    if spec["period"]["development_descriptive"]!=list(YEARS):raise ValueError("WRONG_DEV_YEARS")
    if spec["execution"]["initial_cash_cny"]!=100000:raise ValueError("CHANGED_CASH")
    if src["trade_authorized"] or src["prices_or_outcomes_read"]:raise ValueError("PRICE_LOOKAHEAD_IN_CANDIDATE_FILE")
    login=bs.login()
    if login.error_code!="0":raise ValueError("BAOSTOCK_LOGIN_FAILED")
    years={}
    try:
        for year in YEARS:
            picks=src["years"][str(year)]["candidates"]
            if len(picks)!=10:raise ValueError("EXPECTED_10_FIXED_TOP_CANDIDATES")
            start,end=WINDOWS[year]
            calendar=records(bs.query_trade_dates(start_date=start,end_date=end))
            market={}
            for pick in picks:
                sid=pick["symbol"]
                code=sid[-2:].lower()+"."+sid[:6]
                quote=records(bs.query_history_k_data_plus(
                    code,FIELDS,start_date=start,end_date=end,frequency="d",adjustflag="3"))
                idx={}
                for row in quote:
                    if row["code"]!=code or row["date"] in idx:raise ValueError("BAR_CODE_DATE_DUPLICATE")
                    idx[row["date"]]=row
                market[sid]=idx
            benchmark,bproof=official_h00300(year)
            years[str(year)]=one_year(year,picks,calendar,market,benchmark,bproof,spec["execution"])
            print("V31_DEV_YEAR_ECONOMICS="+json.dumps({
                k:v for k,v in years[str(year)].items() if k not in ("holdings",)},ensure_ascii=False),flush=True)
    finally:
        bs.logout()
    out={"schema":"V31_Q3_GROWTH_2018_2020_CONDITIONAL_DEV_EXECUTION_V1",
         "candidate_sha256":hashlib.sha256(args.candidates.read_bytes()).hexdigest(),
         "source":"BaoStock retrospective daily unadjusted + official CSI H00300 TR close",
         "years":years,"development_only_not_OOS":True,"2021_2022_evaluation_unopened":True,
         "buy_eligibility":"NOT_AUTHORIZED","certified_alpha":None,
         "stamp_duty_amendment":"historical 2018-2020 0.1pct, differs from 2026 frozen 0.05pct assumption; development only",
         "limitations":["open auction price is not verified fill","market data bars lack limit order queue",
                        "cash dividends and all corporate actions not certified",
                        "benchmark H00300 daily close lacks same instant opening value",
                        "provider constructed financial ranking not complete as-published PIT universe"]}
    args.output.write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("V31_DEV_TOTAL="+json.dumps({"year_statuses":{y:r["status"] for y,r in years.items()},
         "development_only_not_OOS":True,"certified_alpha":None},ensure_ascii=False))

if __name__=="__main__":
    main()
