#!/usr/bin/env python3
"""Decision-time minimum-lot budget feasibility for an arbitrary A-share candidate pool.

Not a trading instruction. No price fetching, no future outcomes, no ranking changes.
"""
from datetime import date
from decimal import Decimal, InvalidOperation

SCHEMA = 'V32_GENERIC_PRE_OUTCOME_BUY_FEASIBILITY_V1'


def dec(value):
    try:
        if isinstance(value, bool):
            raise ValueError('BOOLEAN_NOT_AMOUNT')
        result = Decimal(str(value))
    except (InvalidOperation, TypeError) as exc:
        raise ValueError('INVALID_AMOUNT') from exc
    if not result.is_finite() or result < 0:
        raise ValueError('INVALID_AMOUNT')
    return result


def board_lot(sid):
    if not isinstance(sid, str) or ':' not in sid:
        raise ValueError('INVALID_A_SHARE_ID')
    exchange, code = sid.split(':', 1)
    if len(code) != 6 or not code.isascii() or not code.isdigit():
        raise ValueError('INVALID_A_SHARE_ID')
    if exchange == 'SSE' and code.startswith(('688', '689')):
        return 'star', 200
    if exchange == 'SSE' and code.startswith(('600', '601', '603', '605')):
        return 'main', 100
    if exchange == 'SZSE' and code.startswith(('300', '301')):
        return 'chinext', 100
    if exchange == 'SZSE' and code.startswith(('000', '001', '002', '003')):
        return 'main', 100
    raise ValueError('NOT_SUPPORTED_A_SHARE_STOCK_ID:' + sid)


def evaluate(candidates, account):
    """Keep every original candidate and its rank; never substitute missing stocks.

    Required account: cash_cny, slot_cap_cny, fee_reserve_cny, permissions.
    Candidate: security_id, reference_price_cny, reference_session.
    Passing means PAPER_MIN_LOT_AFFORDABLE_ONLY, never an order or BUY signal.
    """
    if not isinstance(candidates, list) or not isinstance(account, dict):
        raise ValueError('INVALID_BOUNDARY_INPUT')
    cash = dec(account['cash_cny'])
    slot = dec(account['slot_cap_cny'])
    reserve = dec(account['fee_reserve_cny'])
    if slot == 0 or reserve > cash:
        raise ValueError('INVALID_ACCOUNT_BUDGET')
    permissions = account['permissions']
    if not isinstance(permissions, dict) or any(type(permissions.get(x)) is not bool for x in ('main', 'chinext', 'star')):
        raise ValueError('BOARD_PERMISSIONS_UNVERIFIED')
    result = []
    seen = set()
    for row in candidates:
        sid = row['security_id']
        if sid in seen:
            raise ValueError('DUPLICATE_RESEARCH_CANDIDATE')
        seen.add(sid)
        board, shares = board_lot(sid)
        price = dec(row['reference_price_cny'])
        asof = row['reference_session']
        if price == 0 or not isinstance(asof, str) or len(asof) != 10 or asof[4] != '-' or asof[7] != '-':
            raise ValueError('INVALID_REFERENCE_PRICE_OR_DATE')
        try:
            parsed_date = date.fromisoformat(asof)
        except ValueError as exc:
            raise ValueError('INVALID_REFERENCE_PRICE_OR_DATE') from exc
        if parsed_date.isoformat() != asof:
            raise ValueError('INVALID_REFERENCE_PRICE_OR_DATE')
        gross = price * shares
        # Fixed illustrative entry assumptions, not user broker's actual fees.
        fee = max(Decimal('5'), gross * Decimal('0.0003'))
        slip = gross * Decimal('0.001')
        need = gross + fee + slip
        reasons = []
        if not permissions[board]:
            reasons.append('BOARD_PERMISSION_NOT_CONFIRMED')
        if need > slot:
            reasons.append('MIN_LOT_OVER_PER_NAME_SLOT')
        if need > cash - reserve:
            reasons.append('MIN_LOT_OVER_AVAILABLE_CASH')
        result.append({
            'security_id':sid, 'board':board, 'minimum_buy_shares':shares,
            'reference_session':asof,
            'paper_min_lot_all_in_cny':str(need),
            'gate':'PAPER_MIN_LOT_AFFORDABLE_ONLY' if not reasons else 'BLOCKED_PAPER_BUY',
            'reasons':reasons,
            'broker_fill_certified':False,
            'buy_authorized':False,
        })
    return {
        'schema':SCHEMA, 'candidate_count':len(result),
        'original_candidates_in_original_order':result,
        'no_rank_or_membership_replacement':True,
        'entry_assumptions':{'min_commission_cny':'5','commission_rate':'0.0003','entry_slippage_rate':'0.001'},
        'shared_portfolio_cash_allocation_not_certified':True,
        'limit_price_liquidity_and_broker_fills_not_certified':True,
        'predictive_alpha_not_assessed':True,
        'trade_authorized':False,
    }
