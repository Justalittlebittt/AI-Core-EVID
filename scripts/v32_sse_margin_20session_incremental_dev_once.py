#!/usr/bin/env python3
"""Preregistered four-event SSE margin-vs-stock 20-session forecast DEV.

Retrospective 60 stock-coded SSE securities sampled via immutable hash
from FIRST event only. Later source availability cannot replace members.
There is no pristine OOS, no sealed historical publication, no broker fills.
"""
from __future__ import annotations
import hashlib,json,math
from datetime import date
from pathlib import Path
import numpy as np
from v32_sse_margin_two_day_source_probe import day_report
from v29_2025_filing_to_return_case import records

ROOT=Path(__file__).resolve().parents[1]
SPEC=ROOT/"research/V3.2_SSE_MARGIN_FIXED_20DAY_INCREMENTAL_DEV_PREREG_20261119.json"
OUTPUT=Path("/tmp/v32_margin_fixed_20session_incremental_dev.json")
EVENTS=("2026-05-20","2026-06-17","2026-07-15","2026-09-18")
FIELDS="date,code,open,close,volume,tradestatus,isST,adjustflag"
STOCK_PREFIXES=("600","601","603","605","688","689")
BASELINE="stock-adjusted-prior5-minus-index-prior5;stock-adjusted-prior20-minus-index-prior20"
BUY_CASH=100000.
PER_SLOT=10000.

def pos(x):
    try:
        v=float(x)
        return v if math.isfinite(v) and v>0 else None
    except (ValueError,TypeError):return None

def get_calendar(bs):
    source=records(bs.query_trade_dates(start_date="2026-04-01",end_date="2026-10-31"))
    if not source:raise ValueError("CALENDAR_EMPTY")
    days=sorted({x["calendar_date"] for x in source if x["is_trading_day"]=="1"})
    if len(days)<100 or any(d not in days for d in EVENTS):
        raise ValueError("CALENDAR_MISSING_FIXED_SIGNAL_DATES")
    return days

def source_rows(sessions):
    data={}
    provenance=[]
    for event in EVENTS:
        i=sessions.index(event)
        if i<20 or i+21>=len(sessions):raise ValueError("20_SESSION_WINDOW_INCOMPLETE")
        required=[sessions[i-5],sessions[i-1],event]
        data[event]={}
        for day in required:
            report,rows=day_report(day.replace("-",""))
            provenance.append({"signal_date":event,"source_date":day,
              "status":report["status"],"raw_page_proof":report["pages"],
              "retrieved_codes":len(rows)})
            if report["status"]!="SOURCE_PAGINATION_EXHAUSTIVE":
                raise ValueError("SSE_MARGIN_DATE_SOURCE_NOT_COMPLETE:"+day)
            data[event][day]=rows
        print("MARGIN_EVENT_SOURCE_COMPLETE",event,"T_MINUS_5",required[0],flush=True)
    return data,provenance

def lock_cohort(rows):
    sample=[k for k in rows if k.startswith(STOCK_PREFIXES)]
    sample.sort(key=lambda k:(hashlib.sha256(k.encode()).hexdigest(),k))
    if len(sample)<60:raise ValueError("LESS_THAN_60_SSE_SECURITIES")
    return sample[:60],len(sample)

