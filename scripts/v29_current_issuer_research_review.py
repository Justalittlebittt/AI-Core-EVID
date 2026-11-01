#!/usr/bin/env python3
"""Read-only, source-bound *research reviews* of two real 2026 Q3 A shares.

These are NOT V2.9 Decision Packets: neither strategy alpha nor a user trade
plan is established. Never fill risk fields using synthetic demo values.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "research/V2.9_ISSUER_VALUATION_SENSITIVITY_20261030.json"
SCHEMA = "V29_REAL_ISSUER_RESEARCH_REVIEW_V1"
ISSUER_IDS = {"SZSE:300408", "SSE:688002"}


def build_reviews(original_bytes: bytes) -> dict:
    source = json.loads(original_bytes)
    if (source.get("schema") != "V2.9_ISSUER_EPS_PE_SENSITIVITY_V1"
            or source.get("buy_eligibility") != "NOT_AUTHORIZED"
            or source.get("independent_alpha_evidence") is not False
            or source.get("company_pit_certification") is not False
            or source.get("price_target_certification") is not False):
        raise ValueError("SOURCE_RESEARCH_ONLY_INVARIANTS_CHANGED")

    study_day = date.fromisoformat(source["as_of"])
    reference_day = date.fromisoformat(source["reference_price_session"])
    if reference_day >= study_day:
        raise ValueError("RESEARCH_QUOTE_MUST_PRECEDE_STUDY_DAY")

    cases = source["cases"]
    if (len(cases) != len(ISSUER_IDS)
            or {item["security_id"] for item in cases} != ISSUER_IDS):
        raise ValueError("UNEXPECTED_OR_DUPLICATED_ISSUER_CASES")

    reports = []
    for case in cases:
        quote_time = datetime.strptime(case["quote_asof_beijing"], "%Y-%m-%d %H:%M")
        if quote_time.date() != reference_day:
            raise ValueError("QUOTE_DATE_SOURCE_MISMATCH")
        price, pe = case["reference_price_cny"], case["vendor_pe_ttm"]
        if not (isinstance(price, (int, float)) and isinstance(pe, (int, float))
                and not isinstance(price, bool) and not isinstance(pe, bool)
                and math.isfinite(price) and math.isfinite(pe) and price > 0 and pe > 0):
            raise ValueError("NONPOSITIVE_OR_INVALID_QUOTE_OR_PE")
        sources = case["sources"]
        if (not isinstance(sources.get("report"), str)
                or not sources["report"].startswith("https://")
                or not isinstance(sources.get("quote"), str)
                or not sources["quote"].startswith("https://")):
            raise ValueError("MISSING_PUBLIC_RESEARCH_SOURCE")
        reports.append({
            "security_id": case["security_id"],
            "issuer": case["name"],
            "research_as_of": study_day.isoformat(),
            "quote_session": reference_day.isoformat(),
            "quote_observation_beijing": case["quote_asof_beijing"],
            "observed_reference_price_cny": price,
            "vendor_labeled_pe_ttm": pe,
            "ytd_gross_margin_2025_pct": case["ytd_gross_margin_2025_pct"],
            "ytd_gross_margin_2026_pct": case["ytd_gross_margin_2026_pct"],
            "source_urls": sources,
            "candidate_status": "REAL_ISSUER_RESEARCH_ONLY",
            "contemplated_action": None,
            "decision_packet": None,
            "discipline_decision": "NOT_EVALUATED_NO_REAL_TRADE_PLAN_OR_VALIDATED_STRATEGY",
            "human_stop_take_profit_position_size": None,
            "financial_vintage_verified_as_original_release": False,
            "quote_vendor_pe_denominator_independently_verified": False,
            "current_quote_or_executable_fill_verified": False,
            "strategy_alpha_and_untouched_oos_verified": False,
            "buy_add_authorized": False,
            "next_allowed_step": "RESEARCH_OR_COLLECT_FRESH_EVIDENCE_NOT_PLACE_ORDER",
        })

    return {
        "schema": SCHEMA,
        "research_as_of": study_day.isoformat(),
        "financial_research_source_path": str(SOURCE.relative_to(ROOT)),
        "financial_research_source_sha256": hashlib.sha256(original_bytes).hexdigest(),
        "selection_basis": "TWO_PURPOSIVELY_STUDIED_ISSUERS_NOT_OUT_OF_SAMPLE",
        "cases": reports,
        "trade_authorized": False,
        "live_buy_eligibility": "NOT_AUTHORIZED",
        "synthetic_risk_fields_used": False,
        "no_trade_decision_claimed_from_discipline_engine": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--out", type=Path, help="Optional local research review JSON, never a trade")
    args = parser.parse_args()
    report = build_reviews(args.source.read_bytes())
    encoded = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        if args.out.exists():
            raise ValueError("REFUSE_OVERWRITE_RESEARCH_REVIEW")
        args.out.write_text(encoded, encoding="utf-8")
    else:
        print(encoded, end="")


if __name__ == "__main__":
    main()
