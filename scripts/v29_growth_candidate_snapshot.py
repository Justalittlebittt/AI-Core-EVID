#!/usr/bin/env python3
"""Capture public A-share financial growth candidates; RESEARCH ONLY, never a BUY signal."""
import argparse
import hashlib
import json
import math
import re
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"
REPORT = "RPT_LICO_FN_CPD"
CODE = re.compile(r"^([0-9]{6})\.(SH|SZ)$")
SH = ("600", "601", "603", "605", "688", "689")
SZ = ("000", "001", "002", "003", "300", "301")


def _date(value):
    if not isinstance(value, str) or len(value) < 10:
        raise ValueError("DATE_UNAVAILABLE")
    return date.fromisoformat(value[:10])


def _num(value):
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (ValueError, TypeError):
        return None


def _security(row):
    symbol = row.get("SECUCODE")
    match = CODE.fullmatch(symbol) if isinstance(symbol, str) else None
    if not match or match[1] != row.get("SECURITY_CODE"):
        return None
    if match[2] == "SH" and match[1].startswith(SH):
        return "SSE:" + match[1]
    if match[2] == "SZ" and match[1].startswith(SZ):
        return "SZSE:" + match[1]
    return None


def fetch_page(report_date, page, opener=urlopen, notice_before=None):
    params = {"reportName": REPORT, "columns": "ALL",
              "filter": "(REPORTDATE='" + report_date + "')",
              "pageSize": "500", "pageNumber": str(page),
              "sortColumns": "SECURITY_CODE", "sortTypes": "1",
              "source": "WEB", "client": "WEB"}
    if notice_before is not None:
        date.fromisoformat(notice_before)
        params["filter"] += "(NOTICE_DATE<'" + notice_before + "')"
    request = Request(URL + "?" + urlencode(params),
                      headers={"User-Agent": "AI-Core-EVID-Research/1.0"})
    with opener(request, timeout=15) as response:
        return response.read(5_000_000)


