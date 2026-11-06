#!/usr/bin/env python3
"""Read-only eight-name shared-account capacity; no BUY or broker access."""
import argparse
import json
from decimal import Decimal, InvalidOperation
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FROZEN = ROOT / "research/V2.9_EIGHT_NAME_LOT_AWARE_PROSPECTIVE_PILOT_PREOUTCOME_20261102.json"
FROZEN_IDS = ("SZSE:300199", "SZSE:002636", "SZSE:301536", "SZSE:000408",
              "SZSE:002463", "SSE:603256", "SZSE:002552", "SZSE:300223")

def number(v, field, zero=False):
    if isinstance(v, bool) or not isinstance(v, (str, int, float, Decimal)):
        raise ValueError("INVALID_" + field)
    try:
        n = Decimal(str(v))
    except InvalidOperation as exc:
        raise ValueError("INVALID_" + field) from exc
    if not n.is_finite() or (n < 0 if zero else n <= 0):
        raise ValueError("INVALID_" + field)
    return n

def assess(ids, account, positions):
    """Evaluate caller-specified quantities; no implicit optimizer or prices."""
    if tuple(ids) != FROZEN_IDS:
        raise ValueError("FROZEN_EIGHT_IDENTITY_OR_ORDER_CHANGED")
    if not isinstance(account, dict) or not isinstance(positions, list):
        raise ValueError("INVALID_INPUT")
    equity = number(account["equity_cny"], "EQUITY")
    cash = number(account["cash_cny"], "CASH", True)
    fees = number(account["fee_reserve_cny"], "FEE_RESERVE", True)
    max_name = number(account["max_name_fraction"], "NAME_FRACTION")
    max_name_loss = number(account["max_name_loss_fraction"], "NAME_LOSS_FRACTION")
    max_total_loss = number(account["max_portfolio_loss_fraction"], "PORTFOLIO_LOSS_FRACTION")
    if cash > equity or fees > cash or max(max_name, max_name_loss, max_total_loss) > 1:
        raise ValueError("INVALID_ACCOUNT_LIMITS")
    permissions = account["permissions"]
    if not isinstance(permissions, dict) or any(type(permissions.get(b)) is not bool for b in ("main", "chinext", "star")):
        raise ValueError("EXPLICIT_BOARD_PERMISSIONS_REQUIRED")
    if len(positions) != 8 or {p.get("security_id") for p in positions} != set(ids):
        raise ValueError("POSITIONS_MUST_MATCH_FROZEN_EIGHT")
    positions_by_id = {p["security_id"]: p for p in positions}
    gross = Decimal(0)
    loss = Decimal(0)
    rows = []
    for sid in ids:
        p = positions_by_id[sid]
        if sid.startswith("SSE:688"):
            board, minimum, step = "star", 200, 1
        elif sid.startswith(("SZSE:300", "SZSE:301")):
            board, minimum, step = "chinext", 100, 100
        else:
            board, minimum, step = "main", 100, 100
        qty = p["shares"]
        if type(qty) is not int or qty < minimum or (qty-minimum) % step:
            raise ValueError("INVALID_EXCHANGE_LOT:" + sid)
        px = number(p["reference_price_cny"], "PRICE")
        stop = number(p["stop_price_cny"], "STOP")
        if stop >= px:
            raise ValueError("STOP_NOT_BELOW_PRICE:" + sid)
        notional, risk = px*qty, (px-stop)*qty
        gross += notional
        loss += risk
        issues = []
        if not permissions[board]:
            issues.append("BOARD_PERMISSION_NOT_GRANTED")
        if notional > equity*max_name:
            issues.append("SINGLE_NAME_POSITION_LIMIT")
        if risk > equity*max_name_loss:
            issues.append("SINGLE_NAME_STOP_RISK_LIMIT")
        rows.append({"security_id":sid,"board":board,"shares":qty,
                     "reference_notional_cny":str(notional),
                     "stop_distance_loss_cny":str(risk),"issues":issues})
    issues = []
    if gross + fees > cash:
        issues.append("SHARED_CASH_EXCEEDED")
    if loss > equity*max_total_loss:
        issues.append("PORTFOLIO_STOP_RISK_EXCEEDED")
    return {"schema":"V29_FROZEN_EIGHT_SHARED_ACCOUNT_PAPER_FEASIBILITY_V1",
            "research_only":True, "reference_quotes_not_verified_fills":True,
            "stop_gap_risk_not_bounded":True,"slippage_and_round_trip_cost_not_estimated":True,
            "gross_reference_notional_cny":str(gross),
            "gross_stop_distance_loss_cny":str(loss),
            "cash_after_reference_and_fee_reserve_cny":str(cash-gross-fees),
            "basket_issues":issues,"positions":rows,
            "paper_capacity_feasible":not issues and all(not r["issues"] for r in rows),
            "trade_authorized":False,"live_buy_eligibility":"NOT_AUTHORIZED"}

