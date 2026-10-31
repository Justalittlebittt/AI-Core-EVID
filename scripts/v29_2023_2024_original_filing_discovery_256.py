#!/usr/bin/env python3
"""Fetch 2023/2024 original annual-report announcement URLs for PRE-FROZEN cohorts.

The two 128-name lists were committed to main BEFORE these new remote queries.
Uses real CNINFO organization-ID resolution, never fabricated ticker-derived IDs.
Preserves failures, ambiguous full reports and raw API response bytes. This is
retrospective 2026 acquisition, not timestamp-sealed original-era PIT or OOS.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import time
import zipfile
from datetime import date,datetime,timedelta,timezone
from pathlib import Path
from urllib.error import HTTPError,URLError

from v29_original_report_discovery_128 import _post

ROOT=Path(__file__).resolve().parents[1]
FRAMES=ROOT/"research/V2.9_2023_2024_ORIGINAL_FILING_SOURCE_FRAMES_128.json"
SOURCE_SCHEMA="V29_2023_2024_2X128_ORIGINAL_ANNUAL_REPORT_DISCOVERY_V1"
FRAME_SCHEMA="V29_EARLIER_ORIGINAL_FILING_2023_2024_SOURCE_COHORTS_V1"
PDF_PATH=re.compile(r"finalpage/(20\d\d-\d\d-\d\d)/(\d+\.PDF)",re.IGNORECASE)
IGNORE=("摘要","更正","修订","已取消","取消","补充","英文","提示性","SUMMARY","ENGLISH","ANNUAL REPORT")
BEIJING=timezone(timedelta(hours=8))
PAGE_LIMIT=4

def sha(b):
    return hashlib.sha256(b).hexdigest()

def load_frozen_frames():
    raw=FRAMES.read_bytes()
    data=json.loads(raw)
    if (data.get("schema")!=FRAME_SCHEMA or
        data.get("historical_outcomes_already_known_at_2026_sampling") is not True or
        data.get("chronological_untouched_oos_certified") is not False or
        len(data.get("cohorts",[]))!=2):
        raise ValueError("NOT_PRE_FROZEN_2023_2024_RESEARCH_COHORT")
    for c,expected_year in zip(data["cohorts"],(2023,2024)):
        ids=c.get("selected_ids")
        if (c.get("expected_issuer_publication_year")!=expected_year or
            c.get("selected_count")!=128 or not isinstance(ids,list) or
            len(ids)!=128 or len(set(ids))!=128 or
            c.get("selected_ids_sha256")!=sha(("\n".join(ids)+"\n").encode()) or
            c.get("report_period_end")!=f"{expected_year-1}-12-31"):
            raise ValueError("FROZEN_IDENTITY_CARDINALITY_OR_YEAR_MISMATCH")
    return data,sha(raw)

def choose_originals(announcements,sid,report_year,publish_year):
    _,code=sid.split(":")
    regex=re.compile(rf"(?<!\d){report_year}(?:年)?(?:年度报告|年报)")
    candidates=[]
    for item in announcements:
        if str(item.get("secCode") or "")!=code:
            continue
        title=re.sub(r"<[^>]*>","",html.unescape(str(item.get("announcementTitle") or "")))
        compact=re.sub(r"\s+","",title)
        if not regex.search(compact) or any(x.lower() in compact.lower() for x in IGNORE):
            continue
        relative=str(item.get("adjunctUrl") or "")
        path=PDF_PATH.fullmatch(relative)
        if not path or not path.group(1).startswith(f"{publish_year}-"):
            continue
        try:
            notice=datetime.fromtimestamp(int(item["announcementTime"])/1000,tz=BEIJING).date().isoformat()
        except (ValueError,TypeError,OSError,KeyError,OverflowError):
            continue
        if notice!=path.group(1):
            continue
        candidates.append({
            "title":title,
            "notice_day":notice,
            "pdf_document_id":path.group(2)[:-4],
            "original_pdf_url":"https://static.cninfo.com.cn/"+relative,
        })
    # Identical announcement on multiple pages should NOT be counted twice.
    unique={(x["notice_day"],x["pdf_document_id"]):x for x in candidates}
    return sorted(unique.values(),key=lambda x:(x["notice_day"],x["pdf_document_id"]))

def locate(sid,report_year,publish_year,request=_post):
    exchange,code=sid.split(":")
    raw={}
    try:
        names,source=request("information/topSearch/query",{"keyWord":code,"maxNum":"10"})
        raw["issuer_org_lookup"]=source
        matches=names if isinstance(names,list) else (
            names.get("data") or names.get("stockList") or [])
        orgs={str(x["orgId"]) for x in matches if isinstance(x,dict) and
              str(x.get("code"))==code and x.get("orgId")}
        if len(orgs)!=1:
            return {"security_id":sid,
                    "status":"CNINFO_ORG_ID_MISSING_OR_AMBIGUOUS_NOT_PROOF_OF_NO_ISSUER",
                    "org_candidates":sorted(orgs),"original_candidates":[]},raw
        org=next(iter(orgs))
        all_ann=[]
        for p in range(1,PAGE_LIMIT+1):
            response,source=request("hisAnnouncement/query",{
                "stock":code+","+org,"tabName":"fulltext",
                "pageNum":str(p),"pageSize":"30",
                "column":"sse" if exchange=="SSE" else "szse",
                "plate":"","category":"category_ndbg_szsh",
                "seDate":f"{publish_year}-01-01~{publish_year}-12-31",
                "isHLtitle":"true","searchkey":""})
            raw[f"report_page_{p}"]=source
            if not isinstance(response,dict):
                raise ValueError("CNINFO_REPORT_PAGE_NOT_DICT")
            items=response.get("announcements")
            if items is None and int(response.get("totalRecordNum") or 0)==0:
                items=[]
            if not isinstance(items,list):
                raise ValueError("CNINFO_ANNOUNCEMENTS_NOT_LIST")
            all_ann.extend(items)
            if not response.get("hasMore"):
                break
        else:
            raise ValueError("CNINFO_REPORT_PAGINATION_LIMIT")
        candidates=choose_originals(all_ann,sid,report_year,publish_year)
        if not candidates:
            status="REPORT_NOT_DISCOVERED_IN_OFFICIAL_API_NOT_PROOF_OF_ABSENCE"
            chosen=None
        else:
            first=candidates[0]["notice_day"]
            earliest=[x for x in candidates if x["notice_day"]==first]
            chosen=earliest[0] if len(earliest)==1 else None
            status=("ONE_ORIGINAL_ANNUAL_PDF_CANDIDATE" if chosen else
                    "SAME_DAY_MULTIPLE_ORIGINAL_CANDIDATES_NEEDS_PDF_IDENTITY_CHECK")
        return {"security_id":sid,"org_id":org,
                "status":status,"official_annual_metadata_count":len(all_ann),
                "original_candidates":candidates,"chosen":chosen},raw
    except (HTTPError,URLError,TimeoutError,OSError,ValueError,TypeError,KeyError) as exc:
        return {"security_id":sid,
                "status":"SOURCE_QUERY_ERROR_NOT_PROOF_OF_NO_REPORT",
                "error_type":f"HTTP_{exc.code}" if isinstance(exc,HTTPError)
                else type(exc).__name__,
                "original_candidates":[]},raw

def collect(out,limit_per_cohort=128,request=_post,sleep_seconds=.10):
    frames,source_sha=load_frozen_frames()
    if out.exists():
        raise ValueError("REFUSE_TO_OVERWRITE_HISTORICAL_SOURCE_RECEIPT")
    if not 1<=limit_per_cohort<=128:
        raise ValueError("INVALID_BOUNDED_YEAR_COHORT_LIMIT")
    evidence=[]
    raw_bytes={}
    for c in frames["cohorts"]:
        fiscal=int(c["report_period_end"][:4])
        issued=c["expected_issuer_publication_year"]
        outcomes=[]
        failure_streak=0
        for idx,sid in enumerate(c["selected_ids"][:limit_per_cohort],1):
            if failure_streak>=6:
                result,api_raw=({"security_id":sid,
                                 "status":"NOT_QUERIED_AFTER_SIX_CONSECUTIVE_SOURCE_ERRORS",
                                 "original_candidates":[]}, {})
            else:
                result,api_raw=locate(sid,fiscal,issued,request)
                failure_streak=(failure_streak+1 if
                    result["status"]=="SOURCE_QUERY_ERROR_NOT_PROOF_OF_NO_REPORT" else 0)
            result.update({
                "expected_fiscal_period":c["report_period_end"],
                "official_year":issued,
                "metadata_only_not_original_pdf_content_certified":True,
                "financial_statement_field_pit_certified":False,
                "independent_unseen_oos":False,
                "live_buy_eligibility":"NOT_AUTHORIZED",
                "api_response_sha256":{k:sha(v) for k,v in api_raw.items()},
            })
            for name,blob in api_raw.items():
                raw_bytes[f"{c['cohort_id']}/{sid.replace(':','-')}/{name}.json"]=blob
            outcomes.append(result)
            print(f"CNINFO {issued} {idx:03d}/{limit_per_cohort} {sid} "
                  f"{result['status']}",flush=True)
            if sleep_seconds:
                time.sleep(sleep_seconds)
        evidence.append({
            "cohort_id":c["cohort_id"],
            "expected_issue_year":issued,
            "fiscal_year":fiscal,
            "population_count":c["population_count"],
            "frozen_sample_sha256":c["selected_ids_sha256"],
            "attempted_count":len(outcomes),
            "single_source_candidate_count":sum(bool(x.get("chosen")) for x in outcomes),
            "ambiguous_same_day_count":sum(x["status"].startswith("SAME_DAY_MULTIPLE")
                                            for x in outcomes),
            "not_discovered_count":sum(x["status"]==
                    "REPORT_NOT_DISCOVERED_IN_OFFICIAL_API_NOT_PROOF_OF_ABSENCE"
                    for x in outcomes),
            "failed_query_count":sum(x["status"]==
                    "SOURCE_QUERY_ERROR_NOT_PROOF_OF_NO_REPORT" for x in outcomes),
            "unqueried_count":sum(x["status"].startswith("NOT_QUERIED") for x in outcomes),
            "missing_org_id_count":sum(x["status"].startswith("CNINFO_ORG_ID_MISSING")
                                       for x in outcomes),
            "rows":outcomes,
        })
    result={
        "schema":SOURCE_SCHEMA,
        "captured_at_utc":datetime.now(timezone.utc).isoformat(),
        "sealed_prequery_cohorts_manifest_sha256":source_sha,
        "membership_asof_reconstructed_in_2026_not_original_timestamp_sealed":True,
        "original_report_metadata_source":"CNINFO_OFFICIAL_HISTORICAL_ANNOUNCEMENTS",
        "original_2023_2024_pdf_bytes_not_acquired_by_this_job":True,
        "annual_financial_numeric_fields_asof_certified":False,
        "2023_2024_price_outcomes_queried":False,
        "pristine_chronological_oos_validated":False,
        "live_buy_eligibility":"NOT_AUTHORIZED",
        "cohorts":evidence,
    }
    out.mkdir(parents=True)
    rawzip=out/"RAW_CNINFO_2023_2024_RESPONSES.zip"
    with zipfile.ZipFile(rawzip,"w",zipfile.ZIP_DEFLATED,compresslevel=8) as z:
        for name,blob in sorted(raw_bytes.items()):
            z.writestr(name,blob)
    result["raw_api_zip_sha256"]=sha(rawzip.read_bytes())
    (out/"HISTORICAL_256_OFFICIAL_DISCOVERY.json").write_text(
        json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({
        "cohorts":[{k:v for k,v in c.items() if k!="rows"} for c in evidence],
        "raw_sha":result["raw_api_zip_sha256"],"oos":False,
        "BUY":"NOT_AUTHORIZED",
    },ensure_ascii=False),flush=True)
    return result

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--out",type=Path,required=True)
    parser.add_argument("--limit-per-cohort",type=int,default=128)
    a=parser.parse_args()
    collect(a.out,limit_per_cohort=a.limit_per_cohort)

if __name__=="__main__":
    main()
