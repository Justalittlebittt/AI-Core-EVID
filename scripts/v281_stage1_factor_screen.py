from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import re
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

import duckdb
import numpy as np
import pandas as pd
from huggingface_hub import hf_hub_download

sys.path.insert(0, str(Path(__file__).resolve().parent))
from v280_scale_invariant_features import build_features

OUT = Path("v281_stage1")
OUT.mkdir(exist_ok=True)

KLINE_REPO = "AlphaDojo/dojo_stock_kline"
KLINE_REV = "c009ad58278161e7b6eb347b68f34f51166114f3"
KLINE_SHA = "acb8ae5e31f58fe3972455b86614d668837f18afd59126c505faaae06920954b"
BENCH_REPO = "AlphaDojo/dojo_benchmark_kline"
BENCH_REV = "4cc8300a0f82cc9db76b946b80ae5b28a7beca95"
BENCH_SHA = "75c4fba2de6875e125c539187fdf7e44eae90d740fce64907f8ce8df6ff58234"

PIT_PATH = Path("evidence/V2.8.1_PIT_MEMBERSHIP_INTERVALS.csv")
PIT_SHA = "52087fa1e68577fae214f8fa18f1b20a0b30f41b6b6bf5592327c25c2800cfc1"
STABLE_PATH = Path("evidence/V2.8.1_VENDOR_VINTAGE_SYMBOL_AUDIT.csv")
VINTAGE_RECEIPT = Path("evidence/V2.8.1_VENDOR_VINTAGE_DRIFT_RECEIPT.json")
VINTAGE_RECEIPT_SHA = "2e01b0f875a31812ba08351379846b94abb28ed02f5ba4eec553ae251aa27894"
CAL2025 = Path("evidence/V2.8.1_JOINT_A_SHARE_CALENDAR_2025_CONTRACT.json")
CAL2026 = Path("evidence/V2.7.32_JOINT_A_SHARE_TRADING_CALENDAR_2026.json")
SNAPSHOT_CONTRACT = Path("evidence/V2.8.1_CANONICAL_RESEARCH_SNAPSHOT_CONTRACT.json")
EXEC_CONTRACT = Path("evidence/V2.8.1_STAGE1_EXECUTION_CONTRACT.json")
PROMOTION_RULE = Path("evidence/V2.8.1_STAGE1_FACTOR_PROMOTION_RULE.json")
STATS_RULE = Path("evidence/V2.8.1_STAGE1_STATISTICAL_MECHANICS_AMENDMENT.json")

MAX_SIGNAL_DATE = date(2026, 9, 9)
BASE_SEED = 2801001
BOOT_B = 10000
BLOCK_LEN = 20
MIN_VALID_DATES = 200
MIN_VALID_QUARTERS = 4
VALID_QUARTER_MIN_DATES = 20
MIN_VALID_DATE_SHARE = 0.80
MIN_MEDIAN_COVERAGE = 0.70
VALID_DATE_COVERAGE = 0.70

FACTOR_META = [
    ("ret_20", +1, 0),
    ("ret_60", +1, 1),
    ("ma50_vs_ma150", +1, 2),
    ("ma150_vs_ma200", +1, 3),
    ("ma200_slope20", +1, 4),
    ("dist_high60", +1, 5),
    ("dist_high252", +1, 6),
    ("rv10_over_rv60", -1, 7),
    ("tr10_over_tr60", -1, 8),
]
FACTORS = [x[0] for x in FACTOR_META]
PANEL_COLS = ["canonical_security_id", "signal_date", *FACTORS, "fwd_5", "fwd_10"]
SYMBOL_RE = re.compile(r"^(\d{6})\.(SS|SZ)$")


def sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda: f.read(1024 * 1024), b""):
            h.update(b)
    return h.hexdigest()


def sha_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def stable_json_sha(obj) -> str:
    b = json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return sha_bytes(b)


def require_sha(path: Path, expected: str, label: str) -> None:
    actual = sha_file(path)
    if actual != expected:
        raise RuntimeError(f"{label} SHA mismatch: {actual} != {expected}")


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sql_lit(v) -> str:
    return "'" + str(v).replace("'", "''") + "'"