def sealed_readiness(root=ROOT):
    """Actual frozen Nov 2 entry reference, not a trade simulation or new BUY."""
    import hashlib
    from v29_eight_pilot_outcome import minimum_lot_reference
    pilot_file=root/"research/V2.9_EIGHT_NAME_LOT_AWARE_PROSPECTIVE_PILOT_PREOUTCOME_20261102.json"
    raw=pilot_file.read_bytes()
    sha=hashlib.sha1(b"blob "+str(len(raw)).encode()+b"\0"+raw).hexdigest()
    if sha!="f33e9c5f68c2202c994fece278322413e18059b1":
        raise ValueError("FROZEN_PILOT_SOURCE_CHANGED")
    pilot=json.loads(raw)
    ids=pilot["pre_outcome_rule"]["selected_ids_in_rank_order"]
    if (tuple(ids)!=FROZEN_IDS or pilot["live_buy_eligibility"]!="NOT_AUTHORIZED"):
        raise ValueError("FROZEN_EIGHT_SOURCE_IDENTITY_CHANGED")
    reference=minimum_lot_reference(root,ids)
    rows=[]
    for r in reference["weights"]:
        sid=r["security_id"]
        board="chinext" if sid.startswith(("SZSE:300","SZSE:301")) else "main"
        rows.append({"security_id":sid,"board":board,"minimum_lot_shares":r["shares"],
                     "sealed_2026_11_02_entry_close_cny":round(r["reference_notional_cny"]/r["shares"],2),
                     "minimum_lot_reference_notional_cny":r["reference_notional_cny"],
                     "minimum_lot_cash_weight_fraction":r["capital_weight"],
                     "required_account_board_permission":board,
                     "risk_approval":"UNASSESSED_PERSONAL_ACCOUNT_UNKNOWN"})
    minimum=reference["min_lot_reference_notional_cny"]
    return {"schema":"V29_EIGHT_FROZEN_REAL_ENTRY_DECISION_READINESS_V1",
            "source_entry_sha256":reference["sealed_entry_snapshot_sha256"],
            "reference_session":"2026-11-02",
            "names_in_original_registered_order":rows,
            "names":len(rows),"chinext_permission_needed_count":sum(x["board"]=="chinext" for x in rows),
            "minimum_lot_gross_reference_cost_cny":minimum,
            "largest_single_name_reference_notional_cny":max(x["minimum_lot_reference_notional_cny"] for x in rows),
            "illustrative_equity_required_for_10pct_single_name_cap_cny":10*max(x["minimum_lot_reference_notional_cny"] for x in rows),
            "ten_percent_cap_is_example_not_user_instruction":True,
            "real_account_cash_stops_permissions_unverified":True,
            "outcome_unobserved_before_registered_maturity":True,
            "financial_signal_independently_validated":False,
            "action_decision":"NO_ACTION_INSUFFICIENT_PREDICTIVE_EVIDENCE",
            "do_not_infer_trading_price_or_broker_fill":True,
            "trade_authorized":False,
            "live_buy_eligibility":"NOT_AUTHORIZED"}

def main():
    ap = argparse.ArgumentParser()
    mode=ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--private-input", type=Path)
    mode.add_argument("--sealed-readiness", action="store_true")
    args = ap.parse_args()
    if args.sealed_readiness:
        print(json.dumps(sealed_readiness(),ensure_ascii=False,indent=2))
        return
    pilot = json.loads(FROZEN.read_text(encoding="utf-8"))
    if (pilot.get("experiment_id") != "V29_20261102_CAPITAL_AWARE_EIGHT_NAME_EXPLORATORY_RESEARCH"
            or pilot.get("live_buy_eligibility") != "NOT_AUTHORIZED"):
        raise ValueError("FROZEN_PILOT_CHANGED")
    data = json.loads(args.private_input.read_text(encoding="utf-8"))
    ids = pilot["pre_outcome_rule"]["selected_ids_in_rank_order"]
    print(json.dumps(assess(ids, data["account"], data["positions"]),ensure_ascii=False,indent=2))

if __name__ == "__main__":
    main()
