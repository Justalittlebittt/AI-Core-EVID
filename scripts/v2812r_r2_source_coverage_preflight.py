from __future__ import annotations

import csv
import hashlib
import json
from datetime import date
from pathlib import Path

import duckdb
import pandas as pd
from huggingface_hub import hf_hub_download

AMENDMENT = Path("evidence/V2.8.12R_RETROSPECTIVE_FEASIBILITY_CONTRACT_AMENDMENT_4.json")
TECH_GATE = Path("evidence/retrospective_feasibility/V2.8.12R_R1_TECHNICAL_GATE_RECEIPT.json")
FINAL_COHORT = Path("evidence/retrospective_feasibility/V2.8.12R_FINAL_PRE_OUTCOME_COHORT.csv")
FINAL_COHORT_RECEIPT = Path("evidence/retrospective_feasibility/V2.8.12R_FINAL_PRE_OUTCOME_COHORT_RECEIPT.json")
CALENDAR = Path("evidence/V2.8.5_JOINT_A_SHARE_TRADING_CALENDAR_2023_2024.json")
OUT = Path("evidence/retrospective_feasibility/V2.8.12R_R2_SOURCE_COVERAGE_PREFLIGHT_RECEIPT.json")


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def stable_sha(obj) -> str:
    return hashlib.sha256(json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def sql_lit(v: str | Path) -> str:
    return "'" + str(v).replace("'", "''") + "'"


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
    try:
        i = days.index(d)
    except ValueError as e:
        raise RuntimeError(f"EVENT_D_NOT_IN_FROZEN_CALENDAR:{d}") from e
    j = i + n
    if j >= len(days):
        raise RuntimeError(f"TARGET_OUTSIDE_FROZEN_CALENDAR:{d}:D+{n}")
    return days[j]


def alpha_symbol(canonical_security_id: str) -> str:
    ex, code = canonical_security_id.split(":", 1)
    if ex == "SSE" and len(code) == 6 and code.isdigit():
        return f"{code}.SS"
    if ex == "SZSE" and len(code) == 6 and code.isdigit():
        return f"{code}.SZ"
    raise RuntimeError(f"UNSUPPORTED_CANONICAL_SECURITY_ID:{canonical_security_id}")


def load_cohort() -> list[dict]:
    return list(csv.DictReader(FINAL_COHORT.read_text(encoding="utf-8").splitlines()))


def verify_authorization() -> tuple[dict, dict, dict]:
    a = read_json(AMENDMENT)
    t = read_json(TECH_GATE)
    c = read_json(FINAL_COHORT_RECEIPT)
    if a.get("status") != "ACTIVE_PRE_OUTCOME_SOURCE_COVERAGE_PREFLIGHT":
        raise RuntimeError("COVERAGE_AMENDMENT_NOT_ACTIVE")
    if t.get("status") != "R1_COHORT_TECHNICALLY_COMPLETE" or t.get("R2_price_or_return_access_authorized") is not True:
        raise RuntimeError("R1_TECHNICAL_GATE_NOT_PASS")
    if c.get("status") != "PASS_FINAL_PRE_OUTCOME_COHORT_FROZEN":
        raise RuntimeError("FINAL_PRE_OUTCOME_COHORT_NOT_FROZEN")
    if c.get("price_or_return_data_consumed") is not False:
        raise RuntimeError("PREOUTCOME_PRICE_FIREWALL_BROKEN")
    if c.get("final_cohort_sha256") != sha_file(FINAL_COHORT):
        raise RuntimeError("FINAL_COHORT_HASH_DRIFT")
    allowed = set(a["authorization_boundary"]["allowed_columns_from_stock_source"])
    if allowed != {"symbol", "bar_time", "kline_t"}:
        raise RuntimeError("STOCK_ALLOWED_COLUMN_CONTRACT_DRIFT")
    if set(a["authorization_boundary"]["allowed_columns_from_benchmark_source"]) != allowed:
        raise RuntimeError("BENCH_ALLOWED_COLUMN_CONTRACT_DRIFT")
    return a, t, c


def materialize_exact(source: dict) -> Path:
    p = Path(hf_hub_download(
        repo_id=source["repo_id"],
        filename=source["target_file"],
        repo_type="dataset",
        revision=source["revision_sha"],
    ))
    actual = sha_file(p)
    if actual != source["target_lfs_sha256"]:
        raise RuntimeError(f"SOURCE_SHA_MISMATCH:{source['repo_id']}:{actual}")
    return p


def presence_rows(parquet: Path, expected: pd.DataFrame, benchmark: bool = False) -> pd.DataFrame:
    con = duckdb.connect()
    con.register("expected", expected)
    # Deliberately project only the columns authorized by Amendment 4.
    if benchmark:
        q = f"""
        WITH source_presence AS (
          SELECT DISTINCT cast(symbol as varchar) AS symbol,
                          cast(bar_time as date) AS bar_date
          FROM read_parquet({sql_lit(parquet)}, columns={{'symbol':'VARCHAR','bar_time':'TIMESTAMP','kline_t':'VARCHAR'}})
          WHERE cast(kline_t as varchar)='1D'
            AND cast(symbol as varchar)='000300.SS'
        )
        SELECT e.event_key, e.required_label, e.required_date,
               CASE WHEN s.bar_date IS NULL THEN false ELSE true END AS present
        FROM expected e
        LEFT JOIN source_presence s
          ON s.symbol=e.symbol AND s.bar_date=cast(e.required_date as date)
        ORDER BY e.event_key, e.required_label
        """
    else:
        q = f"""
        WITH source_presence AS (
          SELECT DISTINCT cast(symbol as varchar) AS symbol,
                          cast(bar_time as date) AS bar_date
          FROM read_parquet({sql_lit(parquet)}, columns={{'symbol':'VARCHAR','bar_time':'TIMESTAMP','kline_t':'VARCHAR'}})
          WHERE cast(kline_t as varchar)='1D'
        )
        SELECT e.event_key, e.symbol, e.required_label, e.required_date,
               CASE WHEN s.bar_date IS NULL THEN false ELSE true END AS present
        FROM expected e
        LEFT JOIN source_presence s
          ON s.symbol=e.symbol AND s.bar_date=cast(e.required_date as date)
        ORDER BY e.event_key, e.required_label
        """
    out = con.execute(q).df()
    con.close()
    return out


def minmax_dates(parquet: Path, symbol_filter: list[str]) -> dict[str, str | None]:
    con = duckdb.connect()
    con.register("wanted", pd.DataFrame({"symbol": symbol_filter}))
    q = f"""
      SELECT min(cast(k.bar_time as date)) AS min_date,
             max(cast(k.bar_time as date)) AS max_date
      FROM read_parquet({sql_lit(parquet)}, columns={{'symbol':'VARCHAR','bar_time':'TIMESTAMP','kline_t':'VARCHAR'}}) k
      INNER JOIN wanted w ON cast(k.symbol as varchar)=w.symbol
      WHERE cast(k.kline_t as varchar)='1D'
    """
    lo, hi = con.execute(q).fetchone()
    con.close()
    return {"min_date": lo.isoformat() if lo else None, "max_date": hi.isoformat() if hi else None}


def main() -> None:
    a, tech, cohort_receipt = verify_authorization()
    days = load_calendar()
    cohort = load_cohort()
    expected_stock = []
    expected_bench = []
    for r in cohort:
        aid = str(r["announcement_id"])
        cid = str(r["canonical_security_id"])
        d = str(r["retrospective_causal_effective_date"])
        sym = alpha_symbol(cid)
        dates = {"D": d, "D+5": target(days, d, 5), "D+10": target(days, d, 10)}
        for label, rd in dates.items():
            expected_stock.append({"event_key": aid, "canonical_security_id": cid, "symbol": sym, "required_label": label, "required_date": rd})
            expected_bench.append({"event_key": aid, "symbol": "000300.SS", "required_label": label, "required_date": rd})
    es = pd.DataFrame(expected_stock)
    eb = pd.DataFrame(expected_bench)

    stock_cfg = a["frozen_source_identity"]["stock"]
    bench_cfg = a["frozen_source_identity"]["benchmark"]
    stock_path = materialize_exact(stock_cfg)
    bench_path = materialize_exact(bench_cfg)

    sp = presence_rows(stock_path, es, benchmark=False)
    bp = presence_rows(bench_path, eb, benchmark=True)
    stock_present = int(sp["present"].sum())
    bench_present = int(bp["present"].sum())
    stock_required = len(sp)
    bench_required = len(bp)
    stock_rate = stock_present / stock_required if stock_required else 1.0
    bench_rate = bench_present / bench_required if bench_required else 1.0
    stock_pass = stock_rate == 1.0
    bench_pass = bench_rate == 1.0
    passed = stock_pass and bench_pass

    missing_stock = [
        {"event_key": str(x.event_key), "symbol": str(x.symbol), "required_label": str(x.required_label), "required_date": str(x.required_date)}
        for x in sp.loc[~sp["present"]].itertuples(index=False)
    ]
    missing_bench = [
        {"event_key": str(x.event_key), "required_label": str(x.required_label), "required_date": str(x.required_date)}
        for x in bp.loc[~bp["present"]].itertuples(index=False)
    ]
    wanted_symbols = sorted(es["symbol"].unique().tolist())

    out = {
        "schema": "AI_CORE_EVID_V2_8_12R_R2_SOURCE_COVERAGE_PREFLIGHT_RECEIPT_V1",
        "version": "V2.8.12R",
        "status": "PRIMARY_SOURCE_COVERAGE_PASS_R2_OUTCOME_RESOLUTION_MAY_BE_SEPARATELY_AUTHORIZED" if passed else "PRIMARY_SOURCE_COVERAGE_FAIL_FALLBACK_AMENDMENT_REQUIRED",
        "authority": str(AMENDMENT),
        "final_pre_outcome_cohort": str(FINAL_COHORT),
        "final_pre_outcome_cohort_sha256": cohort_receipt["final_cohort_sha256"],
        "event_count": len(cohort),
        "required_dates_per_event": ["D", "D+5", "D+10"],
        "stock_required_event_date_rows": stock_required,
        "stock_present_event_date_rows": stock_present,
        "stock_coverage_rate": stock_rate,
        "benchmark_required_event_date_rows": bench_required,
        "benchmark_present_event_date_rows": bench_present,
        "benchmark_coverage_rate": bench_rate,
        "missing_stock_event_dates": missing_stock,
        "missing_benchmark_event_dates": missing_bench,
        "stock_source_date_extent_for_cohort_symbols": minmax_dates(stock_path, wanted_symbols),
        "benchmark_source_date_extent": minmax_dates(bench_path, ["000300.SS"]),
        "source_identity_sha256": a["frozen_source_identity"]["source_identity_sha256"],
        "stock_revision_sha": stock_cfg["revision_sha"],
        "stock_lfs_sha256_verified": stock_cfg["target_lfs_sha256"],
        "benchmark_revision_sha": bench_cfg["revision_sha"],
        "benchmark_lfs_sha256_verified": bench_cfg["target_lfs_sha256"],
        "source_container_materialized": True,
        "projected_source_columns": ["symbol", "bar_time", "kline_t"],
        "numeric_price_columns_read": False,
        "price_values_logged": False,
        "returns_computed": False,
        "retrospective_event_cohort_changed": False,
        "prospective_gate_changed": False,
        "fold3_accessed": False,
        "fold4_accessed": False,
        "outcome_resolution_authorized_by_preflight_itself": False,
        "next_stage": "FREEZE_R2_OUTCOME_RESOLUTION_AUTHORIZATION_USING_EXISTING_CONTRACT" if passed else "FREEZE_SEPARATE_FREE_PUBLIC_FALLBACK_SOURCE_AMENDMENT_BEFORE_ANY_OUTCOME_ACCESS"
    }
    out["receipt_sha256"] = stable_sha(out)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