def fetch_bars(bs,sids):
    result={}
    for j,sid in enumerate(sids,1):
        code="sh."+sid
        byflag={}
        for flag in ("2","3"):
            rr=records(bs.query_history_k_data_plus(code,FIELDS,
               start_date="2026-04-01",end_date="2026-10-31",
               frequency="d",adjustflag=flag))
            tmp={}
            adjustment_unavailable=False
            for one in rr:
                if one["code"]!=code or one["date"] in tmp:
                    raise ValueError("INVALID_BAOSTOCK_IDENTITY_OR_DUPLICATE:"+sid+":"+repr(one)[:200])
                if one["adjustflag"]!=flag:
                    # Historical vendor can return raw flag=3 even when we
                    # requested forward-adjusted flag=2. Never substitute.
                    if flag=="2" and one["adjustflag"]=="3":
                        print("FORWARD_ADJUSTED_SOURCE_NOT_AUTHENTICATED",sid,
                              "requested",flag,"returned",one["adjustflag"],flush=True)
                        adjustment_unavailable=True
                        break
                    raise ValueError("UNEXPECTED_ADJUSTMENT_VINTAGE:"+sid+":"+str(one["adjustflag"]))
                tmp[one["date"]]=one
            byflag[flag]={} if adjustment_unavailable else tmp
        result[sid]=byflag
        if j%15==0:print("BAOSTOCK_ISSUER_PROGRESS",j,len(sids),flush=True)
    idx=records(bs.query_history_k_data_plus("sh.000300",FIELDS,
          start_date="2026-04-01",end_date="2026-10-31",
          frequency="d",adjustflag="3"))
    index={r["date"]:r for r in idx if r["code"]=="sh.000300"}
    if len(index)<75:raise ValueError("BENCHMARK_INDEX_BARS_INSUFFICIENT")
    return result,index

def features(sid,day,sessions,margin,bars,index):
    i=sessions.index(day)
    older=sessions[i-20]
    prev=sessions[i-5]
    yesterday=sessions[i-1]
    rt=margin  # caller already passes event-scoped date -> security rows
    if sid not in rt[prev] or sid not in rt[yesterday] or sid not in rt[day]:
        return None,"MARGIN_MEMBERSHIP_OR_HISTORY_MISSING"
    oldb=pos(rt[prev][sid]["balance"]);nowb=pos(rt[day][sid]["balance"])
    prevb=pos(rt[yesterday][sid]["balance"])
    if not oldb or not nowb or not prevb:return None,"ZERO_OR_INVALID_MARGIN_BALANCE"
    today=rt[day][sid]
    flow=(float(today["buy"])-float(today["repay"]))/prevb
    change=nowb/oldb-1
    adjusted=bars[sid]["2"]
    for d in (older,prev,day):
        if d not in adjusted or d not in index:return None,"PRIOR_PRICE_MISSING"
    for d in (older,prev,day):
        a=adjusted[d];b=index[d]
        if (a["tradestatus"]!="1" or a["isST"]!="0" or not pos(a["volume"])
            or not pos(a["close"]) or not pos(b["close"])):
            return None,"PRE_SIGNAL_NOT_NORMAL_TRADING"
    s5=float(adjusted[day]["close"])/float(adjusted[prev]["close"])-1
    i5=float(index[day]["close"])/float(index[prev]["close"])-1
    s20=float(adjusted[day]["close"])/float(adjusted[older]["close"])-1
    i20=float(index[day]["close"])/float(index[older]["close"])-1
    return np.array([1.,s5-i5,s20-i20,change,flow]),None

def target(sid,day,sessions,bars,index):
    i=sessions.index(day)
    entry,exitday=sessions[i+2],sessions[i+21]
    adj=bars[sid]["2"];raw=bars[sid]["3"]
    for d in (entry,exitday):
        if d not in adj or d not in raw or d not in index:
            return None,"TARGET_ENDPOINT_MISSING"
    for d in (entry,exitday):
        if (raw[d]["tradestatus"]!="1" or not pos(raw[d]["volume"]) or
            not pos(raw[d]["open"]) or not pos(raw[d]["close"])):
            return None,"TARGET_NOT_NORMAL_LIQUID"
    if raw[entry]["isST"]!="0":return None,"ST_AT_ENTRY"
    open_adj=pos(adj[entry]["open"]);close_adj=pos(adj[exitday]["close"])
    idxopen=pos(index[entry]["open"]);idxclose=pos(index[exitday]["close"])
    if None in (open_adj,close_adj,idxopen,idxclose):
        return None,"TARGET_ADJUSTED_OR_BENCHMARK_PRICE_INVALID"
    stock_r=close_adj/open_adj-1.
    index_r=idxclose/idxopen-1.
    return {
      "target_excess":stock_r-index_r,
      "stock_price_return":stock_r,"benchmark_price_return":index_r,
      "entry_day":entry,"exit_day":exitday,
      "entry_raw_open":pos(raw[entry]["open"]),
      "exit_raw_close":pos(raw[exitday]["close"]),
      "actual_broker_fill_certified":False,
    },None

