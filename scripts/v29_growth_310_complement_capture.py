#!/usr/bin/env python3
"""One bounded supplementary 188-name price capture after frozen 122 outcome.

Reuses the parent's verified 122 exit-time observations; adds only the fixed
complement. This is a same-day post-close paper reference comparison, not
proof of auction fills, independent alpha, or BUY permission.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from v29_growth_310_conditional_result import ROOT, load_fixed, maturity, evaluate, PARENT_OUTCOME
from v29_growth_forward_cohort import evaluate as evaluate_parent
from v29_forward122_20th_session_exit_capture import (
    active_bar, bars_by_day, canonical_bytes, sha,
)
from v29_forward122_preentry_source_check import FIELDS, baostock_code
from v29_2025_filing_to_return_case import records

CN = ZoneInfo("Asia/Shanghai")
PARENT_RAW = "research/V2.9_FORWARD_122_20_SESSION_OUTCOME_2026/RAW_VENDOR_STOCK_AND_H00300_INDEX.json.gz"
SCHEMA = "V29_310_SAME_VINTAGE_CLOSE_PROXIES_V1"


def as_price(value):
    try:
        x = float(value)
        return x if 0 < x < float("inf") else None
    except (TypeError, ValueError):
        return None


def one_complement(sid, sessions, raw, adjusted):
    source = {"security_id": sid, "raw_unadjusted": raw, "forward_adjusted": adjusted}
    row = {"security_id": sid, "entry_tradeable": False, "exit_tradeable": False,
           "adjusted_for_corporate_actions": False, "adjusted_entry_close": None,
           "adjusted_exit_close": None, "raw_quote_sha256": sha(canonical_bytes(source)),
           "actual_entry_fill_proven": False, "actual_exit_fill_proven": False}
    try:
        unadjusted = bars_by_day(sid, raw, "3", set(sessions))
        forward = bars_by_day(sid, adjusted, "2", set(sessions))
        e, x = unadjusted.get(sessions[0]), unadjusted.get(sessions[-1])
        ae, ax = forward.get(sessions[0]), forward.get(sessions[-1])
        if not (e and x and ae and ax):
            row["source_status"] = "MISSING_FIXED_ENDPOINT"
            return row, source
        row["entry_ST_flag"] = e.get("isST") == "1"
        row["exit_ST_flag"] = x.get("isST") == "1"
        row["entry_tradeable"] = active_bar(e)
        row["exit_tradeable"] = active_bar(x, allow_exit_st=True)
        if not (row["entry_tradeable"] and row["exit_tradeable"]):
            row["source_status"] = "ENDPOINT_NOT_ACTIVE_OR_ST_OR_NO_VOLUME"
            return row, source
        ep, xp = as_price(ae.get("close")), as_price(ax.get("close"))
        if ep is None or xp is None:
            row["source_status"] = "INVALID_ADJUSTED_ENDPOINT"
            return row, source
        row.update({"adjusted_entry_close": ep, "adjusted_exit_close": xp,
                    "adjusted_for_corporate_actions": True,
                    "source_status": "RETROSPECTIVE_VENDOR_CLOSE_PROXY_NOT_BROKER_FILL"})
        return row, source
    except (ValueError, KeyError, TypeError) as ex:
        row["source_status"] = "BAD_QUOTE_SOURCE:" + type(ex).__name__
        return row, source


def read_parent(root, now):
    if now.astimezone(CN) < datetime(2026, 11, 27, 16, 30, tzinfo=CN):
        raise ValueError("FUTURE_OUTCOME_EMBARGO")
    root = Path(root)
    parent = json.loads((root / PARENT_OUTCOME).read_text(encoding="utf-8"))
    sessions = maturity(parent, now)
    verified = evaluate_parent(parent, root=root, now=now)
    if verified["status"] != "ONE_EPISODE_DESCRIPTIVE_NOT_BUY_EVIDENCE":
        raise ValueError("ORIGINAL_122_OUTCOME_NOT_COMPLETE")
    original = gzip.decompress((root / PARENT_RAW).read_bytes())
    if hashlib.sha256(original).hexdigest() != parent["raw_outcome_sources_sha256"]:
        raise ValueError("PARENT_122_RAW_SHA_MISMATCH")
    saved = json.loads(original)
    rows = saved["stock_sources"]
    if len(rows) != 122 or len(parent["securities"]) != 122:
        raise ValueError("PARENT_122_RAW_COUNT_MISMATCH")
    by_sid = {r["canonical_security_id"]: r for r in parent["securities"]}
    if len(by_sid) != 122:
        raise ValueError("PARENT_122_DUPLICATE")
    for source in rows:
        sid = source["security_id"]
        if sid not in by_sid or sha(canonical_bytes(source)) != by_sid[sid]["raw_quote_sha256"]:
            raise ValueError("PARENT_122_ROW_SOURCE_IDENTITY_CHANGED")
    return parent, sessions, original


def capture(bs, root=ROOT, now=None):
    now = now or datetime.now(timezone.utc)
    root = Path(root)
    parent, sessions, original = read_parent(root, now)
    registered, ids, selected, complement = load_fixed(root)
    parent_time = datetime.fromisoformat(parent["capture_timestamp"])
    if parent_time.astimezone(CN).date() != now.astimezone(CN).date():
        raise ValueError("SUPPLEMENT_NOT_SAME_EXIT_CAPTURE_DAY_AS_PARENT")

    login = bs.login()
    if login.error_code != "0":
        raise ValueError("BAOSTOCK_LOGIN_FAILED")
    results, sources = {}, []
    try:
        for sid in complement:
            code = baostock_code(sid)
            raw, adjusted = [], []
            try:
                raw = records(bs.query_history_k_data_plus(
                    code, FIELDS, start_date=sessions[0], end_date=sessions[-1],
                    frequency="d", adjustflag="3"))
                adjusted = records(bs.query_history_k_data_plus(
                    code, FIELDS, start_date=sessions[0], end_date=sessions[-1],
                    frequency="d", adjustflag="2"))
                row, source = one_complement(sid, sessions, raw, adjusted)
            except (OSError, ValueError, KeyError) as ex:
                row, source = one_complement(sid, sessions, raw, adjusted)
                row["source_status"] = "SOURCE_QUERY_FAILED:" + type(ex).__name__
            results[sid] = row
            sources.append(source)
    finally:
        bs.logout()

    by_parent = {r["canonical_security_id"]: r for r in parent["securities"]}
    for sid in selected:
        p = by_parent[sid]
        results[sid] = {
            "security_id": sid,
            "entry_tradeable": p["entry_tradeable_at_reference_close"],
            "exit_tradeable": p["exit_tradeable_at_reference_close"],
            "entry_ST_flag": p.get("entry_ST_flag"),
            "exit_ST_flag": p.get("exit_ST_flag"),
            "adjusted_for_corporate_actions": p["corporate_actions_and_dividends_adjusted"],
            "adjusted_entry_close": p["adjusted_entry_close"],
            "adjusted_exit_close": p["adjusted_exit_close"],
            "raw_quote_sha256": p["raw_quote_sha256"],
            "source_status": "REUSED_IMMUTABLE_FROZEN_122_OUTCOME",
            "actual_entry_fill_proven": False, "actual_exit_fill_proven": False,
        }
    archive = {"schema": "V29_310_COMPLEMENT_188_RAW_VENDOR_SOURCE_V1",
               "parent_122_source_sha256": hashlib.sha256(original).hexdigest(),
               "parent_122_protocol_sha256": parent["protocol_sha256"],
               "fixed_entry_session": sessions[0], "fixed_exit_session": sessions[-1],
               "actual_capture_time": now.isoformat(), "complement_188_sources": sources}
    raw_bytes = canonical_bytes(archive)
    observation = {
        "schema": SCHEMA, "entry_session": sessions[0], "exit_session": sessions[-1],
        "vendor": "BAOSTOCK", "adjustment": "FORWARD_ADJUSTED_SAME_EXIT_CAPTURE_VINTAGE",
        "captured_at": now.isoformat(), "raw_sources_sha256": sha(raw_bytes),
        "securities": [results[sid] for sid in ids],
    }
    result = evaluate(observation, parent, root=root, now=now)
    if result["strategy_validated"] or result["live_buy_eligibility"] != "NOT_AUTHORIZED":
        raise ValueError("UNEXPECTED_TRADING_AUTHORITY")
    return observation, result, raw_bytes


def save(out, observation, result, raw):
    out = Path(out)
    if out.exists():
        raise ValueError("DO_NOT_OVERWRITE_RESEARCH_SOURCE")
    if (len(observation["securities"]) != 310
            or hashlib.sha256(raw).hexdigest() != observation["raw_sources_sha256"]):
        raise ValueError("BAD_COMPLEMENT_EVIDENCE")
    out.mkdir(parents=True)
    (out / "310_CONDITIONAL_RESULT.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out / "310_SAME_VINTAGE_CLOSE_PROXIES.json").write_text(json.dumps(observation, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with (out / "RAW_188_QUOTES.json.gz").open("wb") as f:
        with gzip.GzipFile(fileobj=f, mode="wb", mtime=0) as z:
            z.write(raw)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()
    now = datetime.now(timezone.utc)
    if now.astimezone(CN) < datetime(2026, 11, 27, 16, 30, tzinfo=CN):
        raise SystemExit("FUTURE_OUTCOME_EMBARGO")
    import baostock
    observation, result, raw = capture(baostock, now=now)
    save(args.out, observation, result, raw)
    print(json.dumps({"status": result["status"], "selected": result["selected_computable"],
                      "comparator": result["comparator_computable"], "BUY": "NOT_AUTHORIZED"},
                     ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