def build_snapshot(report_date, pages, captured_at, notice_before=None):
    period = date.fromisoformat(report_date)
    observed = datetime.fromisoformat(captured_at)
    if observed.tzinfo is None or observed.utcoffset() is None:
        raise ValueError("CAPTURE_TIME_REQUIRES_OFFSET")
    capture_day = observed.astimezone(ZoneInfo("Asia/Shanghai")).date()
    if period > capture_day:
        raise ValueError("REPORT_PERIOD_IN_FUTURE")
    if notice_before is not None and date.fromisoformat(notice_before) > capture_day:
        raise ValueError("NOTICE_CUTOFF_AFTER_CAPTURE_DAY")
    if not pages or len(pages) > 40:
        raise ValueError("INVALID_CAPTURE_PAGE_COUNT")
    records, hashes = [], []
    expected = None
    for page_no, raw in enumerate(pages, 1):
        if not isinstance(raw, bytes):
            raise ValueError("RAW_CAPTURE_BYTES_REQUIRED")
        payload = json.loads(raw)
        result = payload.get("result")
        if payload.get("success") is False or not isinstance(result, dict):
            raise ValueError("PROVIDER_RESPONSE_INVALID")
        count, total, data = result.get("count"), result.get("pages"), result.get("data")
        if type(count) is not int or count <= 0 or type(total) is not int or total <= 0 or not isinstance(data, list):
            raise ValueError("PROVIDER_PAGINATION_INVALID")
        if expected is None:
            expected = (count, total)
        if expected != (count, total):
            raise ValueError("PROVIDER_PAGINATION_CHANGED")
        records.extend(data)
        hashes.append({"page": page_no, "sha256": hashlib.sha256(raw).hexdigest(), "rows": len(data)})
    if len(records) != expected[0] or len(pages) != expected[1]:
        raise ValueError("PROVIDER_PAGINATION_INCOMPLETE")
    seen, candidates = set(), []
    counts = {"non_a_share": 0, "missing_notice": 0,
              "missing_values": 0, "not_positive_growth": 0}
    for row in records:
        sid = _security(row)
        if sid is None:
            counts["non_a_share"] += 1
            continue
        if sid in seen:
            raise ValueError("DUPLICATE_SECURITY_REPORT")
        seen.add(sid)
        if _date(row.get("REPORTDATE")) != period:
            raise ValueError("REPORT_PERIOD_MISMATCH")
        notice = row.get("NOTICE_DATE")
        if not notice:
            counts["missing_notice"] += 1
            continue
        published = _date(notice)
        if published > capture_day:
            raise ValueError("FUTURE_DISCLOSURE_DATE")
        if notice_before is not None and published >= date.fromisoformat(notice_before):
            raise ValueError("DISCLOSURE_OUTSIDE_SNAPSHOT_CUTOFF")
        values = [_num(row.get(f)) for f in
                  ("TOTAL_OPERATE_INCOME", "PARENT_NETPROFIT", "YSTZ", "SJLTZ")]
        if any(v is None for v in values):
            counts["missing_values"] += 1
            continue
        if min(values) <= 0:
            counts["not_positive_growth"] += 1
            continue
        cfo, roe = _num(row.get("MGJYXJJE")), _num(row.get("WEIGHTAVG_ROE"))
        flags = []
        if cfo is None or cfo <= 0:
            flags.append("CASH_FLOW_MISSING_OR_NONPOSITIVE")
        if roe is None or roe <= 0:
            flags.append("ROE_MISSING_OR_NONPOSITIVE")
        candidates.append({
            "security_id": sid, "name": row.get("SECURITY_NAME_ABBR"),
            "report_date": report_date, "notice_date": published.isoformat(),
            "revenue_yuan": values[0], "parent_profit_yuan": values[1],
            "revenue_yoy_pct": values[2], "parent_profit_yoy_pct": values[3],
            "operating_cash_flow_per_share_yuan": cfo, "roe_pct": roe,
            "review_flags": flags, "status": "RESEARCH_CANDIDATE_ONLY",
            "buy_eligibility": "NOT_AUTHORIZED"})
    candidates.sort(key=lambda r: (-r["revenue_yoy_pct"], r["security_id"]))
    return {"schema": "AI_CORE_EVID_GROWTH_CANDIDATE_SNAPSHOT_V1",
            "source": "UNOFFICIAL_EASTMONEY_FINANCIAL_AGGREGATE",
            "report": REPORT, "report_date": report_date,
            "notice_cutoff_exclusive": notice_before,
            "captured_at": observed.isoformat(), "raw_page_hashes": hashes,
            "total_source_rows": len(records), "evaluated_a_share_rows": len(seen),
            "counts": counts, "candidate_count": len(candidates),
            "candidates": candidates,
            "selection_rule": "POSITIVE_REVENUE_PROFIT_AND_REPORTED_YOY_GROWTH",
            "historical_replay_pit_certified": False,
            "official_disclosure_verification_complete": False,
            "strategy_validated": False, "live_buy_eligibility": "NOT_AUTHORIZED"}


def collect(report_date, opener=urlopen, notice_before=None):
    first = fetch_page(report_date, 1, opener, notice_before=notice_before)
    result = json.loads(first).get("result")
    if not isinstance(result, dict) or type(result.get("pages")) is not int:
        raise ValueError("PROVIDER_RESPONSE_INVALID")
    total = result["pages"]
    if not 1 <= total <= 40:
        raise ValueError("PAGE_LIMIT_EXCEEDED")
    raw = [first] + [fetch_page(report_date, i, opener, notice_before=notice_before) for i in range(2, total + 1)]
    return build_snapshot(report_date, raw, datetime.now(timezone.utc).isoformat(), notice_before), raw


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--report-date", required=True)
    p.add_argument("--notice-before", help="Exclusive disclosure-date cutoff, e.g. 2026-10-30")
    p.add_argument("--raw-dir", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    if args.raw_dir.exists() or args.output.exists():
        p.error("Output exists: do not overwrite a previous evidence capture")
    result, pages = collect(args.report_date, notice_before=args.notice_before)
    args.raw_dir.mkdir(parents=True)
    for i, raw in enumerate(pages, 1):
        (args.raw_dir / f"page-{i:03d}.json").write_bytes(raw)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"report_date": result["report_date"],
                      "captured_at": result["captured_at"],
                      "candidate_count": result["candidate_count"],
                      "top_ten": result["candidates"][:10],
                      "live_buy_eligibility": "NOT_AUTHORIZED"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
