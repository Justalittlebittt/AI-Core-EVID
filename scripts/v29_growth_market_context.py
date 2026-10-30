#!/usr/bin/env python3
"""Attach capture-time market valuation and turnover context to A-tier growth research.

Not an alpha model, historical PIT replay, current trading recommendation or execution
service. Reuses the prior two-period report; never touches frozen E-layer evidence.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

ENDPOINT = "https://push2.eastmoney.com/api/qt/ulist.np/get"
FIELDS = "f12,f13,f14,f2,f6,f9,f23,f124,f20,f21,f100"
SID = re.compile(r"^(SSE|SZSE):([0-9]{6})$")
TIER = "A_BOTH_POSITIVE_NO_ACCOUNTING_FLAGS"
BATCH_SIZE = 30
SCHEMA = "AI_CORE_EVID_GROWTH_RESEARCH_REVIEW_V1"


def _float(value, positive=False):
    if isinstance(value, bool):
        return None
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(n) or (n <= 0 if positive else n < 0):
        return None
    return n


def _market_id(security_id):
    match = SID.fullmatch(security_id)
    if match is None:
        raise ValueError("INVALID_A_SHARE_SECURITY_ID")
    return ("1." if match[1] == "SSE" else "0.") + match[2]


def fetch_market_batch(security_ids, opener=urlopen):
    ids = [_market_id(sid) for sid in security_ids]
    if not ids or len(ids) > BATCH_SIZE or len(ids) != len(set(ids)):
        raise ValueError("INVALID_QUOTE_BATCH")
    url = ENDPOINT + "?" + urlencode({
        "fltt": 2, "invt": 2, "fields": FIELDS, "secids": ",".join(ids)
    })
    req = Request(url, headers={
        "User-Agent": "AI-Core-EVID-Research/1.0",
        "Referer": "https://quote.eastmoney.com/"
    })
    with opener(req, timeout=15) as resp:
        return resp.read(500000)


def _decode_batch(raw, expected):
    if not isinstance(raw, bytes):
        raise ValueError("RAW_MARKET_BYTES_REQUIRED")
    data = json.loads(raw)
    if data.get("rc") != 0 or not isinstance(data.get("data"), dict):
        raise ValueError("MARKET_PROVIDER_RESPONSE_INVALID")
    result = data["data"]
    rows = result.get("diff")
    if isinstance(rows, dict):
        rows = list(rows.values())
    if not isinstance(rows, list):
        raise ValueError("MARKET_PROVIDER_ROWS_MISSING")
    decoded = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("MARKET_ROW_INVALID")
        code, exchange = row.get("f12"), row.get("f13")
        if not isinstance(code, str) or not re.fullmatch(r"[0-9]{6}", code) or exchange not in (0, 1):
            raise ValueError("INVALID_MARKET_IDENTITY")
        sid = ("SSE:" if exchange == 1 else "SZSE:") + code
        if sid not in expected or sid in decoded:
            raise ValueError("UNEXPECTED_OR_DUPLICATE_MARKET_SECURITY")
        decoded[sid] = row
    return decoded


def enrich(review, market_pages, captured_at, max_age_minutes=90, queue_limit=20):
    if review.get("schema") != SCHEMA or review.get("live_buy_eligibility") != "NOT_AUTHORIZED":
        raise ValueError("INVALID_RESEARCH_REVIEW")
    if review.get("strategy_validated") is not False:
        raise ValueError("UNEXPECTED_RESEARCH_VALIDITY")
    if type(queue_limit) is not int or not 1 <= queue_limit <= 100:
        raise ValueError("INVALID_QUEUE_LIMIT")
    if type(max_age_minutes) not in (int, float) or not 1 <= max_age_minutes <= 1440:
        raise ValueError("INVALID_MAX_AGE")
    capture = datetime.fromisoformat(captured_at)
    if capture.tzinfo is None or capture.utcoffset() is None:
        raise ValueError("CAPTURE_TIME_REQUIRES_OFFSET")
    if not review.get("latest_source_page_hashes") or not review.get("prior_source_page_hashes"):
        raise ValueError("FINANCIAL_SOURCE_UNBOUND")
    full = review.get("full_research_list")
    if not isinstance(full, list) or not full:
        raise ValueError("RESEARCH_LIST_MISSING")
    eligible = [r for r in full if r.get("review_tier") == TIER]
    if len(eligible) != review["counts"]["both_positive_no_accounting_flags"]:
        raise ValueError("A_TIER_COUNT_MISMATCH")
    securities = [r["security_id"] for r in eligible]
    if len(securities) != len(set(securities)):
        raise ValueError("DUPLICATE_RESEARCH_ID")
    securities.sort()
    expected_pages = [securities[i:i+BATCH_SIZE] for i in range(0, len(securities), BATCH_SIZE)]
    if len(market_pages) != len(expected_pages):
        raise ValueError("QUOTE_BATCH_COUNT_MISMATCH")
    quotes, raw_evidence = {}, []
    for i, (raw, batch) in enumerate(zip(market_pages, expected_pages), 1):
        decoded = _decode_batch(raw, set(batch))
        quotes.update(decoded)
        raw_evidence.append({
            "batch": i, "requested_count": len(batch), "returned_count": len(decoded),
            "raw_sha256": hashlib.sha256(raw).hexdigest()
        })
    captured = capture.astimezone(timezone.utc)
    result, counts = [], {
        "a_tier_requested": len(securities), "quotes_returned": len(quotes),
        "fresh_quote_context": 0, "quote_missing_or_stale": 0,
        "pe_positive_available": 0, "pb_positive_available": 0
    }
    for item in sorted(eligible, key=lambda x: x["security_id"]):
        sid = item["security_id"]
        row = quotes.get(sid)
        status, flags = "MISSING_QUOTE", []
        fields = {"quote_time": None, "observed_session_date": None,
                  "last_indicated_price_yuan": None, "reported_pe_f9": None,
                  "reported_pb_f23": None, "session_turnover_yuan_f6": None,
                  "total_market_cap_yuan_f20": None,
                  "float_market_cap_yuan_f21": None, "industry_vendor_f100": None}
        if row is not None:
            ts = row.get("f124")
            if type(ts) is not int or ts <= 0:
                status = "VENDOR_TIMESTAMP_MISSING"
            else:
                quoted = datetime.fromtimestamp(ts, timezone.utc)
                fields["quote_time"] = quoted.isoformat()
                fields["observed_session_date"] = quoted.astimezone(
                    ZoneInfo("Asia/Shanghai")).date().isoformat()
                age = (captured - quoted).total_seconds()
                price = _float(row.get("f2"), positive=True)
                if age < 0:
                    status = "VENDOR_QUOTE_FROM_FUTURE"
                elif age > max_age_minutes * 60:
                    status = "STALE_VENDOR_QUOTE"
                elif price is None:
                    status = "INVALID_VENDOR_PRICE"
                else:
                    status = "FRESH_OBSERVED_VENDOR_QUOTE"
                    fields.update({
                        "last_indicated_price_yuan": price,
                        "reported_pe_f9": _float(row.get("f9"), positive=True),
                        "reported_pb_f23": _float(row.get("f23"), positive=True),
                        "session_turnover_yuan_f6": _float(row.get("f6")),
                        "total_market_cap_yuan_f20": _float(row.get("f20"), positive=True),
                        "float_market_cap_yuan_f21": _float(row.get("f21"), positive=True),
                        "industry_vendor_f100": row.get("f100") if isinstance(row.get("f100"), str) else None
                    })
                    counts["fresh_quote_context"] += 1
                    if fields["reported_pe_f9"] is not None:
                        counts["pe_positive_available"] += 1
                    else:
                        flags.append("PE_NOT_USABLE_OR_NONPOSITIVE")
                    if fields["reported_pb_f23"] is not None:
                        counts["pb_positive_available"] += 1
                    else:
                        flags.append("PB_NOT_USABLE_OR_NONPOSITIVE")
                    if fields["session_turnover_yuan_f6"] is None:
                        flags.append("TURNOVER_NOT_AVAILABLE")
        if status != "FRESH_OBSERVED_VENDOR_QUOTE":
            counts["quote_missing_or_stale"] += 1
            flags.append(status)
        result.append({
            "security_id": sid, "name_from_financial_report": item.get("name"),
            "finance_report_date": item["recent_report_date"],
            "finance_disclosure_date": item["recent_notice_date"],
            "revenue_yoy_pct": item["revenue_yoy_pct_latest"],
            "profit_yoy_pct": item["profit_yoy_pct_latest"],
            "financial_review_tier": TIER,
            "market_context_status": status, **fields,
            "review_flags": flags,
            "valuation_fairness_established": False,
            "tradability_verified": False,
            "buy_eligibility": "NOT_AUTHORIZED"
        })
    digest = hashlib.sha256(json.dumps(
        review, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode()).hexdigest()
    return {
        "schema": "AI_CORE_EVID_GROWTH_MARKET_CONTEXT_V1",
        "financial_review_sha256": digest, "latest_finance_period": review["latest_period"],
        "notice_cutoff_exclusive": review.get("notice_cutoff_exclusive"),
        "market_captured_at": captured_at,
        "market_source": "EASTMONEY_PUSH2_UNOFFICIAL_SNAPSHOT",
        "market_fields": {"f2": "INDICATED_PRICE", "f6": "SESSION_AMOUNT",
                          "f9": "VENDOR_PE_UNVERIFIED_BASIS",
                          "f23": "VENDOR_PB_UNVERIFIED_BASIS",
                          "f20": "TOTAL_MARKET_CAP", "f21": "FLOAT_MARKET_CAP",
                          "f100": "VENDOR_INDUSTRY", "f124": "VENDOR_UNIX_QUOTE_TIME"},
        "raw_quote_batch_provenance": raw_evidence,
        "counts": counts, "queue": result[:queue_limit], "full_research_list": result,
        "no_cross_sectional_alpha_ranking": True,
        "financial_source_vintage_and_market_capture_not_same_time": True,
        "historical_pit_replay_authorized": False,
        "valuation_fairness_validated": False,
        "strategy_validated": False, "live_buy_eligibility": "NOT_AUTHORIZED"
    }


def capture_review(review, opener=urlopen, max_age_minutes=90, queue_limit=20):
    ids = sorted(row["security_id"] for row in review["full_research_list"]
                 if row.get("review_tier") == TIER)
    if len(ids) != review["counts"]["both_positive_no_accounting_flags"]:
        raise ValueError("A_TIER_COUNT_MISMATCH")
    batches = [fetch_market_batch(ids[i:i+BATCH_SIZE], opener=opener)
               for i in range(0, len(ids), BATCH_SIZE)]
    at = datetime.now(timezone.utc).isoformat()
    return enrich(review, batches, at, max_age_minutes, queue_limit), batches


def main():
    p = argparse.ArgumentParser(description="Add observed market context to financial growth research; no BUY.")
    p.add_argument("--review-json", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--raw-dir", type=Path, required=True)
    p.add_argument("--max-age-minutes", type=float, default=90)
    p.add_argument("--queue-limit", type=int, default=20)
    a = p.parse_args()
    if a.output.exists() or a.raw_dir.exists():
        p.error("Output exists: original vintage must not be overwritten")
    review = json.loads(a.review_json.read_text(encoding="utf-8"))
    report, batches = capture_review(review, max_age_minutes=a.max_age_minutes,
                                    queue_limit=a.queue_limit)
    a.raw_dir.mkdir(parents=True)
    for i, raw in enumerate(batches, 1):
        (a.raw_dir / f"quote-batch-{i:03d}.json").write_bytes(raw)
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(json.dumps({"market_captured_at": report["market_captured_at"],
                      "counts": report["counts"], "queue": report["queue"],
                      "live_buy_eligibility": "NOT_AUTHORIZED"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
