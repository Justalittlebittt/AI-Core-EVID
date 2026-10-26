#!/usr/bin/env python3
"""Read frozen V2.8.1 research receipts before any candidate admission.

Only retrospective evidence is read. No prospective records, prices, or future data.
This is a research-admission boundary, NOT an automatic stock selector.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FINAL = ROOT / "evidence/V2.8.1_FINAL_RECORD.json"
RECEIPT = ROOT / "evidence/V2.8.1_STAGE1_FACTOR_SCREEN_RECEIPT.json"


def sealed_sha(doc):
    payload = {key: value for key, value in doc.items() if key != "receipt_sha256"}
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def assess_factor_admission(final_path=FINAL, receipt_path=RECEIPT):
    final = json.loads(Path(final_path).read_text(encoding="utf-8"))
    receipt = json.loads(Path(receipt_path).read_text(encoding="utf-8"))
    if final.get("schema") != "AI_CORE_EVID_V2_8_1_FINAL_RECORD_V1":
        raise ValueError("INVALID_FINAL_RECORD_SCHEMA")
    if receipt.get("schema") != "AI_CORE_EVID_V2_8_1_STAGE1_FACTOR_SCREEN_RECEIPT_V1":
        raise ValueError("INVALID_SCREEN_RECEIPT_SCHEMA")
    if sealed_sha(receipt) != receipt.get("receipt_sha256"):
        raise ValueError("SCREEN_RECEIPT_SEAL_MISMATCH")
    stage = final["stage1"]
    if stage["screen_receipt_sha256"] != receipt["receipt_sha256"]:
        raise ValueError("RESEARCH_RECEIPT_IDENTITY_MISMATCH")
    if stage["result_ledger_sha256"] != receipt["result_ledger_sha256"]:
        raise ValueError("RESULT_LEDGER_IDENTITY_MISMATCH")
    if final["canonical_snapshot"]["panel_sha256"] != receipt["panel_sha256"]:
        raise ValueError("PANEL_IDENTITY_MISMATCH")
    promoted = receipt["promoted_factors"]
    if stage["promoted_count"] != len(promoted) or receipt["promoted_count"] != len(promoted):
        raise ValueError("PROMOTION_COUNT_MISMATCH")
    if stage["promoted_factors"] != promoted:
        raise ValueError("PROMOTED_FACTOR_SET_MISMATCH")
    if receipt["factor_family_size"] != len(promoted) + len(receipt["not_promoted_factors"]):
        raise ValueError("FACTOR_FAMILY_COUNT_MISMATCH")
    if receipt["gate"]["status"] != "STAGE1_SCREEN_COMPLETE":
        raise ValueError("SCREEN_NOT_COMPLETE")
    if receipt["gate"]["thresholds_modified_after_results"] is not False:
        raise ValueError("RESEARCH_RULE_INTEGRITY_UNVERIFIED")

    # Even successful factor promotion would not alone authorize live trading.
    no_live = final["governance"].get("live_authorized") is False
    if not no_live:
        raise ValueError("UNEXPECTED_LIVE_AUTHORITY_STATE")
    return {
        "source": "V2.8.1_FROZEN_HISTORICAL_RESEARCH_ONLY",
        "screen_run_id": receipt.get("run_id"),
        "snapshot_sha256": receipt["panel_sha256"],
        "screen_receipt_sha256": receipt["receipt_sha256"],
        "factors_tested": receipt["factor_family_size"],
        "factors_promoted": len(promoted),
        "research_candidate_admission": "BLOCKED_NO_PROMOTED_FACTOR" if not promoted else "PROMOTED_FACTORS_RESEARCH_ONLY",
        "live_buy_eligibility": "NOT_AUTHORIZED",
        "reason": "No factor passed the frozen historical gates" if not promoted else "Research promotion is not authorization for live trading",
    }


def main():
    print(json.dumps(assess_factor_admission(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
