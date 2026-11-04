#!/usr/bin/env python3
"""One-episode 310/122/188 conditional contrast; NOT a strategy or trade signal.

Reads one independently captured, same-vintage 310-name price-source file
only after the frozen parent study's twentieth verified trading session.
No quote fetching, scheduling, risk-engine duplication or trading authority.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
import math
import re
from datetime import datetime, date, time, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
CN = ZoneInfo("Asia/Shanghai")
SHA = re.compile(r"^[0-9a-f]{64}$")
REGISTER = "research/V2.9_GROWTH_310_CONDITIONAL_CONTROL_PREOUTCOME_20261102.json"
FRAME = "research/V2.9_GROWTH_310_PREOUTCOME_FINANCIAL_FRAME_20261102.csv"
FLAGS = "research/V2.9_GROWTH_310_PREOUTCOME_SOURCE_RISK_FLAGS_20261102.csv"
PARENT_SPEC = "research/V2.9_GROWTH_122_FORWARD_EVALUATION_PROTOCOL.json"
PARENT_OUTCOME = "research/V2.9_FORWARD_122_20_SESSION_OUTCOME_2026/OUTCOMES_122.json"


def digest_ids(ids):
    return hashlib.sha256(("\n".join(ids) + "\n").encode()).hexdigest()


def load_fixed(root=ROOT):
    root = Path(root)
    spec = json.loads((root / REGISTER).read_text(encoding="utf-8"))
    fixed = spec["frozen_identity"]
    if spec["schema"] != "V29_GROWTH_310_CONDITIONAL_COMPARATOR_PREOUTCOME_V1":
        raise ValueError("INVALID_REGISTERED_COMPARISON")
    ids = fixed["all_310_sorted_ids"]
    if (len(ids) != 310 or ids != sorted(set(ids))
            or digest_ids(ids) != fixed["all_310_sorted_linefeed_sha256"]):
        raise ValueError("CHANGED_310_COHORT")

    original = (root / fixed["selected_122_authority"]).read_text(encoding="utf-8")
    match = re.search(r"## Canonical identities \(122\)[\s\S]*?```([\s\S]*?)```", original)
    if not match:
        raise ValueError("MISSING_ORIGINAL_122_MANIFEST")
    selected_in_original_order = match[1].strip().splitlines()
    selected = set(selected_in_original_order)
    if (len(selected) != 122 or not selected.issubset(ids)
            or digest_ids(selected_in_original_order) != fixed["selected_122_original_order_linefeed_sha256"]):
        raise ValueError("ORIGINAL_122_CHANGED")
    control = sorted(set(ids) - selected)
    if (len(control) != 188 or digest_ids(control) != fixed["comparator_188_sorted_linefeed_sha256"]):
        raise ValueError("COMPLEMENT_188_CHANGED")
    with (root / FRAME).open(encoding="utf-8-sig", newline="") as f:
        frame = list(csv.DictReader(f))
    with (root / FLAGS).open(encoding="utf-8-sig", newline="") as f:
        flags = list(csv.DictReader(f))
    if ([r["security_id"] for r in frame] != ids
            or [r["security_id"] for r in flags] != ids
            or any((r["group"] == "SELECTED_122") != (r["security_id"] in selected) for r in frame)
            or any((r["frozen_selected_122"] == "1") != (r["security_id"] in selected) for r in flags)
            or sum(r["no_specified_risk_flags"] == "1" for r in flags) != 210
            or any(r["frozen_selected_122"] == "1" and (r["no_specified_risk_flags"] != "1" or r["numeric_growth_and_core_pass"] != "1") for r in flags)):
        raise ValueError("PREOUTCOME_FINANCIAL_OR_SOURCE_FLAGS_CHANGED")
    return spec, ids, selected, control


def checked_positive(v):
    if type(v) not in (float, int) or not math.isfinite(v) or v <= 0:
        return None
    return float(v)


def maturity(parent, now):
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("CLOCK_REQUIRES_TIMEZONE")
    if now.astimezone(CN) < datetime(2026, 11, 27, 16, 30, tzinfo=CN):
        raise ValueError("PARENT_TWENTIETH_SESSION_NOT_YET_MATURE")
    if (parent.get("schema") != "V29_FORWARD_COHORT_OBSERVED_OUTCOMES_V1"
            or parent.get("experiment_id") != "V29_122_GROWTH_COHORT_PROSPECTIVE_20261030"):
        raise ValueError("INVALID_PARENT_RESEARCH")
    sessions = parent.get("verified_exchange_sessions")
    if not isinstance(sessions, list) or len(sessions) != 20:
        raise ValueError("NO_VERIFIED_TWENTY_SESSIONS")
    days = [date.fromisoformat(x) for x in sessions]
    if (days != sorted(set(days)) or days[0] != date(2026,11,2)
            or days[-1] < date(2026,11,27) or any(x.weekday() > 4 for x in days)):
        raise ValueError("PARENT_TRADING_SESSIONS_CHANGED")
    if now.astimezone(CN) < datetime.combine(days[-1], time(16,30), tzinfo=CN):
        raise ValueError("FINAL_TRADING_SESSION_NOT_CLOSED")
    return sessions


def evaluate(observations, parent, root=ROOT, now=None):
    # Both the real data file and the parent are read by main() ONLY after clock gate.
    now = now or datetime.now(timezone.utc)
    sessions = maturity(parent, now)
    spec, ids, selected, control = load_fixed(root)
    # Secondary, pre-maturity descriptive comparison within the SAME 210
    # pre-outcome clean records. The frozen 122-vs-188 primary stays intact.
    with (Path(root) / FLAGS).open(encoding="utf-8-sig", newline="") as f:
        clean_210 = {r["security_id"] for r in csv.DictReader(f)
                     if r["no_specified_risk_flags"] == "1"}
    clean_complement_88 = clean_210 - selected
    if len(clean_210) != 210 or len(clean_complement_88) != 88 or not clean_complement_88.issubset(control):
        raise ValueError("ORIGINAL_CLEAN_210_AND_88_SOURCE_CHANGED")
    parent_bytes = (Path(root) / PARENT_SPEC).read_bytes()
    if (parent.get("protocol_sha256") != hashlib.sha256(parent_bytes).hexdigest()
            or {r.get("canonical_security_id") for r in parent.get("securities", [])} != selected
            or len(parent.get("securities", [])) != 122):
        raise ValueError("PARENT_PROTOCOL_OR_SAMPLE_IDENTITY_FAILED")
    if (spec["supplementary_observation"]["transaction_cost_round_trip_fraction"] != 0.003):
        raise ValueError("CONDITIONAL_COST_CHANGED")
    if (observations.get("schema") != "V29_310_SAME_VINTAGE_CLOSE_PROXIES_V1"
            or observations.get("entry_session") != sessions[0]
            or observations.get("exit_session") != sessions[-1]
            or observations.get("vendor") != "BAOSTOCK"
            or observations.get("adjustment") != "FORWARD_ADJUSTED_SAME_EXIT_CAPTURE_VINTAGE"
            or not SHA.fullmatch(observations.get("raw_sources_sha256", ""))):
        raise ValueError("INCOMPATIBLE_PRICE_OBSERVATION")
    captured = datetime.fromisoformat(observations["captured_at"])
    if (captured.tzinfo is None or captured.utcoffset() is None or
            captured < datetime.combine(date.fromisoformat(sessions[-1]), time(16,30), tzinfo=CN)
            or captured > now):
        raise ValueError("INVALID_FUTURE_PRICE_CAPTURE_TIME")
    rows = observations.get("securities")
    if not isinstance(rows, list) or len(rows) != 310 or {r.get("security_id") for r in rows} != set(ids):
        raise ValueError("MISSING_DUPLICATED_OR_REPLACED_COHORT")
    if len({r["security_id"] for r in rows}) != 310:
        raise ValueError("DUPLICATE_PRICE_IDENTITY")
    returns = {}
    missing = {"selected": [], "comparator": []}
    for r in rows:
        sid = r["security_id"]
        good = (r.get("entry_tradeable") is True and r.get("exit_tradeable") is True
                and r.get("adjusted_for_corporate_actions") is True
                and SHA.fullmatch(str(r.get("raw_quote_sha256", ""))) is not None)
        ep, xp = checked_positive(r.get("adjusted_entry_close")), checked_positive(r.get("adjusted_exit_close"))
        if not good or ep is None or xp is None:
            missing["selected" if sid in selected else "comparator"].append(sid)
            continue
        returns[sid] = xp / ep - 1 - 0.003

    base = {
        "schema": "V29_GROWTH_310_FIXED_CONDITIONAL_COMPARISON_RESULT_V1",
        "registered_comparison": REGISTER,
        "fixed_entry_session": sessions[0], "fixed_exit_session": sessions[-1],
        "selected_total": 122, "comparator_total": 188,
        "clean_88_comparator_total": 88,
        "clean_88_definition": "ORIGINAL_NO_SPECIFIED_RISK_FLAGS_AND_NOT_IN_FROZEN_122",
        "clean_88_is_supplementary_pre_maturity_descriptive_only": True,
        "selected_computable": 122 - len(missing["selected"]),
        "clean_88_computable": sum(sid in returns for sid in clean_complement_88),
        "comparator_computable": 188 - len(missing["comparator"]),
        "missing_by_group": missing,
        "round_trip_cost": 0.003,
        "source_identity_asserted_not_independently_authenticated": True,
        "not_industry_or_market_cap_matched": True,
        "one_episode_not_independent_strategy_validation": True,
        "strategy_validated": False, "live_buy_eligibility": "NOT_AUTHORIZED"
    }
    if missing["selected"] or missing["comparator"]:
        return {**base, "status": "INSUFFICIENT_NEVER_DROP_NAMES",
                "mean_selected_net": None, "mean_comparator_net": None, "selected_minus_comparator": None,
                "mean_clean_88_net": None, "selected_minus_clean_88": None}
    a = sum(returns[s] for s in selected)/122
    b = sum(returns[s] for s in control)/188
    clean_b = sum(returns[s] for s in clean_complement_88)/88
    return {**base, "status": "ONE_EPISODE_DESCRIPTIVE_NOT_BUY_EVIDENCE",
            "mean_selected_net": a, "mean_comparator_net": b,
            "selected_minus_comparator": a-b,
            "mean_clean_88_net": clean_b,
            "selected_minus_clean_88": a-clean_b}


def main():
    p = argparse.ArgumentParser(description="Future-mature, source-bound 310/122/188 descriptive comparator")
    p.add_argument("--root", type=Path, default=ROOT)
    p.add_argument("--parent", type=Path)
    p.add_argument("--prices", type=Path, required=True)
    args = p.parse_args()
    now = datetime.now(timezone.utc)
    # Do not open any future-outcome input prior to the embargo expiry.
    if now.astimezone(CN) < datetime(2026,11,27,16,30,tzinfo=CN):
        raise SystemExit("FUTURE_OUTCOME_EMBARGO")
    parent_path = args.parent or args.root / PARENT_OUTCOME
    parent = json.loads(parent_path.read_text(encoding="utf-8"))
    sessions = maturity(parent, now)
    observation = json.loads(args.prices.read_text(encoding="utf-8"))
    print(json.dumps(evaluate(observation, parent, args.root, now), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