def mse(y,p):
    return float(np.mean((y-p)**2))
def spearman(x,y):
    a=np.asarray(x);b=np.asarray(y)
    if len(a)<3 or np.std(a)==0 or np.std(b)==0:return None
    ra=np.argsort(np.argsort(a)).astype(float)
    rb=np.argsort(np.argsort(b)).astype(float)
    return float(np.corrcoef(ra,rb)[0,1])
def portfolio(ranks,actual):
    chosen=sorted(ranks,key=lambda x:(-ranks[x],x))[:10]
    incomplete=[]
    trades=[]
    gross=0.
    for sid in chosen:
        target=actual.get(sid)
        if target is None:
            incomplete.append({"sid":sid,"issue":"TARGET_MISSING"});continue
        entry=target["entry_raw_open"];exit_=target["exit_raw_close"]
        if not entry or not exit_:
            incomplete.append({"sid":sid,"issue":"RAW_PRICE_MISSING"});continue
        shares=200 if sid.startswith(("688","689")) else 100
        cost=shares*entry*(1+.001)+max(5,shares*entry*.0003)
        if cost>PER_SLOT:
            incomplete.append({"sid":sid,"issue":"BOARD_MIN_LOT_EXCEEDS_10000_TARGET"});continue
        proceeds=shares*exit_*(1-.001-.0005)-max(5,shares*exit_*.0003)
        gross+=cost
        trades.append({"sid":sid,"entry_cost":cost,"proceeds":proceeds})
    if incomplete or len(trades)!=10 or gross>BUY_CASH:
        return {"status":"ORIGINAL_TOP10_PORTFOLIO_NOT_EXECUTABLE_AS_SPECIFIED",
           "selected_ids":chosen,"matched_trades":len(trades),"issues":incomplete,
           "portfolio_net_return":None}
    net=(BUY_CASH-gross+sum(t["proceeds"] for t in trades))/BUY_CASH-1
    return {"status":"RAW_DAILY_BAR_PAPER_PROXY_NOT_BROKER_FILLS",
            "selected_ids":chosen,"trades":len(trades),"gross_cny":gross,
            "portfolio_net_return":net,"unverified_corporate_actions":True,
            "limit_order_book_and_dividend_cashflow_not_certified":True}

