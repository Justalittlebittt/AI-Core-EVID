#!/usr/bin/env python3
"""Capture release-cutoff-bound core earnings from public F10 main financial records.

Research-only descriptive enrichment of the existing A-tier, no BUY signal.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from v29_growth_raw_quality_audit import _financial_rows

URL = "https://datacenter.eastmoney.com/securities/api/data/v1/get"
REPORT = "RPT_F10_FINANCE_MAINFINADATA"
COLUMNS = ("SECUCODE,SECURITY_CODE,ORG_CODE,REPORT_DATE,NOTICE_DATE,UPDATE_DATE,"
           "KCFJCXSYJLR,KCFJCXSYJLRTZ,PARENTNETPROFIT")
PAGE_SIZE = 500
TIER = "A_BOTH_POSITIVE_NO_ACCOUNTING_FLAGS"


def fetch_page(period, cutoff, page, opener=urlopen):
    date.fromisoformat(period)
    date.fromisoformat(cutoff)
    q = {"reportName": REPORT, "columns": COLUMNS,
         "filter": "(REPORT_DATE='" + period + "')(NOTICE_DATE<'" + cutoff + "')",
         "pageNumber": str(page), "pageSize": str(PAGE_SIZE),
         "sortColumns": "SECURITY_CODE", "sortTypes": "1",
         "source": "HSF10", "client": "PC"}
    req = Request(URL + "?" + urlencode(q), headers={"User-Agent": "Mozilla/5.0"})
    with opener(req, timeout=15) as resp:
        return resp.read(3500000)


def _decode(pages, period, cutoff):
    if not pages or len(pages) > 100:
        raise ValueError("INVALID_SOURCE_PAGES")
    records, hashes, expected = [], [], None
    for i, blob in enumerate(pages, 1):
        if not isinstance(blob, bytes):
            raise ValueError("SOURCE_PAGE_NOT_BYTES")
        obj = json.loads(blob)
        payload = obj.get("result")
        if obj.get("success") is False or not isinstance(payload, dict):
            raise ValueError("F10_SOURCE_RESPONSE_INVALID")
        count, number, data = payload.get("count"), payload.get("pages"), payload.get("data")
        if type(count) is not int or type(number) is not int or not isinstance(data, list):
            raise ValueError("F10_SOURCE_PAGINATION_INVALID")
        if expected is None:
            expected = (count, number)
        elif expected != (count, number):
            raise ValueError("F10_SOURCE_PAGINATION_CHANGED")
        hashes.append({"page": i, "sha256": hashlib.sha256(blob).hexdigest(), "rows": len(data)})
        records.extend(data)
    if expected[0] != len(records) or expected[1] != len(pages):
        raise ValueError("F10_SOURCE_PAGINATION_INCOMPLETE")
    index = {}
    for row in records:
        if row.get("REPORT_DATE", "")[:10] != period:
            raise ValueError("F10_PERIOD_MISMATCH")
        if not row.get("NOTICE_DATE") or row["NOTICE_DATE"][:10] >= cutoff:
            raise ValueError("F10_NOTICE_OUTSIDE_CUTOFF")
        code, secucode = row.get("SECURITY_CODE"), row.get("SECUCODE")
        if not isinstance(code, str) or not isinstance(secucode, str) or secucode not in (code + ".SZ", code + ".SH"):
            continue
        sid = ("SSE:" if secucode.endswith(".SH") else "SZSE:") + code
        index.setdefault(sid, []).append(row)
    return index, hashes, len(records)


def collect(period, cutoff, opener=urlopen):
    first = fetch_page(period, cutoff, 1, opener)
    obj = json.loads(first)
    data = obj.get("result")
    if not isinstance(data, dict) or type(data.get("pages")) is not int or not 1 <= data["pages"] <= 100:
        raise ValueError("F10_SOURCE_PAGE_COUNT_INVALID")
    pages = [first] + [fetch_page(period, cutoff, i, opener) for i in range(2, data["pages"]+1)]
    return pages


def _value(row, key):
    v = row.get(key)
    if v is None or isinstance(v, bool):
        return None
    try:
        n = float(v)
        return n if math.isfinite(n) else None
    except (ValueError, TypeError):
        return None


def _select(index, sid, raw, cutoff):
    """One unambiguous, matching identity+date+netprofit row or explicit unknown."""
    rows = index.get(sid, [])
    matched = [r for r in rows
               if str(r.get("ORG_CODE")) == str(raw.get("ORG_CODE"))
               and (r.get("NOTICE_DATE") or "")[:10] == (raw.get("NOTICE_DATE") or "")[:10]]
    if len(matched) != 1:
        return None, "NO_UNIQUE_IDENTITY_AND_DISCLOSURE_MATCH"
    row = matched[0]
    if row.get("UPDATE_DATE") and row["UPDATE_DATE"][:10] >= cutoff:
        return None, "F10_UPDATED_AFTER_CUTOFF"
    parent, original = _value(row, "PARENTNETPROFIT"), _value(raw, "PARENT_NETPROFIT")
    if parent is None or original is None or not math.isclose(parent, original, abs_tol=1, rel_tol=0):
        return None, "PARENT_PROFIT_SOURCE_CONFLICT"
    return row, None


def enrich(review, summary_latest_pages, summary_prior_pages, core_latest_pages, core_prior_pages):
    if review.get("schema") != "AI_CORE_EVID_GROWTH_RESEARCH_REVIEW_V1" or review.get("live_buy_eligibility") != "NOT_AUTHORIZED":
        raise ValueError("INVALID_GROWTH_RESEARCH_INPUT")
    cutoff = review.get("notice_cutoff_exclusive")
    if not cutoff:
        raise ValueError("MISSING_NOTICE_CUTOFF")
    latest = _financial_rows(summary_latest_pages, review["latest_source_page_hashes"],
                             review["latest_period"], cutoff)
    prior = _financial_rows(summary_prior_pages, review["prior_source_page_hashes"],
                            review["prior_period"], cutoff)
    q3, q3_hashes, q3_n = _decode(core_latest_pages, review["latest_period"], cutoff)
    h1, h1_hashes, h1_n = _decode(core_prior_pages, review["prior_period"], cutoff)
    selected = [r for r in review["full_research_list"] if r["review_tier"] == TIER]
    if len(selected) != review["counts"]["both_positive_no_accounting_flags"]:
        raise ValueError("A_TIER_COUNT_MISMATCH")
    rows, counts = [], {"reviewed_a_tier": len(selected), "both_periods_matched": 0,
                        "latest_core_profit_available": 0, "both_core_profit_available": 0,
                        "latest_core_profit_nonpositive": 0,
                        "standalone_q3_core_profit_nonpositive": 0, "unmatched_or_missing": 0}
    seen = set()
    for item in sorted(selected, key=lambda r:r["security_id"]):
        sid = item["security_id"]
        if sid in seen or sid not in latest or sid not in prior:
            raise ValueError("DUPLICATE_OR_MISSING_ORIGINAL_ISSUER")
        seen.add(sid)
        now, issue_now = _select(q3, sid, latest[sid], cutoff)
        old, issue_old = _select(h1, sid, prior[sid], cutoff)
        flags = [f"Q3_{issue_now}" for _ in [0] if issue_now] + [f"H1_{issue_old}" for _ in [0] if issue_old]
        recent = _value(now, "KCFJCXSYJLR") if now else None
        earlier = _value(old, "KCFJCXSYJLR") if old else None
        if now and old: counts["both_periods_matched"] += 1
        if recent is not None: counts["latest_core_profit_available"] += 1
        if recent is not None and earlier is not None: counts["both_core_profit_available"] += 1
        q3_increment = recent-earlier if recent is not None and earlier is not None else None
        parent_now = _value(now, "PARENTNETPROFIT") if now else None
        share = (parent_now-recent)/parent_now if parent_now and recent is not None else None
        if recent is None: flags.append("Q3_DEDUCTED_PARENT_PROFIT_NOT_VERIFIED")
        elif recent <= 0:
            counts["latest_core_profit_nonpositive"] += 1
            flags.append("Q3_CUMULATIVE_CORE_PROFIT_NONPOSITIVE")
        if q3_increment is not None and q3_increment <= 0:
            counts["standalone_q3_core_profit_nonpositive"] += 1
            flags.append("STANDALONE_Q3_CORE_PROFIT_NONPOSITIVE")
        if not (now and old): counts["unmatched_or_missing"] += 1
        rows.append({
            "security_id": sid, "name": item.get("name"),
            "q3_deducted_parent_profit_yuan": recent,
            "h1_deducted_parent_profit_yuan": earlier,
            "standalone_q3_deducted_parent_profit_yuan_cumulative_difference": q3_increment,
            "q3_core_profit_yoy_pct_vendor": _value(now, "KCFJCXSYJLRTZ") if now else None,
            "q3_nonrecurring_component_share_of_parent_profit": share,
            "source_match_status": "MATCHED_BOTH" if now and old else "SOURCE_INCOMPLETE",
            "review_flags": flags, "official_filings_independently_verified": False,
            "buy_eligibility": "NOT_AUTHORIZED"})
    return {"schema":"AI_CORE_EVID_GROWTH_CORE_EARNINGS_ENRICHMENT_V1",
            "report_periods":[review["prior_period"],review["latest_period"]],
            "notice_cutoff_exclusive":cutoff,
            "capture_timestamp_utc":datetime.now(timezone.utc).isoformat(),
            "source":"EASTMONEY_UNOFFICIAL_F10_MAINFINADATA",
            "source_report":REPORT,
            "source_core_latest_rows":q3_n,"source_core_prior_rows":h1_n,
            "core_latest_page_hashes":q3_hashes,"core_prior_page_hashes":h1_hashes,
            "financial_review_sha256":hashlib.sha256(json.dumps(review,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest(),
            "counts":counts,"quality_rows":rows,
            "historical_pit_issuer_timing_independently_certified":False,
            "return_or_alpha_validated":False,"live_buy_eligibility":"NOT_AUTHORIZED"}


def _pages(folder):
    result = [p.read_bytes() for p in sorted(folder.glob("page-*.json"))]
    if not result:
        raise ValueError("MISSING_ORIGINAL_RAW_CAPTURE_PAGES")
    return result


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--financial-review",required=True,type=Path)
    p.add_argument("--financial-raw-dir",required=True,type=Path)
    p.add_argument("--core-raw-dir",required=True,type=Path)
    p.add_argument("--output",required=True,type=Path)
    a=p.parse_args()
    if a.core_raw_dir.exists() or a.output.exists():
        p.error("Cannot overwrite original evidence")
    review=json.loads(a.financial_review.read_text(encoding="utf-8"))
    cutoff=review["notice_cutoff_exclusive"]
    raw_latest=collect(review["latest_period"],cutoff)
    raw_prior=collect(review["prior_period"],cutoff)
    result=enrich(review,_pages(a.financial_raw_dir/"latest"),_pages(a.financial_raw_dir/"prior"),raw_latest,raw_prior)
    for label, pages in (("latest",raw_latest),("prior",raw_prior)):
        directory=a.core_raw_dir/label
        directory.mkdir(parents=True,exist_ok=False)
        for i,b in enumerate(pages,1):
            (directory/f"page-{i:03d}.json").write_bytes(b)
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"counts":result["counts"],"latest_source_rows":result["source_core_latest_rows"],
                      "prior_source_rows":result["source_core_prior_rows"],
                      "examples":result["quality_rows"][:4],"live_buy_eligibility":"NOT_AUTHORIZED"},ensure_ascii=False,indent=2))


if __name__=="__main__":
    main()
