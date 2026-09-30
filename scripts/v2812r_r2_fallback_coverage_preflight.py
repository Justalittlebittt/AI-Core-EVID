from __future__ import annotations

import csv
import hashlib
import importlib.metadata
import json
from pathlib import Path

import baostock as bs

BASE = Path("evidence/retrospective_feasibility")
AMENDMENT = Path("evidence/V2.8.12R_RETROSPECTIVE_FEASIBILITY_CONTRACT_AMENDMENT_5.json")
PRIMARY = BASE / "V2.8.12R_R2_SOURCE_COVERAGE_PREFLIGHT_RECEIPT.json"
R1_GATE = BASE / "V2.8.12R_R1_TECHNICAL_GATE_RECONCILED_RECEIPT.json"
FINAL_COHORT = BASE / "V2.8.12R_FINAL_PRE_OUTCOME_COHORT.csv"
FINAL_RECEIPT = BASE / "V2.8.12R_FINAL_PRE_OUTCOME_COHORT_RECEIPT.json"
CALENDAR = Path("evidence/V2.8.5_JOINT_A_SHARE_TRADING_CALENDAR_2023_2024.json")
OUT = BASE / "V2.8.12R_R2_FALLBACK_SOURCE_COVERAGE_PREFLIGHT_RECEIPT.json"


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def stable_sha(obj) -> str:
    return hashlib.sha256(json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def rows(path: Path) -> list[dict]:
    return list(csv.DictReader(path.read_text(encoding="utf-8").splitlines()))


def load_calendar() -> list[str]:
    obj = read_json(CALENDAR)
    if obj.get("status") != "PASS":
        raise RuntimeError("CALENDAR_NOT_PASS")
    days = [str(x) for x in obj.get("trading_dates", [])]
    if len(days) != int(obj.get("trading_day_count", -1)) or len(days) != 484:
        raise RuntimeError("CALENDAR_COUNT_DRIFT")
    if days != sorted(set(days)):
        raise RuntimeError("CALENDAR_ORDER_OR_DUPLICATE_BLOCK")
    return days


def target(days: list[str], d: str, n: int) -> str:
    i = days.index(d)
    return days[i + n]


def bs_symbol(cid: str) -> str:
    ex, code = cid.split(":", 1)
    if ex == "SSE":
        return f"sh.{code}"
    if ex == "SZSE":
        return f"sz.{code}"
    raise RuntimeError(f"UNSUPPORTED_CANONICAL_SECURITY_ID:{cid}")


def verify_authorization() -> tuple[dict, dict]:
    a = read_json(AMENDMENT)
    p = read_json(PRIMARY)
    g = read_json(R1_GATE)
    f = read_json(FINAL_RECEIPT)
    if a.get("status") != "ACTIVE_FREE_PUBLIC_FALLBACK_SOURCE_COVERAGE_PREFLIGHT":
        raise RuntimeError("AMENDMENT5_NOT_ACTIVE")
    if p.get("status") != "PRIMARY_SOURCE_COVERAGE_FAIL_FALLBACK_AMENDMENT_REQUIRED":
        raise RuntimeError("PRIMARY_SOURCE_NOT_FAILED")
    if p.get("stock_coverage_rate") != 0.0 or p.get("benchmark_coverage_rate") != 0.0:
        raise RuntimeError("PRIMARY_FAILURE_SHAPE_DRIFT")
    if p.get("numeric_price_columns_read") is not False or p.get("returns_computed") is not False:
        raise RuntimeError("PRIMARY_PREFLIGHT_PRICE_FIREWALL_BROKEN")
    if g.get("status") != "R1_COHORT_TECHNICALLY_COMPLETE" or g.get("R2_price_or_return_access_authorized") is not True:
        raise RuntimeError("R1_RECONCILED_GATE_NOT_PASS")
    if f.get("status") != "PASS_FINAL_PRE_OUTCOME_COHORT_FROZEN" or f.get("price_or_return_data_consumed") is not False:
        raise RuntimeError("FINAL_COHORT_NOT_FROZEN")
    if a["fallback_source_identity"]["requested_fields"] != ["date", "code"]:
        raise RuntimeError("FALLBACK_FIELDS_DRIFT")
    if a["authorization_boundary"]["price_values_may_be_read_or_logged"] is not False:
        raise RuntimeError("FALLBACK_PRICE_AUTH_DRIFT")
    if a["authorization_boundary"]["returns_may_be_computed"] is not False:
        raise RuntimeError("FALLBACK_RETURN_AUTH_DRIFT")
    actual_version = importlib.metadata.version("baostock")
    if actual_version != a["fallback_source_identity"]["package_version"]:
        raise RuntimeError(f"BAOSTOCK_VERSION_DRIFT:{actual_version}")
    return a, f


def query_dates(code: str, start: str, end: str) -> tuple[set[str], str | None, str | None]:
    rs = bs.query_history_k_data_plus(
        code,
        "date,code",
        start_date=start,
        end_date=end,
        frequency="d",
        adjustflag="3",
    )
    if rs.error_code != "0":
        raise RuntimeError(f"BAOSTOCK_QUERY_ERROR:{code}:{rs.error_code}:{rs.error_msg}")
    got: list[str] = []
    while rs.next():
        row = rs.get_row_data()
        if len(row) != 2:
            raise RuntimeError(f"BAOSTOCK_FIELD_COUNT_DRIFT:{code}:{len(row)}")
        d, returned_code = row
        if returned_code != code:
            raise RuntimeError(f"BAOSTOCK_CODE_DRIFT:{code}:{returned_code}")
        got.append(d)
    uniq = set(got)
    return uniq, (min(uniq) if uniq else None), (max(uniq) if uniq else None)


def main() -> None:
    a, final_receipt = verify_authorization()
    days = load_calendar()
    cohort = rows(FINAL_COHORT)
    expected_stock: list[dict] = []
    expected_bench: list[dict] = []
    for r in cohort:
        d = r["retrospective_causal_effective_date"]
        dates = {"D": d, "D+5": target(days, d, 5), "D+10": target(days, d, 10)}
        sym = bs_symbol(r["canonical_security_id"])
        for label, rd in dates.items():
            expected_stock.append({"event_key": r["announcement_id"], "symbol": sym, "required_label": label, "required_date": rd})
            expected_bench.append({"event_key": r["announcement_id"], "symbol": "sh.000300", "required_label": label, "required_date": rd})

    all_dates = [x["required_date"] for x in expected_stock]
    start, end = min(all_dates), max(all_dates)
    lg = bs.login()
    if lg.error_code != "0":
        raise RuntimeError(f"BAOSTOCK_LOGIN_ERROR:{lg.error_code}:{lg.error_msg}")
    try:
        stock_presence: dict[str, set[str]] = {}
        stock_extent: dict[str, dict[str, str | None]] = {}
        for sym in sorted({x["symbol"] for x in expected_stock}):
            present, lo, hi = query_dates(sym, start, end)
            stock_presence[sym] = present
            stock_extent[sym] = {"min_date": lo, "max_date": hi}
        bench_present, blo, bhi = query_dates("sh.000300", start, end)
    finally:
        bs.logout()

    missing_stock = [x for x in expected_stock if x["required_date"] not in stock_presence[x["symbol"]]]
    missing_bench = [{k: v for k, v in x.items() if k != "symbol"} for x in expected_bench if x["required_date"] not in bench_present]
    stock_required = len(expected_stock)
    bench_required = len(expected_bench)
    stock_present_count = stock_required - len(missing_stock)
    bench_present_count = bench_required - len(missing_bench)
    stock_rate = stock_present_count / stock_required if stock_required else 1.0
    bench_rate = bench_present_count / bench_required if bench_required else 1.0
    passed = stock_rate == 1.0 and bench_rate == 1.0

    out = {
        "schema": "AI_CORE_EVID_V2_8_12R_R2_FALLBACK_SOURCE_COVERAGE_PREFLIGHT_RECEIPT_V1",
        "version": "V2.8.12R",
        "status": "FALLBACK_SOURCE_COVERAGE_PASS_R2_OUTCOME_AUTHORIZATION_MAY_BE_FROZEN" if passed else "FALLBACK_SOURCE_COVERAGE_FAIL_R2_REMAINS_BLOCKED",
        "authority": str(AMENDMENT),
        "provider": "BaoStock",
        "package_version": importlib.metadata.version("baostock"),
        "requested_response_fields": ["date", "code"],
        "final_pre_outcome_cohort_sha256": final_receipt["final_cohort_sha256"],
        "event_count": len(cohort),
        "required_dates_per_event": ["D", "D+5", "D+10"],
        "query_range": {"start": start, "end": end},
        "stock_required_event_date_rows": stock_required,
        "stock_present_event_date_rows": stock_present_count,
        "stock_coverage_rate": stock_rate,
        "benchmark_required_event_date_rows": bench_required,
        "benchmark_present_event_date_rows": bench_present_count,
        "benchmark_coverage_rate": bench_rate,
        "missing_stock_event_dates": missing_stock,
        "missing_benchmark_event_dates": missing_bench,
        "stock_source_date_extent_for_cohort_symbols": stock_extent,
        "benchmark_source_date_extent": {"min_date": blo, "max_date": bhi},
        "numeric_price_fields_requested": False,
        "numeric_price_values_read_or_logged": False,
        "returns_computed": False,
        "retrospective_event_cohort_changed": False,
        "prospective_gate_changed": False,
        "fold3_accessed": False,
        "fold4_accessed": False,
        "setup_or_live_accessed": False,
        "outcome_resolution_authorized_by_preflight_itself": False,
        "next_stage": "FREEZE_SEPARATE_R2_OUTCOME_RESOLUTION_AUTHORIZATION" if passed else "R2_BLOCK_NO_EVENT_OR_DATE_SUBSTITUTION"
    }
    out["receipt_sha256"] = stable_sha(out)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
