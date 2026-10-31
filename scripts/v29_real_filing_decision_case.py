#!/usr/bin/env python3
"""Real, dated issuer filings -> existing fail-closed decision engine.

No price outcomes are an input. A later retrospective outcome may be compared
separately, but must never revise a decision packet at the disclosure as-of.
This is an integration case, not a validated BUY model or live risk advice.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from datetime import date
from pathlib import Path

from v29_decision_case_demo import build_case
from v29_decision_packet_adapter import adapt_and_evaluate

ROOT = Path(__file__).resolve().parents[1]
FILINGS = ROOT / "research/V2.9_2025_TWO_ISSUER_FILING_INPUTS.json"


def digest(obj):
    return hashlib.sha256(json.dumps(obj, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def build_as_disclosed_cases(filings, exchange_sessions, filing_sha256):
    """Only issuer annual inputs + supplied calendar; no later prices or outcomes."""
    if (filings.get("schema") != "AI_CORE_EVID_V29_HISTORICAL_2025_TWO_ISSUER_CASE_INPUT_V1"
            or len(filings.get("issuers", [])) != 2
            or {r["canonical_id"] for r in filings["issuers"]}
               != {"SZSE:300408", "SSE:688002"}):
        raise ValueError("WRONG_FILING_COHORT_OR_SCHEMA")
    if len(filing_sha256) != 64 or any(c not in "0123456789abcdef" for c in filing_sha256):
        raise ValueError("INVALID_FILING_SOURCE_HASH")
    sessions = [date.fromisoformat(s) for s in exchange_sessions]
    if len(sessions) != len(set(sessions)) or sessions != sorted(sessions):
        raise ValueError("INVALID_OR_DUPLICATE_TRADING_CALENDAR")
    result = []
    for issuer in filings["issuers"]:
        published = date.fromisoformat(issuer["published_on"])
        fiscal_end = date.fromisoformat(issuer["financial_report_end"])
        if published <= fiscal_end:
            raise ValueError("DISCLOSURE_BEFORE_PERIOD_END")
        next_sessions = [s for s in sessions if s > published]
        if not next_sessions:
            raise ValueError("NO_VERIFIED_POST_DISCLOSURE_SESSION")
        decision_day = next_sessions[0].isoformat()
        # Exactly the prior-year comparatives in the *same original report*.
        features = {
            "fiscal_end": fiscal_end.isoformat(),
            "publication_date": published.isoformat(),
            "revenue_yoy": (issuer["revenue_2024_yuan"]
                            / issuer["revenue_2023_yuan"] - 1),
            "deducted_profit_yoy": (issuer["deduct_parent_2024_yuan"]
                                    / issuer["deduct_parent_2023_yuan"] - 1),
            "cfo_to_deducted_profit": (issuer["cfo_2024_yuan"]
                                       / issuer["deduct_parent_2024_yuan"]),
        }
        # The existing packet fixture supplies *illustrative* risk fields only.
        # Do not promote those fields into a real or user-authorized position.
        packet = copy.deepcopy(build_case()["packet"])
        packet["research_context"].update({
            "strategy_id": "FY2024_DISCLOSURE_GROWTH_DESCRIPTIVE_ONLY",
            "experiment_version": "V29_REAL_FILING_BOUNDARY_V1",
            "evaluation_timestamp": decision_day + "T15:00:00+08:00",
            "evidence_artifact_sha256": digest({
                "source_filing_sha256": filing_sha256,
                "security_id": issuer["canonical_id"],
                "financials_available_by_asof": features,
            }),
        })
        packet["validity"].update({
            "evidence_strength": "INSUFFICIENT",
            "all_required_dimensions_reported": False,
            "validity_result_sha256": digest({
                "strategy_validated": False, "oos_validation": "MISSING",
                "economic_return_validation": "MISSING",
                "original_pdf_bytes_sealed": False,
            }),
            "pre_registration_sha256": digest({
                "historical_case": "RETROSPECTIVE_DEVELOPMENT_ONLY",
                "unseen_preregistration": False,
            }),
        })
        evaluation = adapt_and_evaluate(packet)
        if evaluation["discipline_decision"]["decision"] != "NO_ACTION_INSUFFICIENT_EVIDENCE":
            raise ValueError("UNVALIDATED_FILING_MUST_NOT_AUTHORIZE_BUY")
        result.append({
            "canonical_security_id": issuer["canonical_id"],
            "issuer": issuer["name"],
            "as_of": decision_day,
            "original_publication_date": published.isoformat(),
            "original_report_url": issuer["official_pdf"],
            "original_pdf_bytes_sealed": False,
            "market_quote_asof_certified": False,
            "source_filing_input_sha256": filing_sha256,
            "financial_features_as_disclosed": features,
            "packet": packet,
            "evaluation": evaluation,
            "risk_fields": "SYNTHETIC_INTEGRATION_FIXTURE_NOT_USER_INPUT",
            "future_price_outcome_in_packet": False,
            "trade_authorized": False,
        })
    return {
        "schema": "V29_REAL_FILING_ASOF_DECISION_CASES_V1",
        "decision_cases": result,
        "calendar_supplied_not_independently_certified": True,
        "source_selection": "RETROSPECTIVE_TWO_KNOWN_ISSUERS_NOT_OOS",
        "strategy_validated": False,
        "live_buy_eligibility": "NOT_AUTHORIZED",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--exchange-sessions", type=Path, required=True,
                        help="JSON array of trading session YYYY-MM-DD, from independently sourced calendar")
    parser.add_argument("--filings", type=Path, default=FILINGS)
    args = parser.parse_args()
    from v29_2025_filing_to_return_case import load_inputs
    filings, sha = load_inputs(args.filings)
    sessions = json.loads(args.exchange_sessions.read_text(encoding="utf-8"))
    print(json.dumps(build_as_disclosed_cases(filings, sessions, sha), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