def build_joint_calendar() -> list[date]:
    c25 = read_json(CAL2025)
    closed: set[date] = set()
    for r in c25["closure_ranges"]:
        d0 = date.fromisoformat(r["start"])
        d1 = date.fromisoformat(r["end"])
        d = d0
        while d <= d1:
            closed.add(d)
            d += timedelta(days=1)
    for x in c25.get("explicit_weekend_closures", []):
        closed.add(date.fromisoformat(x))

    dates25 = []
    d = date(2025, 1, 1)
    while d <= date(2025, 12, 31):
        if d.weekday() < 5 and d not in closed:
            dates25.append(d)
        d += timedelta(days=1)

    c26 = read_json(CAL2026)
    dates26 = [
        date.fromisoformat(x["date"])
        for x in c26["dates"]
        if x["is_joint_a_share_trading_day"]
    ]
    cal = sorted(set(dates25 + dates26))
    if not cal or cal[0] != date(2025, 1, 2):
        raise RuntimeError(f"calendar unexpected first date: {cal[:3]}")
    if len(cal) != len(dates25) + len(dates26):
        raise RuntimeError("calendar overlap/duplicate failure")
    return cal


def target_map(calendar: list[date], n: int) -> dict[date, date]:
    return {
        calendar[i]: calendar[i + n]
        for i in range(0, len(calendar) - n)
    }


def load_intervals() -> pd.DataFrame:
    require_sha(PIT_PATH, PIT_SHA, "PIT membership intervals")
    x = pd.read_csv(PIT_PATH, dtype=str).fillna("")
    required = {
        "canonical_security_id", "exchange", "security_code",
        "official_list_date", "official_delist_date"
    }
    if not required.issubset(x.columns):
        raise RuntimeError(f"PIT interval columns missing: {required - set(x.columns)}")
    if x["canonical_security_id"].duplicated().any():
        dup = x.loc[x["canonical_security_id"].duplicated(False), "canonical_security_id"].head(20).tolist()
        raise RuntimeError(f"duplicate canonical interval identity: {dup}")
    counts = x.groupby("security_code")["canonical_security_id"].nunique()
    bad = counts[counts != 1]
    if len(bad):
        raise RuntimeError(f"security_code is not unique in official interval ledger: {bad.head(20).to_dict()}")
    x["list_date"] = pd.to_datetime(x["official_list_date"], errors="raise").dt.date
    x["delist_date"] = pd.to_datetime(
        x["official_delist_date"].replace("", pd.NA), errors="coerce"
    ).dt.date
    return x


def load_stable_symbols(intervals: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, str]]:
    require_sha(VINTAGE_RECEIPT, VINTAGE_RECEIPT_SHA, "vintage drift receipt")
    receipt = read_json(VINTAGE_RECEIPT)
    if receipt["gate"]["status"] != "VINTAGE_SCALE_INVARIANCE_PASS":
        raise RuntimeError("vintage drift gate is not PASS")
    stable_audit = pd.read_csv(STABLE_PATH)
    stable = stable_audit[
        stable_audit["comparable"].astype(str).str.lower().eq("true")
        & stable_audit["price_stable"].astype(str).str.lower().eq("true")
    ].copy()
    if len(stable) != 5214:
        raise RuntimeError(f"expected 5214 stable symbols, got {len(stable)}")

    code_to_row = intervals.set_index("security_code")
    symbol_to_cid: dict[str, str] = {}
    bad = []
    for sym in stable["symbol"].astype(str):
        m = SYMBOL_RE.fullmatch(sym)
        if not m:
            bad.append((sym, "FORMAT"))
            continue
        code, suffix = m.groups()
        if code not in code_to_row.index:
            bad.append((sym, "NO_OFFICIAL_CODE"))
            continue
        row = code_to_row.loc[code]
        if isinstance(row, pd.DataFrame):
            bad.append((sym, "AMBIGUOUS_CODE"))
            continue
        expected_exchange = "SSE" if suffix == "SS" else "SZSE"
        if row["exchange"] != expected_exchange:
            bad.append((sym, f"SUFFIX_CROSSCHECK_{row['exchange']}"))
            continue
        symbol_to_cid[sym] = row["canonical_security_id"]
    if bad:
        raise RuntimeError(f"stable symbol mapping blocked: {bad[:30]}")
    if len(symbol_to_cid) != 5214:
        raise RuntimeError("stable symbol mapping cardinality mismatch")
    return stable, symbol_to_cid


def download_sources() -> tuple[Path, Path]:
    kline = Path(hf_hub_download(
        KLINE_REPO, "data.parquet", repo_type="dataset", revision=KLINE_REV
    ))
    bench = Path(hf_hub_download(
        BENCH_REPO, "data.parquet", repo_type="dataset", revision=BENCH_REV
    ))
    require_sha(kline, KLINE_SHA, "pinned stock kline")
    require_sha(bench, BENCH_SHA, "pinned benchmark kline")
    return kline, bench


