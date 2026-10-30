#!/usr/bin/env python3
"""Compare two captured public A-share financial periods for research review, never BUY.

A same-year H1/Q3 pair has overlapping year-to-date numbers: persistence is
descriptive, NOT independent alpha/OOS evidence. Only matched positive observations
can be marked confirmed in BOTH captured snapshots.
"""
from __future__ import annotations

import argparse
import json
import math
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from v29_growth_candidate_snapshot import collect

SCHEMA = "AI_CORE_EVID_GROWTH_CANDIDATE_SNAPSHOT_V1"
SOURCE = "UNOFFICIAL_EASTMONEY_FINANCIAL_AGGREGATE"


def _validated_snapshot(snapshot):
    if not isinstance(snapshot, dict) or snapshot.get("schema") != SCHEMA:
        raise ValueError("INVALID_FINANCIAL_SNAPSHOT_SCHEMA")
    if snapshot.get("source") != SOURCE or snapshot.get("strategy_validated") is not False:
        raise ValueError("UNVERIFIED_FINANCIAL_SNAPSHOT_PROVENANCE")
    if snapshot.get("live_buy_eligibility") != "NOT_AUTHORIZED":
        raise ValueError("UNEXPECTED_TRADING_AUTHORITY")
    period = date.fromisoformat(snapshot["report_date"])
    captured = datetime.fromisoformat(snapshot["captured_at"])
    if captured.tzinfo is None or captured.utcoffset() is None:
        raise ValueError("INVALID_CAPTURE_TIMESTAMP")
    if not snapshot.get("raw_page_hashes") or not isinstance(snapshot.get("candidates"), list):
        raise ValueError("INCOMPLETE_SOURCE_PROVENANCE")
    candidates = {}
    for row in snapshot["candidates"]:
        sid = row["security_id"]
        if sid in candidates or row["report_date"] != period.isoformat():
            raise ValueError("DUPLICATE_OR_MISMATCHED_CANDIDATE")
        disclosure = date.fromisoformat(row["notice_date"])
        if disclosure > captured.astimezone(ZoneInfo("Asia/Shanghai")).date():
            raise ValueError("FUTURE_DISCLOSURE_DATE")
        if row["buy_eligibility"] != "NOT_AUTHORIZED" or row["status"] != "RESEARCH_CANDIDATE_ONLY":
            raise ValueError("UNAUTHORIZED_CANDIDATE")
        candidates[sid] = row
    if snapshot["candidate_count"] != len(candidates):
        raise ValueError("CANDIDATE_COUNT_MISMATCH")
    return period, candidates


