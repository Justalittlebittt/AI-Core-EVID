#!/usr/bin/env python3
"""Single preregistered CSI300 official 19-in/19-out 20-session DEV comparison.

Second historical event replication, selected after seeing first event. No broker fills, no alpha promotion.
Preserves every published member, even absent/wrong-vintage quotes.
"""
import hashlib
import json
import math
from pathlib import Path
from collections import Counter
import numpy as np
from v29_2025_filing_to_return_case import records

ROOT=Path(__file__).resolve().parents[1]
SPEC=ROOT/"research/V3.2_CSI300_202511_FIXED_REPLICATION_PREREG_20261119.json"
OUTPUT=Path("/tmp/v32_csi300_reconstitution_202511_replication.json")
QUOTE_FIELDS="date,code,open,close,volume,tradestatus,isST,adjustflag"
START="2025-10-15"
END="2026-01-12"
ENTRY="2025-12-02"
OBS_END="2025-11-27"
def pos(v):
    try:
        x=float(v)
        return x if math.isfinite(x) and x>0 else None
    except (TypeError,ValueError):return None

def main():
    original=SPEC.read_bytes()
    spec=json.loads(original)
    add=spec["added"]
    delete=spec["removed"]
    if (spec["schema"]!="V32_CSI300_202511_RECONSTITUTION_20DAY_REPLICATION_PREREG_V1"
        or len(add)!=11 or len(delete)!=11 or
        len(set(add+delete))!=22 or
        spec["trade_authorized"] is not False or
        spec["entry"][:10]!=ENTRY):
        raise ValueError("PREREGISTRATION_OR_MEMBERSHIP_NOT_LOCKED")
    import baostock as bs
    login=bs.login()
    if login.error_code!="0":raise ValueError("BAOSTOCK_LOGIN_FAILED")
    try:
        cal=records(bs.query_trade_dates(start_date=START,end_date=END))
        sessions=[x["calendar_date"] for x in cal if x["is_trading_day"]=="1"]
        if ENTRY not in sessions or OBS_END not in sessions or len(sessions)<45:
            raise ValueError("TRADING_CALENDAR_NOT_CERTIFIED")
        at=sessions.index(ENTRY)
        exit_=sessions[at+19]
        prior_index=sessions.index(OBS_END)
        prior_start=sessions[prior_index-20]
        print("CSI300_FIXED_MARKET_CLOCK",json.dumps({"entry":ENTRY,
            "exit":exit_,"prior_start":prior_start,"prior_end":OBS_END},ensure_ascii=False),flush=True)
        all_data={}
        reasons=Counter()
        all_codes=add+delete
        for i,sec in enumerate(all_codes,1):
            code=("sh." if sec.startswith(("6","9")) else "sz.")+sec
            adjusted=records(bs.query_history_k_data_plus(
                code,QUOTE_FIELDS,start_date=START,end_date=END,
                frequency="d",adjustflag="2"))
            raw=records(bs.query_history_k_data_plus(
                code,QUOTE_FIELDS,start_date=START,end_date=END,
                frequency="d",adjustflag="3"))
            def mapped(rows,flag):
                out={}
                for row in rows:
                    if row["code"]!=code or row["adjustflag"]!=flag:
                        return None,"WRONG_VENDOR_IDENTITY_OR_ADJUSTFLAG"
                    if row["date"] in out:
                        return None,"DUPLICATE_VENDOR_DATE"
                    out[row["date"]]=row
                return out,None
            am,issue=mapped(adjusted,"2")
            rm,issue2=mapped(raw,"3")
            if issue or issue2:
                all_data[sec]={"status":issue or issue2}
                reasons[issue or issue2]+=1
            elif any(d not in am or d not in rm for d in [ENTRY,exit_,OBS_END,prior_start]):
                all_data[sec]={"status":"MISSING_PRICE_REFERENCE"}
                reasons["MISSING_PRICE_REFERENCE"]+=1
            else:
                if any(rm[d]["tradestatus"]!="1" or not pos(rm[d]["volume"]) for d in [ENTRY,exit_]):
                    all_data[sec]={"status":"ENTRY_OR_EXIT_NO_POSITIVE_TRADING_VOLUME"}
                    reasons["ENTRY_OR_EXIT_NO_POSITIVE_TRADING_VOLUME"]+=1
                elif rm[ENTRY]["isST"]!="0":
                    all_data[sec]={"status":"ST_AT_ENTRY"}
                    reasons["ST_AT_ENTRY"]+=1
                else:
                    adj_open=pos(am[ENTRY]["open"]);adj_exit=pos(am[exit_]["close"])
                    raw_open=pos(rm[ENTRY]["open"]);raw_exit=pos(rm[exit_]["close"])
                    pre0=pos(am[prior_start]["close"]);pre1=pos(am[OBS_END]["close"])
                    if any(x is None for x in [adj_open,adj_exit,raw_open,raw_exit,pre0,pre1]):
                        all_data[sec]={"status":"INVALID_PRICE"}
                        reasons["INVALID_PRICE"]+=1
                    else:
                        lot=200 if sec.startswith(("688","689")) else 100
                        buy_cost=lot*raw_open
                        sell_cost=lot*raw_exit
                        # Fixed fee proxy: commission minimum CNY 5 each side,
                        # 10bps slippage each side, 5bps sell stamp. No fill.
                        friction=(max(5,buy_cost*.0003)+max(5,sell_cost*.0003)
                                  +buy_cost*.001+sell_cost*.001+sell_cost*.0005)/buy_cost
                        all_data[sec]={"status":"HISTORICAL_PRICE_PROXY_COMPUTABLE",
                          "group":"ADD" if sec in add else "DELETE",
                          "lot":lot,"min_lot_reference_cost_cny":buy_cost,
                          "gross_adjusted_price_return":adj_exit/adj_open-1,
                          "fixed_friction_proxy_return":friction,
                          "net_adjusted_price_return_proxy":adj_exit/adj_open-1-friction,
                          "preannouncement_20session_price_return":pre1/pre0-1,
                          "broker_fill_certified":False}
            if i%10==0:print("CSI300_ISSUER_PROGRESS",i,22,flush=True)
        idx_raw=records(bs.query_history_k_data_plus(
              "sh.000300",QUOTE_FIELDS,start_date=START,end_date=END,
              frequency="d",adjustflag="3"))
        index={x["date"]:x for x in idx_raw if x["code"]=="sh.000300" and x["adjustflag"]=="3"}
        if ENTRY not in index or exit_ not in index or OBS_END not in index or prior_start not in index:
            raise ValueError("INDEX_SAME_PERIOD_MISSING")
        bench_entry=pos(index[ENTRY]["open"]);bench_exit=pos(index[exit_]["close"])
        pre_index_start=pos(index[prior_start]["close"])
        pre_index_end=pos(index[OBS_END]["close"])
        if any(x is None for x in [bench_entry,bench_exit,pre_index_start,pre_index_end]):
            raise ValueError("INDEX_PRICE_UNUSABLE")
        benchmark=bench_exit/bench_entry-1
        pre_bench=pre_index_end/pre_index_start-1
    finally:
        bs.logout()
    summary={}
    for group,codes in [("ADD",add),("DELETE",delete)]:
        rows=[all_data[k] for k in codes if all_data[k]["status"]=="HISTORICAL_PRICE_PROXY_COMPUTABLE"]
        for r in rows:
            r["after_cost_price_index_excess_proxy"]=r["net_adjusted_price_return_proxy"]-benchmark
            r["preannouncement_20session_index_excess"]=r["preannouncement_20session_price_return"]-pre_bench
        summary[group]={
          "original_members":len(codes),"computable_members":len(rows),
          "unavailable_members":[k for k in codes if all_data[k]["status"]!="HISTORICAL_PRICE_PROXY_COMPUTABLE"],
          "mean_net_index_excess_proxy":float(np.mean([r["after_cost_price_index_excess_proxy"] for r in rows])) if rows else None,
          "median_net_index_excess_proxy":float(np.median([r["after_cost_price_index_excess_proxy"] for r in rows])) if rows else None,
          "fraction_positive_net_index_excess_proxy":float(np.mean([r["after_cost_price_index_excess_proxy"]>0 for r in rows])) if rows else None,
          "mean_preannouncement_20session_index_excess":float(np.mean([r["preannouncement_20session_index_excess"] for r in rows])) if rows else None,
          "min_lot_reference_cost_sum_cny":sum(r["min_lot_reference_cost_cny"] for r in rows),
          "members_board_min_lot_over_10000_cny":sum(r["min_lot_reference_cost_cny"]>10000 for r in rows)
        }
    count_ok=all(summary[k]["computable_members"]>=16 for k in ("ADD","DELETE"))
    diff=(summary["ADD"]["mean_net_index_excess_proxy"]-summary["DELETE"]["mean_net_index_excess_proxy"]
          if count_ok else None)
    if not count_ok:
        verdict="SOURCE_INSUFFICIENT"
    elif diff>0 and summary["ADD"]["mean_net_index_excess_proxy"]>0:
        verdict="DESCRIPTIVE_DEVELOPMENT_SUPPORT_ONLY_NOT_VERIFIED_ALPHA"
    else:
        verdict="NOT_SUPPORTED_BY_THIS_ONE_HISTORICAL_EVENT"
    result={
      "schema":"V32_CSI300_202511_EVENT_TWENTY_SESSION_RETROSPECTIVE_REPLICATION_RESULT_V1",
      "preregistration_sha256":hashlib.sha256(original).hexdigest(),
      "announcement_date":"2025-11-28","original_count_per_group":11,
      "entry_day":ENTRY,"exit_day":exit_,
      "post_announcement_information_gap_to_entry_sessions":2,
      "index_effective_after_close":"2025-12-12",
      "same_reference_20session_stock_holding":True,
      "CSI300_index_price_only_same_holding_return":benchmark,
      "groups":summary,
      "add_minus_delete_mean_net_excess_proxy":diff,
      "status":verdict,"member_status_counts":dict(reasons),
      "all_member_original_no_replacement":all_data,
      "one_market_episode_not_independent_prospective":True,
      "selected_after_seeing_may_2026_outcome_so_not_pristine_OOS":True,
      "historical_pdf_initial_publication_exact_time_unverified":True,
      "historical_vendor_prices_not_fills_or_total_returns":True,
      "all_2026_122_8_and_e_fold_protected_not_read":True,
      "trade_authorized":False
    }
    OUTPUT.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    print("CSI300_EVENT_FINAL="+json.dumps({k:v for k,v in result.items() if k!="all_member_original_no_replacement"},
      ensure_ascii=False),flush=True)

if __name__=="__main__":main()