def load_price_panel(
    kline: Path,
    stable_symbols: list[str],
    symbol_to_cid: dict[str, str],
    intervals: pd.DataFrame,
) -> tuple[pd.DataFrame, date, dict]:
    con = duckdb.connect()
    con.execute("PRAGMA threads=4")
    con.execute("PRAGMA memory_limit='5GB'")
    symbols_df = pd.DataFrame({"symbol": stable_symbols})
    con.register("stable_symbols", symbols_df)
    query = f"""
      SELECT cast(k.symbol as varchar) symbol,
             cast(k.bar_time as date) bar_date,
             cast(k.open as double) open,
             cast(k.high as double) high,
             cast(k.low as double) low,
             cast(k.close as double) close,
             cast(k.amount as double) amount
      FROM read_parquet({sql_lit(kline)}) k
      INNER JOIN stable_symbols s
        ON cast(k.symbol as varchar)=s.symbol
      WHERE cast(k.kline_t as varchar)='1D'
        AND cast(k.bar_time as date) <= DATE '2026-09-18'
      ORDER BY symbol, bar_date
    """
    px = con.execute(query).fetchdf()
    con.close()

    if px.empty:
        raise RuntimeError("stock kline filtered panel is empty")
    if px.duplicated(["symbol", "bar_date"]).any():
        raise RuntimeError("duplicate symbol/bar_date keys in pinned stock kline")
    px["canonical_security_id"] = px["symbol"].map(symbol_to_cid)
    if px["canonical_security_id"].isna().any():
        raise RuntimeError("unmapped stable symbol present after preflight")

    interval = intervals.set_index("canonical_security_id")[["list_date", "delist_date"]]
    px = px.join(interval, on="canonical_security_id", how="left")
    if px["list_date"].isna().any():
        raise RuntimeError("mapped kline row missing official membership interval")

    px["bar_date"] = pd.to_datetime(px["bar_date"]).dt.date
    active = (px["bar_date"] >= px["list_date"]) & (
        px["delist_date"].isna() | (px["bar_date"] < px["delist_date"])
    )
    before = len(px)
    px = px.loc[active, [
        "canonical_security_id", "symbol", "bar_date",
        "open", "high", "low", "close", "amount"
    ]].copy()
    source_max = max(px["bar_date"])
    diag = {
        "stable_vendor_symbols": len(stable_symbols),
        "filtered_kline_rows_before_pit": int(before),
        "pit_eligible_kline_rows": int(len(px)),
        "mapped_canonical_ids": int(px["canonical_security_id"].nunique()),
        "source_min_bar_date": str(min(px["bar_date"])),
        "source_max_bar_date": str(source_max),
    }
    return px, source_max, diag


def build_outcomes(
    features: pd.DataFrame,
    calendar: list[date],
    source_max: date,
) -> pd.DataFrame:
    t5 = target_map(calendar, 5)
    t10 = target_map(calendar, 10)

    x = features.copy()
    x["signal_date"] = pd.to_datetime(x["bar_date"]).dt.date
    x["target_5"] = x["signal_date"].map(t5)
    x["target_10"] = x["signal_date"].map(t10)

    close_lookup = x[["canonical_security_id", "signal_date", "close"]].rename(
        columns={"signal_date": "target_date", "close": "target_close"}
    )
    if close_lookup.duplicated(["canonical_security_id", "target_date"]).any():
        raise RuntimeError("duplicate close lookup keys")

    x = x.merge(
        close_lookup.rename(columns={"target_date": "target_5", "target_close": "close_t5"}),
        on=["canonical_security_id", "target_5"],
        how="left",
        validate="many_to_one",
    )
    x = x.merge(
        close_lookup.rename(columns={"target_date": "target_10", "target_close": "close_t10"}),
        on=["canonical_security_id", "target_10"],
        how="left",
        validate="many_to_one",
    )
    x.loc[x["target_5"].isna() | (x["target_5"] > source_max), "close_t5"] = np.nan
    x.loc[x["target_10"].isna() | (x["target_10"] > source_max), "close_t10"] = np.nan
    x["fwd_5"] = x["close_t5"] / x["close"] - 1.0
    x["fwd_10"] = x["close_t10"] / x["close"] - 1.0
    return x


def universe_count_by_date(intervals: pd.DataFrame, calendar: list[date]) -> dict[date, int]:
    out = {}
    for d in calendar:
        mask = (intervals["list_date"] <= d) & (
            intervals["delist_date"].isna() | (intervals["delist_date"] > d)
        )
        out[d] = int(mask.sum())
    return out


