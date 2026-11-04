#!/usr/bin/env python3
"""One second, non-overlapping MARKET EPISODE with the SAME frozen 122 names.
Research-only, not an independent company cohort or a BUY signal. No reselection.
Reuses existing BaoStock close-bar validation and frozen November cohort loader.
"""
from __future__ import annotations

import argparse
import base64
import gzip
import hashlib
import json
import math
from datetime import date, datetime, time, timezone
from pathlib import Path
from statistics import median
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from v29_growth_forward_cohort import load_registered
from v29_2025_filing_to_return_case import records
from v29_forward122_preentry_source_check import FIELDS, baostock_code
from v29_forward122_entry_close_capture import canonical_bytes, numeric_positive, sha
from v29_forward122_20th_session_exit_capture import one_issuer, active_bar, bars_by_day

ROOT=Path(__file__).resolve().parents[1]
PLAN=ROOT/"research/V2.9_TEMPORAL_REPLICATION_20261130_PREOUTCOME.json"
ENTRY=ROOT/"research/V2.9_TEMPORAL_REPLICATION_20261130_ENTRY/ENTRY_SNAPSHOT_122.json"
ENTRY_RAW=ENTRY.parent/"RAW_ENTRY_122.json.gz"
TZ=ZoneInfo("Asia/Shanghai")
API="https://www.csindex.com.cn/csindex-home/perf/index-perf"
DAY0=date(2026,11,30)
DAY19=date(2026,12,25)
N=122
GIT_PLAN="4c1059caf679e6b5ce1444ac194da876b5caa5da"

def git_blob(data):
    return hashlib.sha1(b"blob "+str(len(data)).encode()+b"\0"+data).hexdigest()

def sources():
    raw=PLAN.read_bytes()
    if git_blob(raw)!=GIT_PLAN:
        raise ValueError("TEMPORAL_PREOUTCOME_PLAN_CHANGED")
    plan=json.loads(raw)
    spec,ids,digest=load_registered()
    manifest=(ROOT/plan["original_study_bound"]["immutable_122_manifest"]).read_bytes()
    protocol=(ROOT/plan["original_study_bound"]["original_protocol_path"]).read_bytes()
    if (len(ids)!=N or len(set(ids))!=N
            or git_blob(manifest)!=plan["original_study_bound"]["manifest_git_blob_sha"]
            or git_blob(protocol)!=plan["original_study_bound"]["original_protocol_git_blob_sha"]
            or plan["original_study_bound"]["issuer_id_order_linefeed_sha256"]!=spec["sample"]["sha256_linefeed"]
            or plan["temporal_replication"]["planned_entry_session"]!=DAY0.isoformat()
            or plan["temporal_replication"]["planned_twentieth_session"]!=DAY19.isoformat()
            or plan["temporal_replication"]["same_roundtrip_cost_fraction"]!=.003
            or plan["evidence_interpretation"]["independent_security_cohort"] is not False):
        raise ValueError("FROZEN_TEMPORAL_REPLICATION_IDENTITY_CHANGED")
    return plan,ids,digest,sha(raw)

