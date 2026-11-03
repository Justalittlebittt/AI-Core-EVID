#!/usr/bin/env python3
"""Fixed 15-of-256 original-table issuer-years: retrospective 20-session price coverage.
The 15 were selected by original PDF field coverage BEFORE fetching any returns.
Research-only; 2026-adjusted vendor history is not historical PIT or unseen OOS.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "research/v29_original_table_24_20261031/FIXED_24_ORIGINAL_YEAR_TABLE_FIELDS.json"
EXPECTED = {
    (2022, "SSE:688416"), (2022, "SSE:600088"), (2022, "SZSE:002177"),
    (2022, "SSE:605100"), (2022, "SSE:688185"), (2022, "SSE:603233"),
    (2022, "SZSE:001896"), (2023, "SSE:688031"), (2023, "SZSE:000070"),
    (2023, "SSE:688141"), (2023, "SZSE:300822"), (2023, "SZSE:002191"),
    (2023, "SZSE:000501"), (2023, "SSE:603333"), (2023, "SZSE:300224")
}
FIELDS = ("revenue_yuan", "parent_net_profit_yuan", "revenue_growth_yoy_pct", "weighted_roe_pct")
QUOTE_FIELDS = "date,code,close,adjustflag,tradestatus,volume,amount,isST"

def fixed_records(path=SOURCE):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("frozen_audit_sample_count") != 24 or len(data.get("rows", [])) != 24:
        raise ValueError("SOURCE_AUDIT_CHANGED")
    selected = []
    for row in data["rows"]:
        if not row.get("original_table_all_four_fields_unambiguous"):
            continue
        if not all(row.get("field_sources", {}).get(f, {}).get("original_current_year_table_source_status")
                   == "UNIQUE_FISCAL_YEAR_TABLE_CELL_EXTRACTED" for f in FIELDS):
            raise ValueError("ORIGINAL_FIELDS_UNVERIFIED")
        selected.append(row)
    if len(selected) != 15 or {(r["fiscal_year"], r["security_id"]) for r in selected} != EXPECTED:
        raise ValueError("FROZEN_FIFTEEN_CHANGED")
    return selected

def rows_from_vendor(result):
    if result.error_code != "0":
        raise ValueError("BAOSTOCK_QUERY_FAILED:" + str(result.error_msg))
    output = []
    while result.next():
        output.append(dict(zip(result.fields, result.get_row_data())))
    return output

def compute(records, calendars, quotes):
    output = []
    for original in records:
        sid = original["security_id"]
        fy = original["fiscal_year"]
        y = fy + 1
        day = date.fromisoformat(original["official_announcement_day"])
        raw_calendar = calendars[str(y)]
        sessions = sorted({date.fromisoformat(r["calendar_date"])
                           for r in raw_calendar if r.get("is_trading_day") == "1"})
        if len(sessions) < 40:
            raise ValueError("CALENDAR_INCOMPLETE:" + str(y))
        after = [d for d in sessions if d > day]
        if len(after) < 20:
            raise ValueError("INSUFFICIENT_POST_NOTICE_CALENDAR:" + sid)
        entry, finish = after[0], after[19]
        rows = quotes[f"{fy}|{sid}"]
        bars = {}
        for kind in ("unadjusted", "forward_adjusted"):
            code = ("sh." if sid.startswith("SSE:") else "sz.") + sid.split(":")[1]
            series = {}
            for r in rows[kind]:
                d = date.fromisoformat(r["date"])
                if r["code"] != code or d in series or r.get("adjustflag") != ("3" if kind == "unadjusted" else "2"):
                    raise ValueError("QUOTE_IDENTITY_OR_ADJUSTMENT_CHANGED:" + sid)
                series[d] = r
            bars[kind] = series
        e, z = bars["unadjusted"].get(entry), bars["unadjusted"].get(finish)
        ea, za = bars["forward_adjusted"].get(entry), bars["forward_adjusted"].get(finish)
        reasons = []
        if any(b is None for b in (e, z, ea, za)):
            reasons.append("MISSING_PRICE_ENDPOINT")
        if e is not None and z is not None and (e.get("tradestatus") != "1" or z.get("tradestatus") != "1"
                                                or e.get("isST") == "1" or z.get("isST") == "1"):
            reasons.append("ENTRY_OR_EXIT_NOT_TRADEABLE_OR_ST")
        parsed = {}
        if not reasons:
            for name, row in (("entry_unadjusted", e), ("exit_unadjusted", z),
                              ("entry_adjusted", ea), ("exit_adjusted", za)):
                try:
                    p = float(row["close"])
                except (TypeError, ValueError, KeyError):
                    p = float("nan")
                if not math.isfinite(p) or p <= 0:
                    reasons.append("INVALID_CLOSE")
                    break
                parsed[name] = p
        price_return = (parsed["exit_unadjusted"] / parsed["entry_unadjusted"] - 1) if not reasons else None
        adjusted_return = (parsed["exit_adjusted"] / parsed["entry_adjusted"] - 1) if not reasons else None
        output.append({
            "security_id": sid, "fiscal_year": fy, "original_notice_day": day.isoformat(),
            "entry_session": entry.isoformat(), "twentieth_session": finish.isoformat(),
            "status": "RETROSPECTIVE_PRICE_PAIR_AVAILABLE" if not reasons else "INCOMPLETE_NEVER_DROP",
            "failure_reasons": sorted(set(reasons)), "unadjusted_price_return": price_return,
            "later_vintage_forward_adjusted_return_sensitivity": adjusted_return,
            "later_vintage_adjusted_return_minus_30bps": adjusted_return - 0.003 if adjusted_return is not None else None,
            "historical_dividend_total_return_certified": False, "original_time_price_vintage_certified": False,
            "strategy_alpha_validated": False, "live_buy_eligibility": "NOT_AUTHORIZED"
        })
    return output

def collect(out, bs):
    if out.exists():
        raise ValueError("NO_OVERWRITE")
    records = fixed_records()
    status = bs.login()
    if status.error_code != "0":
        raise ValueError("BAOSTOCK_LOGIN_FAILED")
    calendars = {}
    quotes = {}
    try:
        for y in (2023, 2024):
            calendars[str(y)] = rows_from_vendor(bs.query_trade_dates(start_date=f"{y}-03-01", end_date=f"{y}-07-15"))
        for r in records:
            fy, sid = r["fiscal_year"], r["security_id"]
            y = fy + 1
            code = ("sh." if sid.startswith("SSE:") else "sz.") + sid.split(":")[1]
            quotes[f"{fy}|{sid}"] = {}
            for kind, flag in (("unadjusted", "3"), ("forward_adjusted", "2")):
                quotes[f"{fy}|{sid}"][kind] = rows_from_vendor(bs.query_history_k_data_plus(
                    code, QUOTE_FIELDS, start_date=f"{y}-03-01", end_date=f"{y}-07-15",
                    frequency="d", adjustflag=flag))
    finally:
        bs.logout()
    raw = (json.dumps({"calendars": calendars, "quotes": quotes}, sort_keys=True,
                      ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
    output = compute(records, calendars, quotes)
    receipt = {
        "schema": "V29_HISTORICAL_ORIGINAL_PDF_15_POST_FILING_20_SESSION_PRICE_COVERAGE_V1",
        "source": str(SOURCE.relative_to(ROOT)), "original_audit_denominator": 24,
        "historical_universe_issuer_year_denominator": 256,
        "source_selected_before_return_retrieval": True,
        "number_of_fixed_selected_issuer_years": 15,
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "vendor": "BAOSTOCK_RETROSPECTIVE_2026_QUERY",
        "price_adjusted_vintage": "FORWARD_ADJUSTED_QUERY_AT_CAPTURE_NOT_HISTORICAL_PIT",
        "raw_market_and_calendar_sha256": hashlib.sha256(raw).hexdigest(),
        "paired_count": sum(x["status"] == "RETROSPECTIVE_PRICE_PAIR_AVAILABLE" for x in output),
        "missing_count": sum(x["status"] != "RETROSPECTIVE_PRICE_PAIR_AVAILABLE" for x in output),
        "unseen_oos": False, "dividend_total_return_certified": False,
        "historical_alpha_validated": False, "live_buy_eligibility": "NOT_AUTHORIZED",
        "rows": output,
    }
    out.mkdir(parents=True)
    (out / "RAW_15_MARKET_AND_CALENDAR.json").write_bytes(raw)
    (out / "PRICE_PAIR_COVERAGE_15.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return receipt

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    import baostock
    result = collect(args.out, baostock)
    print(json.dumps({k: v for k, v in result.items() if k != "rows"}, ensure_ascii=False))

if __name__ == "__main__":
    main()