def load_benchmark_returns(
    bench_path: Path,
    calendar: list[date],
    source_max: date,
) -> dict[date, float]:
    con = duckdb.connect()
    q = f"""
      SELECT cast(bar_time as date) bar_date, cast(close as double) close
      FROM read_parquet({sql_lit(bench_path)})
      WHERE cast(symbol as varchar)='000300.SS'
        AND cast(kline_t as varchar)='1D'
      ORDER BY bar_date
    """
    b = con.execute(q).fetchdf()
    con.close()
    if b.empty:
        raise RuntimeError("CSI300 benchmark 000300.SS not found")
    b["bar_date"] = pd.to_datetime(b["bar_date"]).dt.date
    if b.duplicated("bar_date").any():
        raise RuntimeError("duplicate CSI300 bar date")
    close = dict(zip(b["bar_date"], b["close"].astype(float)))
    t10 = target_map(calendar, 10)
    out = {}
    for d, t in t10.items():
        if t <= source_max and d in close and t in close:
            out[d] = close[t] / close[d] - 1.0
    return out


def avg_rank_corr(a: pd.Series, b: pd.Series) -> float:
    z = pd.DataFrame({"a": a, "b": b}).dropna()
    if len(z) < 2:
        return np.nan
    ra = z["a"].rank(method="average")
    rb = z["b"].rank(method="average")
    if ra.nunique() < 2 or rb.nunique() < 2:
        return np.nan
    return float(ra.corr(rb, method="pearson"))


def quantile_metrics(g: pd.DataFrame, factor: str) -> tuple[float, dict[int, float], int]:
    z = g[[factor, "fwd_10"]].dropna().copy()
    if len(z) < 5 or z[factor].nunique() < 2:
        return np.nan, {}, len(z)
    pct = z[factor].rank(method="average", pct=True)
    q = np.ceil(pct * 5.0).clip(1, 5).astype(int)
    means = z.assign(q=q).groupby("q")["fwd_10"].mean().to_dict()
    if 1 not in means or 5 not in means:
        return np.nan, means, len(z)
    return float(means[5] - means[1]), {int(k): float(v) for k, v in means.items()}, len(z)


def bootstrap_mean(series: np.ndarray, seed: int) -> tuple[float, float, float]:
    y = np.asarray(series, dtype=float)
    y = y[np.isfinite(y)]
    n = len(y)
    if n < 2:
        return np.nan, np.nan, np.nan
    rng = np.random.default_rng(seed)
    blocks = math.ceil(n / BLOCK_LEN)
    starts = rng.integers(0, n, size=(BOOT_B, blocks), endpoint=False)
    offsets = np.arange(BLOCK_LEN, dtype=np.int64)
    idx = (starts[:, :, None] + offsets[None, None, :]) % n
    idx = idx.reshape(BOOT_B, -1)[:, :n]
    means = y[idx].mean(axis=1)
    lo, hi = np.quantile(means, [0.025, 0.975])
    return float(y.mean()), float(lo), float(hi)


def bootstrap_ic_with_null(series: np.ndarray, seed: int) -> tuple[float, float, float, float]:
    y = np.asarray(series, dtype=float)
    y = y[np.isfinite(y)]
    n = len(y)
    if n < 2:
        return np.nan, np.nan, np.nan, 1.0
    observed = float(y.mean())
    rng = np.random.default_rng(seed)
    blocks = math.ceil(n / BLOCK_LEN)
    starts = rng.integers(0, n, size=(BOOT_B, blocks), endpoint=False)
    offsets = np.arange(BLOCK_LEN, dtype=np.int64)
    idx = (starts[:, :, None] + offsets[None, None, :]) % n
    idx = idx.reshape(BOOT_B, -1)[:, :n]
    means = y[idx].mean(axis=1)
    lo, hi = np.quantile(means, [0.025, 0.975])
    centered = y - observed
    null_means = centered[idx].mean(axis=1)
    p = (1.0 + float(np.sum(null_means >= observed))) / (BOOT_B + 1.0)
    return observed, float(lo), float(hi), float(p)


def holm_pass(pvals: dict[str, float], alpha: float = 0.05) -> dict[str, bool]:
    ordered = sorted(pvals.items(), key=lambda kv: (kv[1], kv[0]))
    result = {k: False for k in pvals}
    m = len(ordered)
    still = True
    for i, (factor, p) in enumerate(ordered):
        threshold = alpha / (m - i)
        if still and np.isfinite(p) and p <= threshold:
            result[factor] = True
        else:
            still = False
            result[factor] = False
    return result