def main():
    fixed=SPEC.read_bytes()
    spec=json.loads(fixed)
    if (spec["schema"]!="V32_SSE_MARGIN_FIXED_20SESSION_INCREMENTAL_DEVELOPMENT_PREDECLARATION_V1"
        or spec["decision_events"]!=list(EVENTS)
        or spec["authorized_buy"] is not False):
        raise ValueError("PREREGISTRATION_NOT_FIXED")
    import baostock as bs
    login=bs.login()
    if login.error_code!="0":raise ValueError("BAOSTOCK_LOGIN_FAILED")
    try:
        sessions=get_calendar(bs)
        margin,margin_sources=source_rows(sessions)
        initial=margin[EVENTS[0]][EVENTS[0]]
        sample,first_count=lock_cohort(initial)
        print("FROZEN_SAMPLE_HASHED_60",sample,flush=True)
        prices,index=fetch_bars(bs,sample)
    finally:bs.logout()
    X=[];Y=[];event_counts={}
    test_rows={}
    misses={}
    for event in EVENTS:
        valid=0
        for sid in sample:
            f,why=features(sid,event,sessions,margin[event],prices,index)
            if why:
                misses[why]=misses.get(why,0)+1;continue
            y,ywhy=target(sid,event,sessions,prices,index)
            if ywhy:
                misses[ywhy]=misses.get(ywhy,0)+1
                if event==EVENTS[-1]:test_rows[sid]={"features":f,"target":None}
                continue
            if event!=EVENTS[-1]:
                X.append(f);Y.append(y["target_excess"])
            else:test_rows[sid]={"features":f,"target":y}
            valid+=1
        event_counts[event]=valid
        print("TWENTY_DAY_ISSUER_EVENT",event,"eligible_with_outcome",valid,flush=True)
    result={
      "schema":"V32_SSE_MARGIN_20SESSION_INCREMENTAL_FIXED_DEV_RESULT_V1",
      "preregistration_sha256":hashlib.sha256(fixed).hexdigest(),
      "retrospective_development_not_pristine_oos":True,
      "source_as_published_initial_timestamp_certified":False,
      "official_equity_issuer_identity_confirmed":False,
      "day_bar_trading_not_broker_fill_certified":True,
      "test_is_one_cross_sectional_market_event":True,
      "five_and_twenty_day_price_only_baseline":BASELINE,
      "first_event_approx_A_stock_count":first_count,"cohort_size":len(sample),
      "cohort_code_sha256":hashlib.sha256(("|".join(sample)).encode()).hexdigest(),
      "cohort_ids":sample,
      "event_valid_target_counts":event_counts,"missing_or_ineligible":misses,
      "margin_source_page_receipts":margin_sources,
      "no_unseen_122_8_or_E_layer_read":True,
      "live_buy_authorized":False}
    feature_eligible={sid:one for sid,one in test_rows.items()}
    complete_cases={sid:one for sid,one in test_rows.items() if one["target"] is not None}
    if len(X)<40 or len(complete_cases)<30:
        result["status"]="INSUFFICIENT_TRAIN_OR_TEST_SOURCE"
    else:
        train=np.vstack(X);labels=np.asarray(Y,dtype=float)
        # Fixed unrestricted linear model, no hyperparameter tuning.
        b=np.linalg.lstsq(train[:,:3],labels,rcond=None)[0]
        a=np.linalg.lstsq(train,labels,rcond=None)[0]
        ordering=sorted(complete_cases)
        te=np.stack([complete_cases[k]["features"] for k in ordering])
        observed=np.array([complete_cases[k]["target"]["target_excess"] for k in ordering])
        pb=te[:,:3]@b;pa=te@a
        b_mse=mse(observed,pb);a_mse=mse(observed,pa)
        all_decision_codes=sorted(feature_eligible)
        all_decision_features=np.stack([feature_eligible[k]["features"] for k in all_decision_codes])
        all_predictions_base=all_decision_features[:,:3]@b
        all_predictions_plus=all_decision_features@a
        ranks_base={k:float(v) for k,v in zip(all_decision_codes,all_predictions_base)}
        ranks_plus={k:float(v) for k,v in zip(all_decision_codes,all_predictions_plus)}
        actual={sid:r["target"] for sid,r in test_rows.items()}
        portfolio_base=portfolio(ranks_base,actual)
        portfolio_aug=portfolio(ranks_plus,actual)
        result.update({"status":"DESCRIPTIVE_INCREMENTAL_MSE_IMPROVED" if a_mse<b_mse
                           else "NOT_SUPPORTED_BY_THIS_RETROSPECTIVE_DEVELOPMENT_SAMPLE",
           "train_n":len(X),"test_n":len(ordering),
           "test_decision_time_feature_eligible":len(feature_eligible),
           "baseline_test_mse":b_mse,"augmented_test_mse":a_mse,
           "relative_mse_improvement":1-a_mse/b_mse if b_mse>0 else None,
           "baseline_test_rank_ic":spearman(pb,observed),
           "augmented_test_rank_ic":spearman(pa,observed),
           "baseline_paper_portfolio":portfolio_base,
           "augmented_paper_portfolio":portfolio_aug,
           "test_date":EVENTS[-1],
           "test_portfolio_rank_candidates_all_decision_time_only":True,
           "quantile_standard_errors_not_independent":True,
           "fees_not_proven_broker_equivalent":True,
           "evidence_not_sufficient_for_buy":True})
    OUTPUT.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    print("V32_MARGIN_INCREMENTAL_20SESSION_RESULT",json.dumps({
      k:v for k,v in result.items() if k not in
      ("margin_source_page_receipts","cohort_ids")},ensure_ascii=False),flush=True)

if __name__=="__main__":main()