def gate(phase,now):
    if not isinstance(now,datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("AWARE_CLOCK_REQUIRED")
    now=now.astimezone(TZ)
    day=DAY0 if phase=="entry" else DAY19
    if now.date()!=day or now.time()<time(16,30):
        raise ValueError("ONLY_DECLARED_SAME_DAY_AFTER_CLOSE_CAPTURE")
    return now

def sessions_for(phase,calendar,plan):
    wanted=[DAY0.isoformat()] if phase=="entry" else plan["temporal_replication"]["planned_sessions_from_published_holidays_and_weekdays_not_yet_actual_calendar_certified"]
    seen={}
    for r in calendar:
        day=r["calendar_date"]
        if day in seen or r["is_trading_day"] not in ("0","1"):
            raise ValueError("INVALID_OR_DUPLICATE_CALENDAR")
        seen[day]=r["is_trading_day"]
    if phase=="entry":
        if seen.get("2026-11-28")!="0" or seen.get("2026-11-29")!="0" or seen.get(wanted[0])!="1":
            raise ValueError("SECOND_EPISODE_ENTRY_CALENDAR_UNVERIFIED")
    elif (len(wanted)!=20 or len(seen)<26
          or any(seen.get(day)!=("1" if date.fromisoformat(day).weekday()<5 else "0")
                 for day in seen)
          or any(seen.get(day)!="1" for day in wanted)
          or sorted(day for day,active in seen.items() if active=="1")!=wanted):
        raise ValueError("SECOND_EPISODE_EXCHANGE_CALENDAR_NOT_VERIFIED")
    return wanted

def index_fetch(start,end,opener=urlopen):
    url=API+"?"+urlencode({"indexCode":"H00300","startDate":start.replace("-",""),
                           "endDate":end.replace("-","")})
    request=Request(url,headers={"User-Agent":"Mozilla/5.0 Chrome/124.0.0.0 Safari/537.36",
                  "Accept":"application/json,text/plain,*/*","Referer":"https://www.csindex.com.cn/"})
    for attempt in range(3):
        try:
            with opener(request,timeout=20) as response:
                raw=response.read(900_001)
            if len(raw)>900000:
                raise ValueError("OFFICIAL_INDEX_RESPONSE_TOO_LARGE")
            return raw
        except HTTPError:
            raise
        except (URLError,TimeoutError,OSError):
            if attempt==2:
                raise

def read_index(raw,start,end,original_entry=None):
    payload=json.loads(raw)
    if not isinstance(payload,dict) or not isinstance(payload.get("data"),list):
        raise ValueError("OFFICIAL_TOTAL_RETURN_INDEX_SCHEMA_INVALID")
    prices={}
    for item in payload["data"]:
        if isinstance(item,list) and len(item)>=10:
            d,c,v=item[0],item[1],item[9]
        elif isinstance(item,dict):
            d,c,v=item.get("tradeDate") or item.get("date"),item.get("indexCode"),item.get("close")
        else:
            raise ValueError("OFFICIAL_INDEX_ROW_INVALID")
        if str(c or "").upper() not in ("H00300","H00300.CSI"):
            raise ValueError("PRICE_INDEX_CANNOT_SUBSTITUTE_H00300")
        d=str(d or "")
        day=datetime.strptime(d,"%Y%m%d").date().isoformat() if len(d)==8 and d.isdigit() else date.fromisoformat(d).isoformat()
        if not start<=day<=end or day in prices:
            raise ValueError("OFFICIAL_INDEX_DATE_OR_DUPLICATE_INVALID")
        price=numeric_positive(v)
        if price is None:
            raise ValueError("OFFICIAL_INDEX_PRICE_INVALID")
        prices[day]=price
    if start not in prices or end not in prices:
        raise ValueError("OFFICIAL_INDEX_ENDPOINT_MISSING")
    if original_entry is not None and abs(prices[start]-original_entry)>0.0001:
        raise ValueError("H00300_FROZEN_SECOND_ENTRY_VINTAGE_DRIFT")
    return {"security_id":"H00300.CSI","entry_close":prices[start],"exit_close":prices[end],
            "source_sha256":sha(raw),"same_official_total_return_index":True}

def query(bs,ids,phase,plan):
    begin="2026-11-28" if phase=="entry" else DAY0.isoformat()
    end=DAY0.isoformat() if phase=="entry" else DAY19.isoformat()
    login=bs.login()
    if login.error_code!="0":
        raise ValueError("BAOSTOCK_LOGIN_FAILED")
    sources=[]
    try:
        calendar=records(bs.query_trade_dates(start_date=begin,end_date=end))
        sessions=sessions_for(phase,calendar,plan)
        for sid in ids:
            code=baostock_code(sid)
            record={"security_id":sid,"raw_unadjusted":[],"forward_adjusted":[]}
            for key,flag in (("raw_unadjusted","3"),("forward_adjusted","2")):
                try:
                    record[key]=records(bs.query_history_k_data_plus(
                        code,FIELDS,start_date=DAY0.isoformat(),end_date=end,
                        frequency="d",adjustflag=flag))
                except (OSError,ValueError,KeyError) as e:
                    record["query_error_"+key]=type(e).__name__
            sources.append(record)
    finally:
        bs.logout()
    return sources,calendar,sessions

def capture_entry(bs,now,index_reader=index_fetch):
    local=gate("entry",now)
    plan,ids,protocol_sha,plan_sha=sources()
    sources_rows,calendar,sessions=query(bs,ids,"entry",plan)
    rows=[]
    for source in sources_rows:
        sid=source["security_id"]
        try:
            e=bars_by_day(sid,source["raw_unadjusted"],"3",set(sessions)).get(sessions[0])
            a=bars_by_day(sid,source["forward_adjusted"],"2",set(sessions)).get(sessions[0])
            valid=e is not None and a is not None and active_bar(e) and numeric_positive(a.get("close")) is not None
        except (ValueError,KeyError,TypeError):
            valid=False
        rows.append({"security_id":sid,"source_complete":bool(valid),
                     "raw_source_sha256":sha(canonical_bytes(source))})
    official_raw=None
    try:
        official_raw=index_reader(DAY0.isoformat(),DAY0.isoformat())
        bm=read_index(official_raw,DAY0.isoformat(),DAY0.isoformat())
        benchmark={"status":"OFFICIAL_H00300_ENTRY_VERIFIED",**bm}
    except (ValueError,KeyError,TypeError,HTTPError,URLError,TimeoutError,OSError) as exc:
        benchmark={"status":"OFFICIAL_H00300_ENTRY_UNVERIFIED","source_sha256":sha(official_raw) if official_raw else None,
                   "reason":type(exc).__name__+":"+str(exc)[:160]}
    archive={"calendar":calendar,"sessions":sessions,"quotes":sources_rows,
             "official_http_base64":base64.b64encode(official_raw).decode() if official_raw else None}
    raw=canonical_bytes(archive)
    status=("COMPLETE_122_AND_H00300" if all(r["source_complete"] for r in rows)
            and benchmark["status"]=="OFFICIAL_H00300_ENTRY_VERIFIED" else "INCOMPLETE_NO_SUBSTITUTION")
    report={"schema":"V29_SECOND_TEMPORAL_122_ENTRY_V1","experiment_id":plan["experiment_id"],
            "source_plan_sha256":plan_sha,"original_protocol_sha256":protocol_sha,
            "captured_at_local":local.isoformat(),"entry_session":DAY0.isoformat(),
            "rows":rows,"number_of_original_issuers":N,"source_complete":sum(r["source_complete"] for r in rows),
            "benchmark":benchmark,"raw_sha256":sha(raw),"status":status,
            "actual_fills_proven":False,"live_buy_eligibility":"NOT_AUTHORIZED"}
    return report,raw

def load_second_entry():
    plan,ids,protocol_sha,plan_sha=sources()
    if not ENTRY.exists() or not ENTRY_RAW.exists():
        raise ValueError("SECOND_EPISODE_SAME_DAY_ENTRY_NOT_SEALED")
    entry=json.loads(ENTRY.read_text(encoding="utf-8"))
    raw=gzip.decompress(ENTRY_RAW.read_bytes())
    archive=json.loads(raw)
    if (entry.get("schema")!="V29_SECOND_TEMPORAL_122_ENTRY_V1"
            or entry.get("status")!="COMPLETE_122_AND_H00300"
            or entry.get("entry_session")!=DAY0.isoformat()
            or entry.get("source_plan_sha256")!=plan_sha
            or entry.get("original_protocol_sha256")!=protocol_sha
            or entry.get("raw_sha256")!=sha(raw)
            or entry.get("number_of_original_issuers")!=N
            or entry.get("source_complete")!=N
            or entry.get("benchmark",{}).get("status")!="OFFICIAL_H00300_ENTRY_VERIFIED"
            or [r["security_id"] for r in entry["rows"]]!=ids
            or [r["security_id"] for r in archive["quotes"]]!=ids):
        raise ValueError("SECOND_EPISODE_FROZEN_ENTRY_ARCHIVE_INTEGRITY_FAILED")
    return plan,ids,protocol_sha,sha(ENTRY.read_bytes()),entry,archive

def capture_outcome(bs,now,index_reader=index_fetch):
    local=gate("outcome",now)
    plan,ids,protocol_sha,entry_sha,entry,prior=load_second_entry()
    quote_rows,calendar,sessions=query(bs,ids,"outcome",plan)
    outcomes=[]
    for sid,original,source in zip(ids,prior["quotes"],quote_rows):
        if source["security_id"]!=sid or original["security_id"]!=sid:
            raise ValueError("SECOND_EPISODE_ORDER_CHANGED")
        row,_=one_issuer(sid,sessions,original,source["raw_unadjusted"],source["forward_adjusted"])
        outcomes.append(row)
    official_raw=None
    try:
        official_raw=index_reader(DAY0.isoformat(),DAY19.isoformat())
        benchmark=read_index(official_raw,DAY0.isoformat(),DAY19.isoformat(),
                             entry["benchmark"]["entry_close"])
        benchmark["status"]="OFFICIAL_H00300_BOTH_ENDPOINTS_VERIFIED"
    except (ValueError,KeyError,TypeError,HTTPError,URLError,TimeoutError,OSError) as exc:
        benchmark={"status":"OFFICIAL_H00300_EXIT_UNVERIFIED",
                   "reason":type(exc).__name__+":"+str(exc)[:160],
                   "source_sha256":sha(official_raw) if official_raw else None}
    valid=[r for r in outcomes if r["price_comparison_eligible"]]
    complete=len(valid)==N and benchmark["status"]=="OFFICIAL_H00300_BOTH_ENDPOINTS_VERIFIED"
    metrics=None
    if complete:
        baseline=benchmark["exit_close"]/benchmark["entry_close"]-1
        prices={r["canonical_security_id"]:
                r["adjusted_exit_close"]/r["adjusted_entry_close"]-1-.003 for r in outcomes}
        net=list(prices.values())
        excess=[v-baseline for v in net]
        eight_file=(ROOT/plan["optional_same_episode_secondary"]["eight_fixed_preoutcome_spec"]).read_bytes()
        if git_blob(eight_file)!=plan["optional_same_episode_secondary"]["eight_spec_git_blob_sha"]:
            raise ValueError("FROZEN_EIGHT_SPEC_CHANGED")
        eight_spec=json.loads(eight_file)
        eight=eight_spec["pre_outcome_rule"]["selected_ids_in_rank_order"]
        if len(eight)!=8 or len(set(eight))!=8 or not set(eight).issubset(ids):
            raise ValueError("FROZEN_EIGHT_CHANGED")
        eight_net=sum(prices[sid] for sid in eight)/8
        metrics={"equal_122_mean_net":sum(net)/N,"mean_net_excess_vs_H00300":sum(excess)/N,
                 "median_individual_excess":median(excess),"min_individual_excess":min(excess),
                 "max_individual_excess":max(excess),"fraction_beating_H00300":sum(v>0 for v in excess)/N,
                 "eight_mean_net":eight_net,
                 "eight_minus_122":eight_net-sum(net)/N,
                 "eight_minus_H00300":eight_net-baseline,
                 "benchmark_total_return":baseline}
    archive={"calendar":calendar,"sessions":sessions,"quotes":quote_rows,
             "official_http_base64":base64.b64encode(official_raw).decode() if official_raw else None}
    raw=canonical_bytes(archive)
    status="ONE_MORE_NONOVERLAPPING_EPISODE_DESCRIPTIVE_ONLY" if complete else "INCOMPLETE_KEEP_ALL_122"
    return {"schema":"V29_SECOND_TEMPORAL_122_OUTCOME_V1","experiment_id":plan["experiment_id"],
            "source_entry_snapshot_sha256":entry_sha,"source_plan_sha256":sha(PLAN.read_bytes()),
            "original_protocol_sha256":protocol_sha,"entry_session":DAY0.isoformat(),
            "exit_session":DAY19.isoformat(),"captured_at_local":local.isoformat(),
            "sessions":sessions,"observed":N,"price_eligible":len(valid),"rows":outcomes,
            "benchmark":benchmark,"metrics":metrics,"status":status,"raw_sha256":sha(raw),
            "independent_company_cohort":False,"independent_reporting_vintage":False,
            "actual_fills_proven":False,"strategy_validated":False,"live_buy_eligibility":"NOT_AUTHORIZED"},raw

def write(out,phase,report,raw):
    if out.exists():
        raise ValueError("NEVER_OVERWRITE_ARCHIVED_RESEARCH")
    if report["raw_sha256"]!=sha(raw) or len(report["rows"])!=N:
        raise ValueError("SOURCE_HASH_OR_FIXED_SAMPLE_COUNT_FAILED")
    out.mkdir(parents=True)
    filename="ENTRY_SNAPSHOT_122.json" if phase=="entry" else "OUTCOME_122.json"
    archive="RAW_ENTRY_122.json.gz" if phase=="entry" else "RAW_OUTCOME_122.json.gz"
    (out/filename).write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    with (out/archive).open("wb") as f:
        with gzip.GzipFile(fileobj=f,mode="wb",mtime=0) as stream:
            stream.write(raw)

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--phase",required=True,choices=["entry","outcome"])
    parser.add_argument("--out",required=True,type=Path)
    args=parser.parse_args()
    import baostock
    now=datetime.now(timezone.utc)
    if args.phase=="entry":
        report,raw=capture_entry(baostock,now)
    else:
        report,raw=capture_outcome(baostock,now)
    write(args.out,args.phase,report,raw)
    print(json.dumps({"experiment_id":report["experiment_id"],"status":report["status"],
                      "live_buy_eligibility":"NOT_AUTHORIZED"},ensure_ascii=False),flush=True)

if __name__=="__main__":
    main()