def panel_sha(panel: pd.DataFrame) -> tuple[str, Path]:
    path = OUT / "V2.8.1_CANONICAL_RESEARCH_PANEL.parquet"
    p = panel[PANEL_COLS].copy()
    p["signal_date"] = pd.to_datetime(p["signal_date"])
    p = p.sort_values(["canonical_security_id", "signal_date"], kind="mergesort").reset_index(drop=True)
    p.to_parquet(path, engine="pyarrow", compression="zstd", index=False)
    return sha_file(path), path


def main() -> None:
    started = datetime.now(timezone.utc)

    # Freeze-authority integrity checks.
    require_sha(VINTAGE_RECEIPT, VINTAGE_RECEIPT_SHA, "vintage receipt")
    snapshot_contract = read_json(SNAPSHOT_CONTRACT)
    exec_contract = read_json(EXEC_CONTRACT)
    promotion = read_json(PROMOTION_RULE)
    stats = read_json(STATS_RULE)
    if not snapshot_contract.get("frozen_before_stage1_results"):
        raise RuntimeError("snapshot contract not frozen before results")
    if not exec_contract.get("frozen_before_stage1_results"):
        raise RuntimeError("execution contract not frozen before results")
    if promotion.get("status") != "PREREGISTERED_BEFORE_NEW_FACTOR_RESULTS":
        raise RuntimeError("promotion rule not preregistered")
    if not stats.get("frozen_before_factor_results"):
        raise RuntimeError("statistical mechanics not frozen")

    intervals = load_intervals()
    stable, symbol_to_cid = load_stable_symbols(intervals)
    calendar = build_joint_calendar()
    kline, bench = download_sources()
    px, source_max, source_diag = load_price_panel(
        kline, stable["symbol"].astype(str).tolist(), symbol_to_cid, intervals
    )
    if source_max != date(2026, 9, 18):
        raise RuntimeError(f"unexpected pinned source max bar date {source_max}")

    print(f"PRICE_PANEL rows={len(px)} cids={px['canonical_security_id'].nunique()} source_max={source_max}", flush=True)

    feat_input = px[["canonical_security_id", "bar_date", "open", "high", "low", "close", "amount"]]
    features = build_features(feat_input)
    panel_all = build_outcomes(features, calendar, source_max)

    # Only preregistered signal-date horizon; retain future source rows only for T endpoint lookup.
    signal = panel_all[panel_all["signal_date"] <= MAX_SIGNAL_DATE].copy()
    universe_counts = universe_count_by_date(intervals, calendar)
    csi10 = load_benchmark_returns(bench, calendar, source_max)

    # Canonical panel identity includes all stable/PIT-eligible signal rows through max D.
    panel = signal[PANEL_COLS].copy()
    psha, panel_path = panel_sha(panel)

    daily_rows: list[dict] = []
    quantile_rows: list[dict] = []
    preliminary: dict[str, dict] = {}

    t10_map = target_map(calendar, 10)
    calendar_set = set(calendar)
    last_primary_available_dates = [
        d for d in calendar
        if d <= MAX_SIGNAL_DATE and d in t10_map and t10_map[d] <= source_max
    ]
    if not last_primary_available_dates:
        raise RuntimeError("no primary-outcome-available dates")
    global_last_eval = max(last_primary_available_dates)

    for factor, direction, offset in FACTOR_META:
        finite_by_date = signal.loc[np.isfinite(pd.to_numeric(signal[factor], errors="coerce"))].groupby(
            "signal_date"
        ).size()
        warm_candidates = sorted(d for d in finite_by_date.index if d in calendar_set and d <= global_last_eval)
        warmup = warm_candidates[0] if warm_candidates else None
        if warmup is None:
            eligible_dates: list[date] = []
        else:
            eligible_dates = [
                d for d in calendar
                if warmup <= d <= global_last_eval
            ]

        factor_daily = []
        for d in eligible_dates:
            g = signal[signal["signal_date"] == d]
            uc = universe_counts.get(d, 0)
            finite_factor = np.isfinite(pd.to_numeric(g[factor], errors="coerce")).sum()
            coverage = (finite_factor / uc) if uc else 0.0
            ic10 = avg_rank_corr(g[factor], g["fwd_10"])
            ic5 = avg_rank_corr(g[factor], g["fwd_5"])
            raw_spread, qmeans, qn = quantile_metrics(g, factor)
            broad10 = float(g["fwd_10"].mean()) if g["fwd_10"].notna().any() else np.nan
            csi = csi10.get(d, np.nan)
            valid = bool(coverage >= VALID_DATE_COVERAGE and np.isfinite(ic10))
            rec = {
                "factor": factor,
                "direction": "POSITIVE" if direction > 0 else "NEGATIVE",
                "signal_date": d.isoformat(),
                "official_universe_count": int(uc),
                "factor_finite_count": int(finite_factor),
                "factor_coverage": float(coverage),
                "rank_ic_d10": ic10,
                "rank_ic_d5": ic5,
                "direction_adjusted_ic_d10": direction * ic10 if np.isfinite(ic10) else np.nan,
                "direction_adjusted_ic_d5": direction * ic5 if np.isfinite(ic5) else np.nan,
                "raw_q5_minus_q1_d10": raw_spread,
                "direction_adjusted_spread_d10": direction * raw_spread if np.isfinite(raw_spread) else np.nan,
                "broad_a_ew_d10": broad10,
                "csi300_d10": csi,
                "valid_evaluation_date": valid,
            }
            daily_rows.append(rec)
            factor_daily.append(rec)

            for q in range(1, 6):
                quantile_rows.append({
                    "factor": factor,
                    "direction": "POSITIVE" if direction > 0 else "NEGATIVE",
                    "signal_date": d.isoformat(),
                    "quintile": q,
                    "mean_d10_return": qmeans.get(q, np.nan),
                    "rows_in_factor_return_cross_section": int(qn),
                    "broad_a_ew_d10": broad10,
                    "csi300_d10": csi,
                })

        fd = pd.DataFrame(factor_daily)
        valid_fd = fd[fd["valid_evaluation_date"]].copy() if len(fd) else pd.DataFrame()
        valid_dates = len(valid_fd)
        eligible_count = len(eligible_dates)
        valid_share = valid_dates / eligible_count if eligible_count else 0.0
        median_cov = float(fd["factor_coverage"].median()) if len(fd) else 0.0

        if valid_dates:
            dir_ic10 = valid_fd["direction_adjusted_ic_d10"].to_numpy(float)
            dir_spread = valid_fd["direction_adjusted_spread_d10"].dropna().to_numpy(float)
            dir_ic5 = valid_fd["direction_adjusted_ic_d5"].dropna().to_numpy(float)
            ic_mean, ic_lo, ic_hi, p_one = bootstrap_ic_with_null(dir_ic10, BASE_SEED + offset)
            sp_mean, sp_lo, sp_hi = bootstrap_mean(dir_spread, BASE_SEED + 1000 + offset)
            d5_mean = float(np.mean(dir_ic5)) if len(dir_ic5) else np.nan
            valid_fd["quarter"] = pd.to_datetime(valid_fd["signal_date"]).dt.to_period("Q").astype(str)
            qstats = valid_fd.groupby("quarter").agg(
                dates=("signal_date", "count"),
                mean_dir_ic10=("direction_adjusted_ic_d10", "mean")
            ).reset_index()
            valid_q = qstats[qstats["dates"] >= VALID_QUARTER_MIN_DATES].copy()
            quarter_count = len(valid_q)
            quarter_positive_share = (
                float((valid_q["mean_dir_ic10"] > 0).mean()) if quarter_count else 0.0
            )
            loo_positive = True if quarter_count else False
            loo_values = {}
            for q in valid_q["quarter"]:
                remain = valid_fd[valid_fd["quarter"] != q]["direction_adjusted_ic_d10"].dropna()
                m = float(remain.mean()) if len(remain) else np.nan
                loo_values[q] = m
                if not np.isfinite(m) or m <= 0:
                    loo_positive = False
        else:
            ic_mean = ic_lo = ic_hi = np.nan
            p_one = 1.0
            sp_mean = sp_lo = sp_hi = np.nan
            d5_mean = np.nan
            quarter_count = 0
            quarter_positive_share = 0.0
            loo_positive = False
            loo_values = {}

        preliminary[factor] = {
            "factor": factor,
            "direction": "POSITIVE" if direction > 0 else "NEGATIVE",
            "warmup_start": warmup.isoformat() if warmup else "",
            "last_eligible_date": global_last_eval.isoformat(),
            "eligible_dates": eligible_count,
            "valid_dates": valid_dates,
            "valid_date_share": valid_share,
            "median_factor_coverage": median_cov,
            "valid_quarters": quarter_count,
            "mean_direction_adjusted_ic_d10": ic_mean,
            "ic_d10_ci_low": ic_lo,
            "ic_d10_ci_high": ic_hi,
            "ic_d10_one_sided_p": p_one,
            "mean_direction_adjusted_spread_d10": sp_mean,
            "spread_d10_ci_low": sp_lo,
            "spread_d10_ci_high": sp_hi,
            "mean_direction_adjusted_ic_d5": d5_mean,
            "positive_valid_quarter_share": quarter_positive_share,
            "leave_one_valid_quarter_out_all_positive": loo_positive,
            "leave_one_valid_quarter_out_means": loo_values,
        }

    pvals = {
        f: (float(preliminary[f]["ic_d10_one_sided_p"])
            if np.isfinite(preliminary[f]["ic_d10_one_sided_p"]) else 1.0)
        for f in FACTORS
    }
    holm = holm_pass(pvals)

    ledger = []
    promoted = []
    for factor, direction, offset in FACTOR_META:
        r = preliminary[factor]
        gates = {
            "valid_date_share_ge_80pct": r["valid_date_share"] >= MIN_VALID_DATE_SHARE,
            "median_coverage_ge_70pct": r["median_factor_coverage"] >= MIN_MEDIAN_COVERAGE,
            "valid_dates_ge_200": r["valid_dates"] >= MIN_VALID_DATES,
            "valid_quarters_ge_4": r["valid_quarters"] >= MIN_VALID_QUARTERS,
            "mean_d10_ic_direction_positive": np.isfinite(r["mean_direction_adjusted_ic_d10"]) and r["mean_direction_adjusted_ic_d10"] > 0,
            "d10_ic_ci_excludes_zero": np.isfinite(r["ic_d10_ci_low"]) and r["ic_d10_ci_low"] > 0,
            "holm_bonferroni_pass": bool(holm[factor]),
            "mean_d10_spread_direction_positive": np.isfinite(r["mean_direction_adjusted_spread_d10"]) and r["mean_direction_adjusted_spread_d10"] > 0,
            "d10_spread_ci_excludes_zero": np.isfinite(r["spread_d10_ci_low"]) and r["spread_d10_ci_low"] > 0,
            "quarter_direction_share_ge_two_thirds": r["positive_valid_quarter_share"] >= (2.0 / 3.0),
            "leave_one_valid_quarter_out_positive": bool(r["leave_one_valid_quarter_out_all_positive"]),
            "d5_mean_ic_same_direction": np.isfinite(r["mean_direction_adjusted_ic_d5"]) and r["mean_direction_adjusted_ic_d5"] > 0,
        }
        passed = all(gates.values())
        if passed:
            promoted.append(factor)
        ledger.append({
            **{k: v for k, v in r.items() if k != "leave_one_valid_quarter_out_means"},
            "holm_bonferroni_pass": bool(holm[factor]),
            "all_promotion_gates_pass": passed,
            "promotion_status": "PROMOTED_STAGE2" if passed else "NOT_PROMOTED",
            "failed_gates": "|".join(k for k, v in gates.items() if not v),
            "loo_quarter_means_json": json.dumps(r["leave_one_valid_quarter_out_means"], sort_keys=True),
        })

    daily = pd.DataFrame(daily_rows)
    quantiles = pd.DataFrame(quantile_rows)
    ledger_df = pd.DataFrame(ledger)

    daily_path = OUT / "V2.8.1_STAGE1_DAILY_METRICS.csv"
    quantile_path = OUT / "V2.8.1_STAGE1_QUANTILE_METRICS.csv"
    ledger_path = OUT / "V2.8.1_STAGE1_FACTOR_RESULT_LEDGER.csv"
    daily.to_csv(daily_path, index=False, lineterminator="\n")
    quantiles.to_csv(quantile_path, index=False, lineterminator="\n")
    ledger_df.to_csv(ledger_path, index=False, lineterminator="\n")

    snapshot_receipt = {
        "schema": "AI_CORE_EVID_V2_8_1_CANONICAL_RESEARCH_SNAPSHOT_RECEIPT_V1",
        "source": {
            "stock_kline_revision": KLINE_REV,
            "stock_kline_sha256": sha_file(kline),
            "benchmark_revision": BENCH_REV,
            "benchmark_sha256": sha_file(bench),
            "vintage_receipt_sha256": sha_file(VINTAGE_RECEIPT),
            "pit_intervals_sha256": sha_file(PIT_PATH),
        },
        "population": {
            **source_diag,
            "vintage_stable_symbols": 5214,
            "mapping_exact_coverage": True,
            "mapping_authority": "official PIT interval security_code; vendor suffix crosscheck only",
        },
        "calendar": {
            "joint_calendar_dates_2025_2026": len(calendar),
            "first_date": calendar[0].isoformat(),
            "last_date": calendar[-1].isoformat(),
        },
        "panel": {
            "rows": int(len(panel)),
            "unique_securities": int(panel["canonical_security_id"].nunique()),
            "min_signal_date": str(panel["signal_date"].min()),
            "max_signal_date": str(panel["signal_date"].max()),
            "parquet_sha256": psha,
            "parquet_bytes": panel_path.stat().st_size,
            "sort": ["canonical_security_id", "signal_date"],
            "columns": PANEL_COLS,
        },
        "status": "CANONICAL_RESEARCH_SNAPSHOT_PASS",
    }
    snapshot_receipt["receipt_sha256"] = stable_json_sha(snapshot_receipt)
    snap_path = OUT / "V2.8.1_CANONICAL_RESEARCH_SNAPSHOT_RECEIPT.json"
    snap_path.write_text(json.dumps(snapshot_receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    screen_receipt = {
        "schema": "AI_CORE_EVID_V2_8_1_STAGE1_FACTOR_SCREEN_RECEIPT_V1",
        "run_id": os.getenv("GITHUB_RUN_ID", ""),
        "head_sha": os.getenv("GITHUB_SHA", ""),
        "started_at_utc": started.isoformat(),
        "finished_at_utc": datetime.now(timezone.utc).isoformat(),
        "factor_family_size": 9,
        "promoted_factors": promoted,
        "promoted_count": len(promoted),
        "not_promoted_factors": [f for f in FACTORS if f not in promoted],
        "panel_sha256": psha,
        "result_ledger_sha256": sha_file(ledger_path),
        "daily_metrics_sha256": sha_file(daily_path),
        "quantile_metrics_sha256": sha_file(quantile_path),
        "frozen_rules": {
            "promotion_rule": sha_file(PROMOTION_RULE),
            "statistical_mechanics": sha_file(STATS_RULE),
            "execution_contract": sha_file(EXEC_CONTRACT),
            "snapshot_contract": sha_file(SNAPSHOT_CONTRACT),
        },
        "gate": {
            "status": "STAGE1_SCREEN_COMPLETE",
            "all_nine_hypotheses_retained": len(ledger_df) == 9,
            "optional_stopping_used": False,
            "thresholds_modified_after_results": False,
        },
    }
    screen_receipt["receipt_sha256"] = stable_json_sha(screen_receipt)
    screen_path = OUT / "V2.8.1_STAGE1_FACTOR_SCREEN_RECEIPT.json"
    screen_path.write_text(json.dumps(screen_receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    final = {
        "schema": "AI_CORE_EVID_V2_8_1_FINAL_RECORD_V1",
        "version": "V2.8.1",
        "strategy_identity": "AI_CORE_GROWTH_TREND_V2_8_0_NEW_BASELINE",
        "canonical_snapshot": {
            "status": "PASS",
            "panel_sha256": psha,
            "receipt_sha256": snapshot_receipt["receipt_sha256"],
        },
        "vendor_vintage": {
            "status": "VINTAGE_SCALE_INVARIANCE_PASS",
            "stable_symbols": 5214,
            "unstable_symbols": 0,
            "receipt_sha256": VINTAGE_RECEIPT_SHA,
        },
        "stage1": {
            "status": "COMPLETE",
            "promoted_count": len(promoted),
            "promoted_factors": promoted,
            "not_promoted_factors": [f for f in FACTORS if f not in promoted],
            "result_ledger_sha256": sha_file(ledger_path),
            "screen_receipt_sha256": screen_receipt["receipt_sha256"],
        },
        "governance": {
            "retrospective_status": "DEVELOPMENT_DIAGNOSTIC_RETRO_STRESS_ONLY",
            "setup_emission_authorized": False,
            "episode_emission_authorized": False,
            "prospective_first60_activated": False,
            "live_authorized": False,
        },
        "next_stage": (
            "V2.8.2 STAGE2 COMBINATION RESEARCH PREREGISTRATION"
            if promoted else
            "V2.8.2 FACTOR-BASELINE REVIEW — NO STAGE1 FACTOR PROMOTED"
        ),
    }
    final_path = OUT / "V2.8.1_FINAL_RECORD.json"
    final_path.write_text(json.dumps(final, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(json.dumps({
        "snapshot": snapshot_receipt,
        "screen": screen_receipt,
        "factor_results": ledger,
        "final": final,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
