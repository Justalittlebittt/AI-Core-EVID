#!/usr/bin/env python3
"""Connect REAL historical descriptive rankings to the existing fail-closed decision engine.

Historical input is an unvalidated factor observation, never a trading signal.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path

from v29_decision_case_demo import build_case
from v29_decision_packet_adapter import adapt_and_evaluate

SCHEMA = "AI_CORE_EVID_HISTORICAL_DESCRIPTIVE_RANK_V1"


def digest(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def build_historical_case(report, security_id):
    if report.get("schema") != SCHEMA:
        raise ValueError("UNSUPPORTED_HISTORICAL_RANK_SCHEMA")
    if report.get("decision_case_admission") != "BLOCKED_UNVALIDATED_FACTOR":
        raise ValueError("UNEXPECTED_RANK_ADMISSION_STATE")
    if report.get("live_buy_eligibility") != "NOT_AUTHORIZED":
        raise ValueError("UNEXPECTED_LIVE_ELIGIBILITY")
    source = report.get("real_historical_source")
    if not isinstance(source, dict) or source.get("candidate_strategy_validated") is not False:
        raise ValueError("NO_VERIFIED_UNVALIDATED_HISTORICAL_SOURCE")
    if source.get("frozen_research_asof_eligibility_verified") is not True:
        raise ValueError("HISTORICAL_SOURCE_IDENTITY_UNVERIFIED")
    ranking = report.get("ranking")
    if not isinstance(ranking, list) or not ranking:
        raise ValueError("EMPTY_RANKING")
    matches = [r for r in ranking if r.get("canonical_security_id") == security_id]
    if len(matches) != 1:
        raise ValueError("SECURITY_NOT_UNIQUE_IN_RANK")
    ranked = matches[0]
    if ranked.get("signal_date") != report.get("as_of"):
        raise ValueError("SIGNAL_DATE_MISMATCH")
    if not isinstance(ranked.get("ret_20"), (int, float)):
        raise ValueError("INVALID_DESCRIPTIVE_FACTOR")

    packet = copy.deepcopy(build_case()["packet"])
    packet["research_context"].update({
        "strategy_id": "HISTORICAL_UNPROMOTED_RET20",
        "experiment_version": "DESCRIPTIVE_ONLY_V1",
        "evaluation_timestamp": report["as_of"] + "T15:00:00+08:00",
        "evidence_artifact_sha256": digest(report),
    })
    packet["validity"].update({
        "evidence_strength": "INSUFFICIENT",
        "validity_result_sha256": digest({
            "historical_research_result": report.get("historical_research_result"),
            "strategy_validated": False,
        }),
        "pre_registration_sha256": digest({
            "research": "V2.8.1_NON_PROMOTED_RET20",
            "not_a_new_preregistration": True,
        }),
        "all_required_dimensions_reported": False,
    })
    # Risk values are synthetic placeholders from the integration fixture.
    # They MUST NOT be interpreted as real position or execution advice.
    evaluation = adapt_and_evaluate(packet)
    if evaluation["discipline_decision"]["decision"] != "NO_ACTION_INSUFFICIENT_EVIDENCE":
        raise ValueError("HISTORICAL_FACTOR_MUST_NOT_AUTHORIZE_BUY")
    return {
        "case_type": "REAL_HISTORICAL_INPUT_UNVALIDATED_RESEARCH_NOT_TRADING_ADVICE",
        "security": security_id,
        "as_of": report["as_of"],
        "descriptive_factor": {"name": "ret_20", "value": ranked["ret_20"], "rank": ranked["descriptive_rank"]},
        "source_report_sha256": digest(report),
        "research_status": "FACTOR_NOT_PROMOTED",
        "risk_input_status": "SYNTHETIC_DEMO_ONLY",
        "decision": evaluation,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ranking-json", required=True, type=Path)
    parser.add_argument("--security", required=True)
    args = parser.parse_args()
    report = json.loads(args.ranking_json.read_text(encoding="utf-8"))
    print(json.dumps(build_historical_case(report, args.security), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
