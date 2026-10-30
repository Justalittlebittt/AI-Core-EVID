#!/usr/bin/env python3
"""Audit existing captured growth candidates against their original published financial rows.

This is descriptive data quality, NOT predictor validation or stock trading advice.
Avoid post-hoc alpha ranking, frozen E-layer, Fold3/Fold4, or brokerage access.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from pathlib import Path

TIER = "A_BOTH_POSITIVE_NO_ACCOUNTING_FLAGS"
ST_NAME = re.compile(r"^\*?ST", re.IGNORECASE)


def _amount(row, field):
    value = row.get(field)
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _financial_rows(pages, receipt, period, cutoff):
    """Check source hashes and material identity once at the raw-data boundary."""
    if len(pages) != len(receipt) or not pages:
        raise ValueError("SOURCE_PAGES_INCOMPLETE")
    by_id = {}
    for i, (raw, provenance) in enumerate(zip(pages, receipt), 1):
        if provenance["page"] != i or hashlib.sha256(raw).hexdigest() != provenance["sha256"]:
            raise ValueError("RAW_FINANCIAL_SOURCE_HASH_MISMATCH")
        payload = json.loads(raw)
        rows = payload["result"]["data"]
        for row in rows:
            code, symbol = row.get("SECURITY_CODE"), row.get("SECUCODE", "")
            if not isinstance(symbol, str) or symbol not in (str(code)+".SH", str(code)+".SZ"):
                continue
            if row.get("REPORTDATE", "")[:10] != period:
                raise ValueError("FINANCIAL_REPORT_PERIOD_CHANGED")
            if row.get("NOTICE_DATE", "")[:10] >= cutoff:
                raise ValueError("DISCLOSURE_AFTER_FROZEN_CAPTURE_CUTOFF")
            sid = ("SSE:" if symbol.endswith(".SH") else "SZSE:")+str(code)
            if sid in by_id:
                raise ValueError("DUPLICATE_RAW_FINANCIAL_ID")
            by_id[sid] = row
    return by_id


def audit(review, latest_pages, prior_pages):
    """Retain the original A-tier, attach source-coverage and quality warnings."""
    if review.get("schema") != "AI_CORE_EVID_GROWTH_RESEARCH_REVIEW_V1" or review.get("live_buy_eligibility") != "NOT_AUTHORIZED":
        raise ValueError("INVALID_GROWTH_RESEARCH_REPORT")
    cutoff = review.get("notice_cutoff_exclusive")
    if not cutoff:
        raise ValueError("NOTICE_CUTOFF_MISSING")
    current = _financial_rows(latest_pages, review["latest_source_page_hashes"],
                              review["latest_period"], cutoff)
    previous = _financial_rows(prior_pages, review["prior_source_page_hashes"],
                               review["prior_period"], cutoff)
    originals = [r for r in review["full_research_list"] if r["review_tier"] == TIER]
    if len(originals) != review["counts"]["both_positive_no_accounting_flags"]:
        raise ValueError("GROWTH_TIER_COUNT_CHANGED")
    counts = {"reviewed_a_tier": len(originals), "latest_deduct_eps_missing": 0,
              "previous_deduct_eps_missing": 0, "st_name_warning": 0,
              "cumulative_gross_margin_lower": 0, "gross_margin_missing": 0,
              "quarter_revenue_nonpositive": 0, "quarter_profit_nonpositive": 0}
    audited = []
    for candidate in sorted(originals, key=lambda r: r["security_id"]):
        sid = candidate["security_id"]
        if sid not in current or sid not in previous:
            raise ValueError("CANDIDATE_RAW_SOURCE_ROW_MISSING")
        now, old = current[sid], previous[sid]
        if any((r.get("UPDATE_DATE") or "")[:10] >= cutoff for r in (now, old)):
            raise ValueError("SELECTED_SOURCE_REVISED_AFTER_CAPTURE_CUTOFF")
        if now.get("ORG_CODE") != old.get("ORG_CODE"):
            raise ValueError("MATERIAL_ISSUER_IDENTITY_MISMATCH")
        if now.get("NOTICE_DATE", "")[:10] != candidate["recent_notice_date"]:
            raise ValueError("CANDIDATE_NOTICE_IDENTITY_CHANGED")
        rev_now = _amount(now, "TOTAL_OPERATE_INCOME")
        rev_old = _amount(old, "TOTAL_OPERATE_INCOME")
        profit_now = _amount(now, "PARENT_NETPROFIT")
        profit_old = _amount(old, "PARENT_NETPROFIT")
        if None in (rev_now, rev_old, profit_now, profit_old):
            raise ValueError("CUMULATIVE_ACCOUNTING_VALUES_MISSING")
        quarter_revenue = rev_now - rev_old
        quarter_profit = profit_now - profit_old
        current_deduct = _amount(now, "DEDUCT_BASIC_EPS")
        prior_deduct = _amount(old, "DEDUCT_BASIC_EPS")
        gross_now = _amount(now, "XSMLL")
        gross_old = _amount(old, "XSMLL")
        flags = []
        if current_deduct is None:
            counts["latest_deduct_eps_missing"] += 1
            flags.append("Q3_DEDUCT_EPS_UNAVAILABLE_CANNOT_VERIFY_CORE_EARNINGS")
        if prior_deduct is None:
            counts["previous_deduct_eps_missing"] += 1
            flags.append("H1_DEDUCT_EPS_UNAVAILABLE")
        if ST_NAME.match(candidate["name"] or ""):
            counts["st_name_warning"] += 1
            flags.append("ST_NAME_REQUIRES_EXCHANGE_STATUS_CONFIRMATION")
        if gross_now is None or gross_old is None:
            counts["gross_margin_missing"] += 1
            flags.append("CUMULATIVE_GROSS_MARGIN_UNAVAILABLE")
        elif gross_now < gross_old:
            counts["cumulative_gross_margin_lower"] += 1
            flags.append("CUMULATIVE_GROSS_MARGIN_LOWER_THAN_H1")
        if quarter_revenue <= 0:
            counts["quarter_revenue_nonpositive"] += 1
            flags.append("STANDALONE_Q3_REVENUE_NONPOSITIVE")
        if quarter_profit <= 0:
            counts["quarter_profit_nonpositive"] += 1
            flags.append("STANDALONE_Q3_PARENT_PROFIT_NONPOSITIVE")
        audited.append({
            "security_id": sid, "name": candidate["name"],
            "latest_report_date": review["latest_period"],
            "prior_report_date": review["prior_period"],
            "quarter_revenue_yuan_cumulative_difference": quarter_revenue,
            "quarter_parent_profit_yuan_cumulative_difference": quarter_profit,
            "latest_cumulative_gross_margin_pct": gross_now,
            "prior_cumulative_gross_margin_pct": gross_old,
            "latest_deduct_basic_eps_yuan": current_deduct,
            "prior_deduct_basic_eps_yuan": prior_deduct,
            "review_flags": flags, "core_earnings_quality_verified": False,
            "official_special_treatment_status_verified": False,
            "buy_eligibility": "NOT_AUTHORIZED"
        })
    return {
        "schema": "AI_CORE_EVID_GROWTH_RAW_SOURCE_QUALITY_AUDIT_V1",
        "review_sha256": hashlib.sha256(json.dumps(
            review, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        ).encode()).hexdigest(),
        "latest_period": review["latest_period"], "prior_period": review["prior_period"],
        "notice_cutoff_exclusive": cutoff,
        "latest_finance_source_hashes": review["latest_source_page_hashes"],
        "prior_finance_source_hashes": review["prior_source_page_hashes"],
        "counts": counts, "quality_rows": audited,
        "standalone_quarter_computed_from_two_cumulative_statements": True,
        "cumulative_delta_not_independently_filing_certified": True,
        "missing_deduct_eps_not_imputed": True,
        "no_alpha_test_or_valuation_estimate": True,
        "strategy_validated": False,
        "live_buy_eligibility": "NOT_AUTHORIZED"
    }


def _pages(folder):
    files = sorted(Path(folder).glob("page-*.json"))
    if not files:
        raise ValueError("CAPTURE_PAGES_NOT_FOUND")
    return [p.read_bytes() for p in files]


def main():
    p = argparse.ArgumentParser(description="Audit raw financial fields of existing A-tier growth research.")
    p.add_argument("--review-json", type=Path, required=True)
    p.add_argument("--raw-dir", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    if a.output.exists():
        p.error("Do not overwrite a prior research audit")
    review = json.loads(a.review_json.read_text(encoding="utf-8"))
    result = audit(review, _pages(a.raw_dir/"latest"), _pages(a.raw_dir/"prior"))
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(json.dumps({"counts": result["counts"],
                      "examples": result["quality_rows"][:12],
                      "live_buy_eligibility": "NOT_AUTHORIZED"},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