def compare(latest, prior, queue_limit=20):
    """Pure comparison. No financial source download, empirical tuning or backtest."""
    if type(queue_limit) is not int or not 1 <= queue_limit <= 100:
        raise ValueError("INVALID_REVIEW_QUEUE_LIMIT")
    recent_date, recent = _validated_snapshot(latest)
    prior_date, earlier = _validated_snapshot(prior)
    if prior_date >= recent_date:
        raise ValueError("PRIOR_PERIOD_NOT_EARLIER")
    rows = []
    counts = {"both_positive": 0, "both_positive_no_accounting_flags": 0,
              "both_positive_with_review_flags": 0, "prior_positive_not_observed": 0}
    for sid, row in sorted(recent.items()):
        old = earlier.get(sid)
        flags = list(row["review_flags"])
        persistent = old is not None
        if persistent:
            counts["both_positive"] += 1
            if old["review_flags"]:
                flags.extend("PRIOR_" + flag for flag in old["review_flags"])
            if row["name"] != old["name"]:
                flags.append("SECURITY_NAME_CHANGED_VERIFY_IDENTITY")
            # Cumulative report-period profit margins are comparable indicators,
            # but NOT stand-alone quarterly margin, timing or alpha.
            recent_margin = row["parent_profit_yuan"] / row["revenue_yuan"]
            prior_margin = old["parent_profit_yuan"] / old["revenue_yuan"]
            if not (math.isfinite(recent_margin) and math.isfinite(prior_margin)):
                raise ValueError("INVALID_NET_MARGIN")
            if recent_margin < prior_margin:
                flags.append("CUMULATIVE_PARENT_NET_MARGIN_LOWER")
            if flags:
                counts["both_positive_with_review_flags"] += 1
            else:
                counts["both_positive_no_accounting_flags"] += 1
        else:
            counts["prior_positive_not_observed"] += 1
            flags.append("PRIOR_POSITIVE_UNOBSERVED_NOT_PROOF_OF_DECLINE")
        rows.append({
            "security_id": sid, "name": row["name"],
            "recent_report_date": latest["report_date"],
            "recent_notice_date": row["notice_date"],
            "prior_report_date": prior["report_date"],
            "prior_notice_date": old["notice_date"] if old else None,
            "revenue_yoy_pct_latest": row["revenue_yoy_pct"],
            "profit_yoy_pct_latest": row["parent_profit_yoy_pct"],
            "revenue_yoy_pct_prior": old["revenue_yoy_pct"] if old else None,
            "profit_yoy_pct_prior": old["parent_profit_yoy_pct"] if old else None,
            "latest_cfo_per_share": row["operating_cash_flow_per_share_yuan"],
            "latest_roe_pct": row["roe_pct"],
            "persistent_positive_observation": persistent,
            "review_flags": sorted(set(flags)),
            "review_tier": ("A_BOTH_POSITIVE_NO_ACCOUNTING_FLAGS" if persistent and not flags
                            else "B_BOTH_POSITIVE_WITH_FLAGS" if persistent
                            else "C_PRIOR_POSITIVE_NOT_OBSERVED"),
            "buy_eligibility": "NOT_AUTHORIZED",
        })
    rows.sort(key=lambda r: (r["review_tier"], r["security_id"]))
    return {
        "schema": "AI_CORE_EVID_GROWTH_RESEARCH_REVIEW_V1",
        "latest_period": latest["report_date"],
        "prior_period": prior["report_date"],
        "latest_capture": latest["captured_at"],
        "prior_capture": prior["captured_at"],
        "latest_source_page_hashes": latest["raw_page_hashes"],
        "prior_source_page_hashes": prior["raw_page_hashes"],
        "counts": counts,
        "review_queue_order": "TIER_THEN_CANONICAL_SECURITY_ID_NOT_ALPHA_RANK",
        "queue_limit": queue_limit, "review_queue": rows[:queue_limit],
        "full_research_list": rows,
        "overlapping_cumulative_periods_are_not_independent_validation": True,
        "historical_asof_source_authenticity_independently_verified": False,
        "valuation_checked": False,
        "strategy_validated": False,
        "live_buy_eligibility": "NOT_AUTHORIZED",
    }


def main():
    p = argparse.ArgumentParser(description="Two fiscal periods of growth research; not buy advice.")
    p.add_argument("--latest-period", required=True)
    p.add_argument("--prior-period", required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--raw-dir", type=Path, required=True)
    p.add_argument("--queue-limit", type=int, default=20)
    a = p.parse_args()
    if a.output.exists() or a.raw_dir.exists():
        p.error("Do not overwrite a previous financial capture")
    # Capture both *today*: later provider revisions must not be called historical PIT.
    latest, raw_latest = collect(a.latest_period)
    prior, raw_prior = collect(a.prior_period)
    report = compare(latest, prior, a.queue_limit)
    for sub, raw, snapshot in (
        ("latest", raw_latest, latest), ("prior", raw_prior, prior)
    ):
        folder = a.raw_dir / sub
        folder.mkdir(parents=True, exist_ok=False)
        for i, blob in enumerate(raw, 1):
            (folder / f"page-{i:03d}.json").write_bytes(blob)
        (folder / "snapshot.json").write_text(
            json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "latest_period": report["latest_period"],
        "prior_period": report["prior_period"],
        "counts": report["counts"],
        "review_queue": report["review_queue"],
        "live_buy_eligibility": "NOT_AUTHORIZED",
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
