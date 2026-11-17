#!/usr/bin/env python3
"""Discover official Q3 filing PDF metadata for frozen 2021/22 cohorts.

Reuses the repo's CNINFO _post transport. Metadata only; does not download PDFs,
open stock returns, modify the candidate cohort, or promote alpha.
"""
import argparse
import hashlib
import html
import json
import re
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError

from v29_original_report_discovery_128 import _post

RECEIPT = Path("research/V3.1_2021_2022_FIXED_TOP10_SOURCE_ONLY_RECEIPT_20261117.json")
BEIJING = timezone(timedelta(hours=8))
TITLE = re.compile(r"(2021|2022)年?第三季度报告")
BAD = ("摘要", "更正", "修订", "补充", "取消", "已取消", "英文", "提示性")
PDF = re.compile(r"finalpage/(20\d\d-\d\d-\d\d)/(\d+\.PDF)$", re.I)


def choose(row, code, year):
    candidate = []
    for a in row:
        if str(a.get("secCode") or "") != code:
            continue
        title = re.sub(r"\s+", "", re.sub("<[^>]+>", "", html.unescape(str(a.get("announcementTitle") or ""))))
        if not TITLE.search(title) or not title.startswith(str(year)) or any(b in title for b in BAD):
            continue
        url = str(a.get("adjunctUrl") or "")
        found = PDF.fullmatch(url)
        if not found or not found.group(1).startswith(str(year)):
            continue
        try:
            notice = datetime.fromtimestamp(int(a["announcementTime"])/1000, tz=BEIJING).date().isoformat()
        except (ValueError, KeyError, TypeError, OverflowError):
            continue
        if abs((datetime.strptime(notice,"%Y-%m-%d").date() -
                datetime.strptime(found.group(1),"%Y-%m-%d").date()).days) > 1:
            continue
        candidate.append({"title": title,"publication_day":notice,
                          "original_pdf_url":"https://static.cninfo.com.cn/"+url,
                          "document_id":found.group(2)[:-4]})
    return sorted({(x["publication_day"],x["document_id"]):x for x in candidate}.values(),
                  key=lambda x:(x["publication_day"],x["document_id"]))


def discover(symbol, year):
    code = symbol[:6]
    column = "sse" if symbol.endswith(".SH") else "szse"
    try:
        matches, lookup_raw = _post("information/topSearch/query", {"keyWord":code,"maxNum":"10"})
        matches = matches if isinstance(matches,list) else (matches.get("data") or matches.get("stockList") or [])
        orgs={str(r["orgId"]) for r in matches if isinstance(r,dict) and str(r.get("code"))==code and r.get("orgId")}
        if len(orgs)!=1:
            return {"status":"ORG_ID_AMBIGUOUS_OR_MISSING","orgs":sorted(orgs)}, {"lookup_sha256":hashlib.sha256(lookup_raw).hexdigest()}
        org=next(iter(orgs))
        filings=[]
        hashes={"lookup_sha256":hashlib.sha256(lookup_raw).hexdigest()}
        for page in range(1,4):
            payload, raw = _post("hisAnnouncement/query",{
                "stock":code+","+org, "tabName":"fulltext","pageNum":str(page),"pageSize":"30",
                "column":column,"plate":"","category":"",
                "seDate":f"{year}-10-01~{year}-11-15","isHLtitle":"true","searchkey":""})
            hashes[f"page{page}_sha256"]=hashlib.sha256(raw).hexdigest()
            records=payload.get("announcements")
            if not isinstance(records,list):
                if int(payload.get("totalRecordNum") or 0)==0: records=[]
                else: return {"status":"INVALID_CNINFO_RECORDS"},hashes
            filings.extend(records)
            if not payload.get("hasMore"):
                break
        else:
            return {"status":"CNINFO_PAGINATION_EXCEEDED"},hashes
        candidates=choose(filings,code,year)
        if len(candidates)==1:
            state="ONE_OFFICIAL_Q3_PDF_CANDIDATE"
        elif not candidates:
            state="NO_OFFICIAL_Q3_PDF_DISCOVERED"
        else:
            state="MULTIPLE_Q3_PDFS_CHECK_VERSION"
        return {"status":state,"candidates":candidates,"raw_response_sha256":hashes},{}
    except (HTTPError,URLError,TimeoutError,OSError,ValueError,KeyError,TypeError) as exc:
        return {"status":"OFFICIAL_QUERY_ERROR","error_type":type(exc).__name__}, {}


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--output",type=Path,required=True)
    args=p.parse_args()
    raw=RECEIPT.read_bytes()
    receipt=json.loads(raw)
    if receipt["schema"]!="V31_FIXED_Q3_EVALUATION_CANDIDATE_SOURCE_ONLY_RECEIPT_V1": raise ValueError("RECEIPT_SCHEMA_CHANGED")
    rows=[]
    failure_streak=0
    for year in (2021,2022):
        for item in receipt[f"year_{year}"]:
            code,day=item[0],str(item[1])
            if failure_streak>=6:
                result={"status":"NOT_QUERIED_AFTER_SIX_ERRORS"}
            else:
                result,_=discover(code,year)
                failure_streak=(failure_streak+1 if result["status"]=="OFFICIAL_QUERY_ERROR" else 0)
            candidates=result.get("candidates",[])
            date_match=bool(len(candidates)==1 and candidates[0]["publication_day"].replace("-","")==day)
            rows.append({"security_id":code,"report_year":year,"vendor_notice_date":day,
                         "official_notice_matches_vendor":date_match, **result})
            print("OFFICIAL_Q3_DISCOVERY",year,code,result["status"],"NOTICE_MATCH",date_match,flush=True)
            time.sleep(.1)
    status=Counter(x["status"] for x in rows)
    output={"schema":"V31_FIXED_TOP10_OFFICIAL_Q3_PDF_METADATA_DISCOVERY_V1",
            "frozen_receipt_sha256":hashlib.sha256(raw).hexdigest(),
            "discovery_counts":dict(status),"rows":rows,
            "official_Q3_PDF_binary_contents_verified":False,
            "as_published_financial_3_fields_verified_for_all":False,
            "stock_prices_or_returns_requested":False,"trade_authorized":False}
    args.output.write_text(json.dumps(output,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("FIXED_TOP10_OFFICIAL_Q3_METADATA_SUMMARY="+json.dumps({
        "counts":dict(status),"notice_matches":sum(x["official_notice_matches_vendor"] for x in rows),
        "total":len(rows),"stock_prices_or_returns_requested":False},ensure_ascii=False),flush=True)

if __name__=="__main__":
    main()
