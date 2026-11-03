#!/usr/bin/env python3
"""Read-only eight-name shared-account capacity; no BUY or broker access."""
import argparse
import json
from decimal import Decimal, InvalidOperation
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FROZEN = ROOT / "research/V2.9_EIGHT_NAME_LOT_AWARE_PROSPECTIVE_PILOT_PREOUTCOME_20261102.json"

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
    if len(ids) != 8 or len(set(ids)) != 8:
        raise ValueError("EXPECTED_FROZEN_EIGHT")
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

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--private-input", type=Path, required=True)
    args = ap.parse_args()
    pilot = json.loads(FROZEN.read_text(encoding="utf-8"))
    if (pilot.get("experiment_id") != "V29_20261102_CAPITAL_AWARE_EIGHT_NAME_EXPLORATORY_RESEARCH"
            or pilot.get("live_buy_eligibility") != "NOT_AUTHORIZED"):
        raise ValueError("FROZEN_PILOT_CHANGED")
    data = json.loads(args.private_input.read_text(encoding="utf-8"))
    ids = pilot["pre_outcome_rule"]["selected_ids_in_rank_order"]
    print(json.dumps(assess(ids, data["account"], data["positions"]),ensure_ascii=False,indent=2))

if __name__ == "__main__":
    main()
