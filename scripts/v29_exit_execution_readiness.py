"""Separate an existing EXIT_REQUIRED decision from actual sell-order readiness.

No trade execution. Broker-reported sellable quantity is an explicit input:
T+1 eligibility cannot be inferred from total position, purchase price or dates.
"""
from __future__ import annotations
import json
import argparse
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
from v29_position_watchlist import timestamp

FIELDS = {"security_id", "as_of", "sellable_quantity", "trading_status"}
STATUSES = {"TRADING", "SUSPENDED", "UNKNOWN"}


def apply_execution_constraints(watchlist, contexts, reviewed_at):
    if watchlist.get("schema") != "AI_CORE_EVID_WATCHLIST_REVIEW_V1":
        raise ValueError("NOT_A_VALIDATED_WATCHLIST_REPORT")
    if watchlist.get("evaluated_at") != reviewed_at:
        raise ValueError("WATCHLIST_EVALUATION_TIMESTAMP_MISMATCH")
    if not isinstance(contexts, list):
        raise ValueError("EXECUTION_CONTEXT_MUST_BE_LIST")
    by_security = {}
    for item in contexts:
        if not isinstance(item, dict) or set(item) != FIELDS:
            raise ValueError("EXECUTION_CONTEXT_SCHEMA_INVALID")
        sid = item["security_id"]
        if not isinstance(sid, str) or not sid or sid in by_security:
            raise ValueError("DUPLICATE_OR_INVALID_EXECUTION_SECURITY")
        q = item["sellable_quantity"]
        if type(q) is not int or q < 0 or item["trading_status"] not in STATUSES:
            raise ValueError("INVALID_EXECUTION_STATUS")
        quote_at = timestamp(item["as_of"])
        if quote_at > timestamp(reviewed_at):
            raise ValueError("FUTURE_EXECUTION_STATUS")
        by_security[sid] = item
    positions = watchlist.get("positions")
    if not isinstance(positions, list) or not positions:
        raise ValueError("EMPTY_WATCHLIST")
    sids = [p["security_id"] for p in positions]
    if len(set(sids)) != len(sids) or set(by_security) - set(sids):
        raise ValueError("EXECUTION_SECURITY_IDENTITY_MISMATCH")
    tz = ZoneInfo("Asia/Shanghai")
    day = timestamp(reviewed_at).astimezone(tz).date()
    reviewed = []
    for p in positions:
        item = by_security.get(p["security_id"])
        can_submit = None
        sellable = None
        if item is None:
            reason = "BROKER_SELLABLE_QUANTITY_MISSING"
        elif timestamp(item["as_of"]).astimezone(tz).date() != day:
            reason = "BROKER_STATUS_PREVIOUS_DAY"
        else:
            sellable = item["sellable_quantity"]
            if sellable > p["quantity"]:
                raise ValueError("SELLABLE_EXCEEDS_POSITION")
            if item["trading_status"] == "SUSPENDED":
                reason, can_submit = "SUSPENDED", False
            elif item["trading_status"] == "UNKNOWN":
                reason = "TRADING_STATUS_UNKNOWN"
            elif sellable == 0:
                reason, can_submit = "NO_TPLUS1_SELLABLE_SHARES", False
            elif sellable < p["quantity"]:
                reason, can_submit = "ONLY_PARTIAL_POSITION_SELLABLE", False
            else:
                reason, can_submit = "FULL_SELL_ORDER_POSSIBLE_NOT_CONFIRMED", True
        decision = p.get("discipline_decision") or {}
        exit_required = decision.get("decision") == "EXIT_REQUIRED"
        reviewed.append({
            "security_id": p["security_id"],
            "exit_required": exit_required,
            "exit_reason": decision.get("reasons", []) if exit_required else [],
            "sellable_quantity": sellable,
            "can_submit_full_sell_order": can_submit,
            "execution_reason": reason,
            "urgent_unexecuted_exit": exit_required,
            "execution_confirmed": False,
        })
    return {
        "schema": "AI_CORE_EVID_EXIT_EXECUTION_READINESS_V1",
        "reviewed_at": reviewed_at,
        "positions": reviewed,
        "required_exit_count": sum(x["exit_required"] for x in reviewed),
        "required_exit_with_unconfirmed_full_execution_count": sum(x["exit_required"] and x["can_submit_full_sell_order"] is not True for x in reviewed),
        "cannot_infer_tradability_from_quote": True,
        "not_a_trade_instruction_or_execution_receipt": True,
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--watchlist", type=Path, required=True)
    p.add_argument("--execution-context", type=Path, required=True)
    a = p.parse_args()
    w = json.loads(a.watchlist.read_text(encoding="utf-8"))
    c = json.loads(a.execution_context.read_text(encoding="utf-8"))
    print(json.dumps(apply_execution_constraints(w, c, w["evaluated_at"]), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
