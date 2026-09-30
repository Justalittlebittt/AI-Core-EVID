from __future__ import annotations

import csv
import hashlib
import json
import random
import statistics
from pathlib import Path
from typing import Iterable

import baostock as bs

BASE = Path("evidence/retrospective_feasibility")
CONTRACT = Path("evidence/V2.8.12R_RETROSPECTIVE_FEASIBILITY_SAMPLING_AND_OUTCOME_CONTRACT.json")
AUTH = Path("evidence/V2.8.12R_RETROSPECTIVE_FEASIBILITY_CONTRACT_AMENDMENT_6.json")
R1_GATE = BASE / "V2.8.12R_R1_TECHNICAL_GATE_RECONCILED_RECEIPT.json"
COHORT = BASE / "V2.8.12R_FINAL_PRE_OUTCOME_COHORT.csv"
COHORT_RECEIPT = BASE / "V2.8.12R_FINAL_PRE_OUTCOME_COHORT_RECEIPT.json"
FALLBACK_COVERAGE = BASE / "V2.8.12R_R2_FALLBACK_SOURCE_COVERAGE_PREFLIGHT_RECEIPT.json"
CALENDAR = Path("evidence/V2.8.5_JOINT_A_SHARE_TRADING_CALENDAR_2023_2024.json")
OUT_CSV = BASE / "V2.8.12R_R2_OUTCOME_RESULTS.csv"
OUT_RECEIPT = BASE / "V2.8.12R_R2_OUTCOME_RESOLUTION_RECEIPT.json"

FIELDS = [
    "announcement_id", "canonical_security_id", "security_name", "quarter",
    "D", "D5", "D10", "stock_close_D", "stock_close_D5", "stock_close_D10",
    "benchmark_close_D", "benchmark_close_D5", "benchmark_close_D10",
    "stock_return_D5", "benchmark_return_D5", "excess_return_D5",
    "stock_return_D10", "benchmark_return_D10", "excess_return_D10",
    "stock_response_sha256", "benchmark_response_sha256", "outcome_status"
]


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def rows(path: Path) -> list[dict]:
    return list(csv.DictReader(path.read_text(encoding="utf-8").splitlines()))


def sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def stable_sha(obj) -> str:
    return hashlib.sha256(json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def pct(values: list[float], q: float) -> float:
    if not values:
        raise RuntimeError("EMPTY_PERCENTILE")
    x = sorted(values)
    if len(x) == 1:
        return x[0]
    pos = (len(x) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(x) - 1)
    frac = pos - lo
    return x[lo] * (1 - frac) + x[hi] * frac


def fmt(x: float) -> str:
    return f"{x:.12f}"


def load_calendar() -> list[str]:
    obj = read_json(CALENDAR)
    if obj.get("status") != "PASS":
        raise RuntimeError("CALENDAR_NOT_PASS")
    ds = [str(x) for x in obj.get("trading_dates", [])]
    if ds != sorted(set(ds)) or len(ds) != int(obj.get("trading_day_count", -1)):
        raise RuntimeError("CALENDAR_DRIFT")
    return ds


def target(days: list[str], d: str, n: int) -> str:
    try:
        i = days.index(d)
    except ValueError as e:
        raise RuntimeError(f"EVENT_D_NOT_IN_CALENDAR:{d}") from e
    j = i + n
    if j >= len(days):
        raise RuntimeError(f"TARGET_OUTSIDE_CALENDAR:{d}:D+{n}")
    return days[j]


def bao_symbol(cid: str) -> str:
    ex, code = cid.split(":", 1)
    if ex == "SSE":
        return f"sh.{code}"
    if ex == "SZSE":
        return f"sz.{code}"
    raise RuntimeError(f"UNSUPPORTED_SECURITY:{cid}")


def query_series(code: str, start: str, end: str, adjustflag: str) -> tuple[dict[str, float], str]:
    rs = bs.query_history_k_data_plus(
        code,
        "date,code,close",
        start_date=start,
        end_date=end,
        frequency="d",
        adjustflag=adjustflag,
    )
    if rs.error_code != "0":
        raise RuntimeError(f"BAOSTOCK_QUERY_ERROR:{code}:{rs.error_code}:{rs.error_msg}")
    raw = []
    out: dict[str, float] = {}
    while (rs.error_code == "0") and rs.next():
        r = rs.get_row_data()
        if len(r) != 3:
            raise RuntimeError(f"BAOSTOCK_FIELD_COUNT:{code}:{r}")
        d, c, close = r
        if c != code:
            raise RuntimeError(f"BAOSTOCK_CODE_DRIFT:{code}:{c}")
        if not close:
            continue
        v = float(close)
        if v <= 0:
            raise RuntimeError(f"NONPOSITIVE_CLOSE:{code}:{d}:{close}")
        out[d] = v
        raw.append({"date": d, "code": c, "close": close})
    if rs.error_code != "0":
        raise RuntimeError(f"BAOSTOCK_ITER_ERROR:{code}:{rs.error_code}:{rs.error_msg}")
    return out, stable_sha({"code": code, "adjustflag": adjustflag, "rows": raw})


def verify_authorization() -> tuple[dict, dict]:
    auth = read_json(AUTH)
    if auth.get("status") != "ACTIVE_R2_OUTCOME_RESOLUTION_AUTHORIZATION":
        raise RuntimeError("OUTCOME_AUTH_NOT_ACTIVE")
    gate = read_json(R1_GATE)
    if gate.get("status") != "R1_COHORT_TECHNICALLY_COMPLETE" or gate.get("R2_price_or_return_access_authorized") is not True:
        raise RuntimeError("R1_GATE_NOT_AUTHORIZED")
    cr = read_json(COHORT_RECEIPT)
    if cr.get("status") != "PASS_FINAL_PRE_OUTCOME_COHORT_FROZEN" or cr.get("final_cohort_sha256") != sha_file(COHORT):
        raise RuntimeError("FINAL_COHORT_NOT_FROZEN")
    cov = read_json(FALLBACK_COVERAGE)
    if cov.get("status") != "FALLBACK_SOURCE_COVERAGE_PASS_R2_OUTCOME_AUTHORIZATION_MAY_BE_FROZEN":
        raise RuntimeError("FALLBACK_COVERAGE_NOT_PASS")
    if cov.get("stock_coverage_rate") != 1.0 or cov.get("benchmark_coverage_rate") != 1.0:
        raise RuntimeError("FALLBACK_COVERAGE_RATE_DRIFT")
    if cov.get("numeric_price_values_read_or_logged") is not False or cov.get("returns_computed") is not False:
        raise RuntimeError("PREFLIGHT_FIREWALL_BROKEN")
    if auth["source_and_vintage_contract"]["stock_adjustflag"] != "2":
        raise RuntimeError("STOCK_ADJUSTFLAG_DRIFT")
    if auth["source_and_vintage_contract"]["benchmark_adjustflag"] != "3":
        raise RuntimeError("BENCH_ADJUSTFLAG_DRIFT")
    contract = read_json(CONTRACT)
    return auth, contract


def main() -> None:
    auth, contract = verify_authorization()
    cohort = rows(COHORT)
    if len(cohort) != 4 or len({r["announcement_id"] for r in cohort}) != 4:
        raise RuntimeError("COHORT_CARDINALITY_DRIFT")

    days = load_calendar()
    enriched = []
    required_dates = []
    for r in cohort:
        d = r["retrospective_causal_effective_date"]
        d5 = target(days, d, 5)
        d10 = target(days, d, 10)
        z = dict(r)
        z.update({"D": d, "D5": d5, "D10": d10, "bao_symbol": bao_symbol(r["canonical_security_id"])})
        enriched.append(z)
        required_dates.extend([d, d5, d10])
    start, end = min(required_dates), max(required_dates)

    lg = bs.login()
    if lg.error_code != "0":
        raise RuntimeError(f"BAOSTOCK_LOGIN_ERROR:{lg.error_code}:{lg.error_msg}")
    try:
        stock_cache: dict[str, tuple[dict[str, float], str]] = {}
        for code in sorted({r["bao_symbol"] for r in enriched}):
            stock_cache[code] = query_series(code, start, end, auth["source_and_vintage_contract"]["stock_adjustflag"])
        bench_code = auth["source_and_vintage_contract"]["benchmark_symbol"]
        bench_series, bench_sha = query_series(code=bench_code, start=start, end=end, adjustflag=auth["source_and_vintage_contract"]["benchmark_adjustflag"])
    finally:
        bs.logout()

    out_rows = []
    unavailable = []
    for r in enriched:
        s, ssha = stock_cache[r["bao_symbol"]]
        dates = [r["D"], r["D5"], r["D10"]]
        missing = [d for d in dates if d not in s or d not in bench_series]
        if missing:
            unavailable.append({"announcement_id": r["announcement_id"], "missing_dates": missing})
            out_rows.append({
                "announcement_id": r["announcement_id"], "canonical_security_id": r["canonical_security_id"],
                "security_name": r["security_name"], "quarter": r["quarter"], "D": r["D"], "D5": r["D5"], "D10": r["D10"],
                "stock_response_sha256": ssha, "benchmark_response_sha256": bench_sha,
                "outcome_status": "OUTCOME_UNAVAILABLE_NO_SHIFT"
            })
            continue
        sd, s5, s10 = s[r["D"]], s[r["D5"]], s[r["D10"]]
        bd, b5, b10 = bench_series[r["D"]], bench_series[r["D5"]], bench_series[r["D10"]]
        sr5, br5 = s5 / sd - 1.0, b5 / bd - 1.0
        sr10, br10 = s10 / sd - 1.0, b10 / bd - 1.0
        out_rows.append({
            "announcement_id": r["announcement_id"], "canonical_security_id": r["canonical_security_id"],
            "security_name": r["security_name"], "quarter": r["quarter"], "D": r["D"], "D5": r["D5"], "D10": r["D10"],
            "stock_close_D": fmt(sd), "stock_close_D5": fmt(s5), "stock_close_D10": fmt(s10),
            "benchmark_close_D": fmt(bd), "benchmark_close_D5": fmt(b5), "benchmark_close_D10": fmt(b10),
            "stock_return_D5": fmt(sr5), "benchmark_return_D5": fmt(br5), "excess_return_D5": fmt(sr5 - br5),
            "stock_return_D10": fmt(sr10), "benchmark_return_D10": fmt(br10), "excess_return_D10": fmt(sr10 - br10),
            "stock_response_sha256": ssha, "benchmark_response_sha256": bench_sha, "outcome_status": "RESOLVED"
        })

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUT_CSV.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, lineterminator="\n", extrasaction="ignore")
        w.writeheader(); w.writerows(out_rows)

    resolved = [r for r in out_rows if r["outcome_status"] == "RESOLVED"]
    resolved_share = len(resolved) / len(out_rows)
    issuer_d10: dict[str, list[float]] = {}
    issuer_d5: dict[str, list[float]] = {}
    for r in resolved:
        issuer_d10.setdefault(r["canonical_security_id"], []).append(float(r["excess_return_D10"]))
        issuer_d5.setdefault(r["canonical_security_id"], []).append(float(r["excess_return_D5"]))
    issuer_medians_d10 = {k: statistics.median(v) for k, v in issuer_d10.items()}
    issuer_medians_d5 = {k: statistics.median(v) for k, v in issuer_d5.items()}

    primary = statistics.median(issuer_medians_d10.values()) if issuer_medians_d10 else None
    secondary_issuer_d5 = statistics.median(issuer_medians_d5.values()) if issuer_medians_d5 else None
    event_median_d10 = statistics.median(float(r["excess_return_D10"]) for r in resolved) if resolved else None
    event_median_d5 = statistics.median(float(r["excess_return_D5"]) for r in resolved) if resolved else None
    issuer_positive_share = (sum(v > 0 for v in issuer_medians_d10.values()) / len(issuer_medians_d10)) if issuer_medians_d10 else None
    event_positive_share = (sum(float(r["excess_return_D10"]) > 0 for r in resolved) / len(resolved)) if resolved else None

    boot = []
    if issuer_medians_d10:
        vals = list(issuer_medians_d10.values())
        rng = random.Random(2812)
        for _ in range(5000):
            sample = [vals[rng.randrange(len(vals))] for _ in vals]
            boot.append(statistics.median(sample))
    ci = [pct(boot, 0.025), pct(boot, 0.975)] if boot else [None, None]

    distinct_issuers = len({r["canonical_security_id"] for r in cohort})
    distinct_quarters = len({r["quarter"] for r in cohort})
    issuer_counts: dict[str, int] = {}
    for r in cohort:
        issuer_counts[r["canonical_security_id"]] = issuer_counts.get(r["canonical_security_id"], 0) + 1
    max_share = max(issuer_counts.values()) / len(cohort)
    floor = contract["analysis_contract"]["decision_eligibility_sample_floor"]
    floor_checks = {
        "frozen_positive_events_min_12": len(cohort) >= int(floor["frozen_positive_events_min"]),
        "distinct_issuers_min_6": distinct_issuers >= int(floor["distinct_issuers_min"]),
        "distinct_positive_quarters_min_6": distinct_quarters >= int(floor["distinct_positive_quarters_min"]),
        "maximum_single_issuer_event_share_le_one_third": max_share <= float(floor["maximum_single_issuer_event_share"]),
        "resolved_event_share_min_0_80": resolved_share >= float(floor["resolved_event_share_min"]),
    }
    sample_floor_pass = all(floor_checks.values())
    if not sample_floor_pass:
        verdict = "DESCRIPTIVE_ONLY_SAMPLE_TOO_SMALL_FOR_FEASIBILITY_VERDICT"
    elif primary is not None and primary > 0 and ci[0] is not None and ci[0] > 0:
        verdict = "PROMISING_RETROSPECTIVE_FEASIBILITY"
    elif primary is not None and primary <= 0 and ci[1] is not None and ci[1] <= 0:
        verdict = "UNPROMISING_RETROSPECTIVE_FEASIBILITY"
    else:
        verdict = "INCONCLUSIVE_RETROSPECTIVE_FEASIBILITY"

    receipt = {
        "schema": "AI_CORE_EVID_V2_8_12R_R2_OUTCOME_RESOLUTION_RECEIPT_V1",
        "version": "V2.8.12R",
        "status": "R2_OUTCOMES_RESOLVED" if resolved_share == 1.0 else "R2_OUTCOMES_PARTIALLY_UNAVAILABLE_NO_SHIFT",
        "authority": str(AUTH),
        "final_pre_outcome_cohort_sha256": sha_file(COHORT),
        "source": {
            "provider": "BaoStock", "package_version": "0.9.4",
            "stock_adjustflag": auth["source_and_vintage_contract"]["stock_adjustflag"],
            "benchmark_adjustflag": auth["source_and_vintage_contract"]["benchmark_adjustflag"],
            "query_range": {"start": start, "end": end},
            "stock_response_sha256_by_symbol": {k: v[1] for k, v in stock_cache.items()},
            "benchmark_response_sha256": bench_sha,
            "D_T_from_same_response": True,
        },
        "resolution": {
            "event_count": len(cohort), "resolved_events": len(resolved), "resolved_event_share": resolved_share,
            "unavailable": unavailable, "target_shift_used": False, "event_drop_used": False,
        },
        "analysis": {
            "primary_statistic_issuer_equal_weight_median_D10_excess": primary,
            "issuer_cluster_bootstrap_95pct_interval": ci,
            "bootstrap_resamples": 5000, "bootstrap_seed": 2812,
            "secondary_issuer_equal_weight_median_D5_excess": secondary_issuer_d5,
            "event_level_median_D10_excess": event_median_d10,
            "event_level_median_D5_excess": event_median_d5,
            "issuer_level_positive_D10_share": issuer_positive_share,
            "event_level_positive_D10_share": event_positive_share,
            "issuer_D10_medians": issuer_medians_d10,
            "issuer_D5_medians": issuer_medians_d5,
        },
        "sample_floor": {
            "frozen_positive_events": len(cohort), "distinct_issuers": distinct_issuers,
            "distinct_positive_quarters": distinct_quarters, "maximum_single_issuer_event_share": max_share,
            "resolved_event_share": resolved_share, "checks": floor_checks, "pass": sample_floor_pass,
        },
        "verdict": verdict,
        "maximum_claim": "RETROSPECTIVE_FEASIBILITY_ONLY",
        "prospective_gate_changed": False,
        "fold3_accessed": False,
        "fold4_accessed": False,
        "setup_or_live_accessed": False,
        "buy_sell_or_rebalance_instruction_generated": False,
        "results_file": str(OUT_CSV),
    }
    receipt["receipt_sha256"] = stable_sha(receipt)
    OUT_RECEIPT.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
