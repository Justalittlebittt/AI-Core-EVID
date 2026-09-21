from __future__ import annotations

import hashlib
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import v281_stage1_factor_screen as s1

OUT = Path("v282_conditional")
OUT.mkdir(exist_ok=True)

CONTRACT = Path("evidence/V2.8.2_CONDITIONAL_DIAGNOSTIC_CONTRACT.json")
FINAL_RECORD = Path("evidence/V2.8.1_FINAL_RECORD.json")
SNAPSHOT_RECEIPT = Path("evidence/V2.8.1_CANONICAL_RESEARCH_SNAPSHOT_RECEIPT.json")
STAGE1_DAILY = Path("evidence/V2.8.1_STAGE1_DAILY_METRICS.csv")
SECTOR_RECEIPT = Path("evidence/V2.8.2_CAPCO_SECTOR_PARSER_RECEIPT.json")
SECTOR_RECEIPT_SEAL = "55a4ceaa6ccab4b85d2819e8918780fb333c7173650ca03448485705c62767c2"
SECTOR_ROWS = Path("evidence/V2.8.2_CAPCO_SECTOR_SNAPSHOT_ROWS.csv")
SECTOR_INTERVALS = Path("evidence/V2.8.2_CAPCO_SECTOR_EFFECTIVE_INTERVALS.csv")

EXPECTED_PANEL_SHA = "5a37b30ccc6a33b8ac8bc3a43399c0372695bf2016e0efe0e9168116a60ccbf2"
FOCUS_FACTORS = ["ret_20", "ret_60", "rv10_over_rv60", "tr10_over_tr60"]
MIN_CONDITIONED_ROWS = 50
MIN_SECTOR_ROWS = 10


def sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda: f.read(1024 * 1024), b""):
            h.update(b)
    return h.hexdigest()


def stable_json_sha(obj: dict) -> str:
    b = json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(b).hexdigest()


def verify_receipt(path: Path, expected_seal: str, label: str) -> dict:
    obj = json.loads(path.read_text(encoding="utf-8"))
    embedded = obj.get("receipt_sha256")
    unsigned = dict(obj)
    unsigned.pop("receipt_sha256", None)
    computed = stable_json_sha(unsigned)
    if embedded != expected_seal or computed != expected_seal:
        raise RuntimeError(
            f"{label} seal mismatch embedded={embedded} computed={computed} expected={expected_seal}"
        )
    return obj


def rank_ic_with_count(
    g: pd.DataFrame,
    factor: str,
    outcome: str,
    minimum_rows: int = 2,
) -> tuple[float, int]:
    z = g[[factor, outcome]].replace([np.inf, -np.inf], np.nan).dropna()
    n = len(z)
    if n < minimum_rows:
        return np.nan, n
    if z[factor].nunique() < 2 or z[outcome].nunique() < 2:
        return np.nan, n
    return s1.avg_rank_corr(z[factor], z[outcome]), n


def sector_neutral_rank_ic(
    g: pd.DataFrame,
    factor: str,
    outcome: str,
) -> tuple[float, int, int]:
    z = g.loc[
        g["sector_context_code"].ne("UNKNOWN"),
        ["sector_context_code", factor, outcome],
    ].replace([np.inf, -np.inf], np.nan).dropna()

    parts = []
    eligible_sector_count = 0
    for _sector, h in z.groupby("sector_context_code", sort=False):
        if len(h) < MIN_SECTOR_ROWS:
            continue
        if h[factor].nunique() < 2 or h[outcome].nunique() < 2:
            continue
        q = h.copy()
        q["factor_rank"] = q[factor].rank(method="average", pct=True)
        q["outcome_rank"] = q[outcome].rank(method="average", pct=True)
        parts.append(q[["factor_rank", "outcome_rank"]])
        eligible_sector_count += 1

    if not parts:
        return np.nan, 0, 0
    pooled = pd.concat(parts, ignore_index=True)
    n = len(pooled)
    if n < MIN_CONDITIONED_ROWS:
        return np.nan, n, eligible_sector_count
    if pooled["factor_rank"].nunique() < 2 or pooled["outcome_rank"].nunique() < 2:
        return np.nan, n, eligible_sector_count
    return (
        float(pooled["factor_rank"].corr(pooled["outcome_rank"], method="pearson")),
        n,
        eligible_sector_count,
    )


def load_market_context(bench_path: Path) -> pd.DataFrame:
    con = duckdb.connect()
    q = f"""
      SELECT cast(bar_time as date) signal_date,
             cast(close as double) close_px
      FROM read_parquet({s1.sql_lit(bench_path)})
      WHERE cast(symbol as varchar)='000300.SS'
        AND cast(kline_t as varchar)='1D'
      ORDER BY signal_date
    """
    b = con.execute(q).fetchdf()
    con.close()
    if b.empty:
        raise RuntimeError("CSI300 benchmark missing")
    b["signal_date"] = pd.to_datetime(b["signal_date"]).dt.date
    if b["signal_date"].duplicated().any():
        raise RuntimeError("duplicate CSI300 dates")

    close = pd.to_numeric(b["close_px"], errors="coerce")
    if (close <= 0).any():
        raise RuntimeError("non-positive CSI300 close")
    prev = close.shift(1)
    logret = np.log(close / prev)
    b["market_ret20"] = close / close.shift(20) - 1.0
    rv10 = logret.rolling(10, min_periods=10).std(ddof=0)
    rv60 = logret.rolling(60, min_periods=60).std(ddof=0)
    b["market_rv10_over_rv60"] = rv10 / rv60.replace(0.0, np.nan)

    known = np.isfinite(b["market_ret20"]) & np.isfinite(b["market_rv10_over_rv60"])
    trend = np.where(b["market_ret20"] >= 0, "UP", "DOWN")
    vol = np.where(b["market_rv10_over_rv60"] <= 1.0, "CALM", "STRESSED")
    b["market_state"] = np.where(known, np.char.add(np.char.add(trend, "_"), vol), "UNKNOWN_WARMUP")
    return b[["signal_date", "market_ret20", "market_rv10_over_rv60", "market_state"]]


def attach_sector_context(signal: pd.DataFrame, intervals: pd.DataFrame) -> pd.DataFrame:
    sector_rows = pd.read_csv(SECTOR_ROWS, dtype=str).fillna("")
    eff = pd.read_csv(SECTOR_INTERVALS, dtype=str).fillna("")
    required_rows = {
        "snapshot_label",
        "security_code",
        "context_code",
        "context_name",
    }
    if not required_rows.issubset(sector_rows.columns):
        raise RuntimeError(f"sector row columns missing {required_rows - set(sector_rows.columns)}")
    if sector_rows.duplicated(["snapshot_label", "security_code"]).any():
        raise RuntimeError("duplicate snapshot/security_code in sector rows")

    x = signal.copy()
    code_map = intervals.set_index("canonical_security_id")["security_code"]
    x["security_code"] = x["canonical_security_id"].map(code_map)
    if x["security_code"].isna().any():
        raise RuntimeError("signal row missing official security_code")

    x["sector_snapshot_label"] = ""
    for _, r in eff.iterrows():
        start = date.fromisoformat(r["research_effective_date"])
        end = date.fromisoformat(r["research_effective_end_date"])
        mask = (x["signal_date"] >= start) & (x["signal_date"] <= end)
        if (x.loc[mask, "sector_snapshot_label"] != "").any():
            raise RuntimeError("overlapping CAPCO effective intervals")
        x.loc[mask, "sector_snapshot_label"] = r["snapshot_label"]

    if (x["sector_snapshot_label"] == "").any():
        bad = sorted(set(x.loc[x["sector_snapshot_label"] == "", "signal_date"]))[:20]
        raise RuntimeError(f"signal dates missing CAPCO effective snapshot: {bad}")

    m = sector_rows[
        ["snapshot_label", "security_code", "context_code", "context_name"]
    ].rename(
        columns={
            "snapshot_label": "sector_snapshot_label",
            "context_code": "sector_context_code",
            "context_name": "sector_context_name",
        }
    )
    x = x.merge(
        m,
        on=["sector_snapshot_label", "security_code"],
        how="left",
        validate="many_to_one",
    )
    x["sector_context_code"] = x["sector_context_code"].fillna("").replace("", "UNKNOWN")
    x["sector_context_name"] = x["sector_context_name"].fillna("").replace("", "UNKNOWN")
    return x


def build_sector_relative_state(signal: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    x = signal.sort_values(["canonical_security_id", "signal_date"], kind="mergesort").copy()
    close = pd.to_numeric(x["close"], errors="coerce")
    prev = x.groupby("canonical_security_id", sort=False)["close"].shift(1)
    prev = pd.to_numeric(prev, errors="coerce")
    x["stock_ret1"] = close / prev.replace(0.0, np.nan) - 1.0
    x.loc[~np.isfinite(x["stock_ret1"]), "stock_ret1"] = np.nan

    broad = (
        x.groupby("signal_date", as_index=False)
        .agg(
            broad_a_daily_ew_return=("stock_ret1", "mean"),
            broad_a_daily_valid_stocks=("stock_ret1", "count"),
        )
        .sort_values("signal_date")
        .reset_index(drop=True)
    )
    if (broad["broad_a_daily_ew_return"] <= -1.0).any():
        raise RuntimeError("invalid broad-A daily equal-weight return <= -100%")
    broad_log = np.log1p(broad["broad_a_daily_ew_return"])
    broad["broad_a_ret20"] = np.expm1(
        broad_log.rolling(20, min_periods=20).sum()
    )

    mapped = x[
        x["sector_context_code"].ne("UNKNOWN")
        & x["stock_ret1"].notna()
    ].copy()
    sector_daily = (
        mapped.groupby(["signal_date", "sector_context_code"], as_index=False)
        .agg(
            sector_daily_ew_return=("stock_ret1", "mean"),
            sector_daily_valid_stocks=("stock_ret1", "count"),
        )
        .sort_values(["sector_context_code", "signal_date"], kind="mergesort")
        .reset_index(drop=True)
    )
    if (sector_daily["sector_daily_ew_return"] <= -1.0).any():
        raise RuntimeError("invalid sector daily equal-weight return <= -100%")

    sector_daily["sector_log1p"] = np.log1p(sector_daily["sector_daily_ew_return"])
    sector_daily["sector_ret20"] = (
        sector_daily.groupby("sector_context_code", sort=False)["sector_log1p"]
        .transform(lambda s: np.expm1(s.rolling(20, min_periods=20).sum()))
    )
    sector_daily = sector_daily.merge(
        broad[["signal_date", "broad_a_ret20"]],
        on="signal_date",
        how="left",
        validate="many_to_one",
    )
    sector_daily["sector_relative_ret20"] = (
        sector_daily["sector_ret20"] - sector_daily["broad_a_ret20"]
    )
    finite = np.isfinite(sector_daily["sector_relative_ret20"])
    sector_daily["sector_relative_state"] = np.where(
        finite,
        np.where(sector_daily["sector_relative_ret20"] >= 0, "STRONG", "WEAK"),
        "UNKNOWN",
    )

    x = x.merge(
        sector_daily[
            [
                "signal_date",
                "sector_context_code",
                "sector_daily_valid_stocks",
                "sector_ret20",
                "broad_a_ret20",
                "sector_relative_ret20",
                "sector_relative_state",
            ]
        ],
        on=["signal_date", "sector_context_code"],
        how="left",
        validate="many_to_one",
    )
    x["sector_relative_state"] = x["sector_relative_state"].fillna("UNKNOWN")
    return x, sector_daily


def summarize_market(daily: pd.DataFrame) -> pd.DataFrame:
    rows = []
    grouping = list(daily.groupby(["factor", "market_state"], sort=True))
    for factor, g0 in daily.groupby("factor", sort=True):
        grouping.append(((factor, "ALL_MARKET_STATES"), g0))

    for (factor, state), g in grouping:
        valid10 = g["raw_ic_d10"].dropna()
        valid5 = g["raw_ic_d5"].dropna()
        sn10 = g["sector_neutral_ic_d10"].dropna()
        sn5 = g["sector_neutral_ic_d5"].dropna()
        rows.append(
            {
                "factor": factor,
                "market_state": state,
                "calendar_days": len(g),
                "valid_d10_days": len(valid10),
                "mean_raw_ic_d10": float(valid10.mean()) if len(valid10) else np.nan,
                "median_raw_ic_d10": float(valid10.median()) if len(valid10) else np.nan,
                "positive_raw_ic_d10_day_share": float((valid10 > 0).mean()) if len(valid10) else np.nan,
                "valid_d5_days": len(valid5),
                "mean_raw_ic_d5": float(valid5.mean()) if len(valid5) else np.nan,
                "sector_neutral_valid_d10_days": len(sn10),
                "mean_sector_neutral_ic_d10": float(sn10.mean()) if len(sn10) else np.nan,
                "sector_neutral_valid_d5_days": len(sn5),
                "mean_sector_neutral_ic_d5": float(sn5.mean()) if len(sn5) else np.nan,
                "mean_baseline_rows_d10": float(g["baseline_rows_d10"].mean()),
                "mean_sector_mapped_share": float(g["sector_mapped_share"].mean()),
            }
        )
    return pd.DataFrame(rows)


def summarize_interactions(daily: pd.DataFrame) -> pd.DataFrame:
    long_rows = []
    for _, r in daily.iterrows():
        for state, prefix in (("STRONG", "strong"), ("WEAK", "weak")):
            long_rows.append(
                {
                    "factor": r["factor"],
                    "signal_date": r["signal_date"],
                    "market_state": r["market_state"],
                    "sector_relative_state": state,
                    "raw_ic_d10": r[f"{prefix}_sector_ic_d10"],
                    "raw_ic_d5": r[f"{prefix}_sector_ic_d5"],
                    "rows_d10": r[f"{prefix}_sector_rows_d10"],
                }
            )
    z = pd.DataFrame(long_rows)
    rows = []
    for keys, g in z.groupby(
        ["factor", "market_state", "sector_relative_state"], sort=True
    ):
        factor, market_state, sector_state = keys
        d10 = g["raw_ic_d10"].dropna()
        d5 = g["raw_ic_d5"].dropna()
        rows.append(
            {
                "factor": factor,
                "market_state": market_state,
                "sector_relative_state": sector_state,
                "calendar_days": len(g),
                "valid_d10_days": len(d10),
                "mean_raw_ic_d10": float(d10.mean()) if len(d10) else np.nan,
                "median_raw_ic_d10": float(d10.median()) if len(d10) else np.nan,
                "positive_raw_ic_d10_day_share": float((d10 > 0).mean()) if len(d10) else np.nan,
                "valid_d5_days": len(d5),
                "mean_raw_ic_d5": float(d5.mean()) if len(d5) else np.nan,
                "mean_rows_d10": float(g.loc[g["raw_ic_d10"].notna(), "rows_d10"].mean())
                if len(d10)
                else np.nan,
            }
        )
    return pd.DataFrame(rows)


def summarize_quarters(daily: pd.DataFrame) -> pd.DataFrame:
    z = daily.copy()
    z["quarter"] = pd.to_datetime(z["signal_date"]).dt.to_period("Q").astype(str)
    frames = []
    z_all = z.copy()
    z_all["market_state"] = "ALL_MARKET_STATES"
    frames.append(z_all)
    frames.append(z)
    q = pd.concat(frames, ignore_index=True)

    rows = []
    for keys, g in q.groupby(["factor", "quarter", "market_state"], sort=True):
        factor, quarter, state = keys
        d10 = g["raw_ic_d10"].dropna()
        sn10 = g["sector_neutral_ic_d10"].dropna()
        rows.append(
            {
                "factor": factor,
                "quarter": quarter,
                "market_state": state,
                "calendar_days": len(g),
                "valid_d10_days": len(d10),
                "mean_raw_ic_d10": float(d10.mean()) if len(d10) else np.nan,
                "raw_ic_d10_sign": (
                    "POSITIVE"
                    if len(d10) and d10.mean() > 0
                    else "NEGATIVE"
                    if len(d10) and d10.mean() < 0
                    else "ZERO_OR_UNAVAILABLE"
                ),
                "positive_raw_ic_d10_day_share": float((d10 > 0).mean()) if len(d10) else np.nan,
                "sector_neutral_valid_d10_days": len(sn10),
                "mean_sector_neutral_ic_d10": float(sn10.mean()) if len(sn10) else np.nan,
            }
        )
    return pd.DataFrame(rows)


def main() -> None:
    started = datetime.now(timezone.utc)

    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    if contract.get("status") != "FROZEN_BEFORE_CONDITIONAL_DIAGNOSTIC_RESULTS":
        raise RuntimeError("conditional diagnostic contract not frozen")

    final = json.loads(FINAL_RECORD.read_text(encoding="utf-8"))
    if final["stage1"]["promoted_count"] != 0:
        raise RuntimeError("V2.8.1 promoted-count invariant changed")
    if final["canonical_snapshot"]["panel_sha256"] != EXPECTED_PANEL_SHA:
        raise RuntimeError("V2.8.1 final-record panel SHA changed")

    sector_receipt = verify_receipt(
        SECTOR_RECEIPT, SECTOR_RECEIPT_SEAL, "CAPCO sector parser receipt"
    )
    if not sector_receipt.get("structural_parser_pass"):
        raise RuntimeError("CAPCO sector parser is not structurally PASS")

    intervals = s1.load_intervals()
    stable, symbol_to_cid = s1.load_stable_symbols(intervals)
    calendar = s1.build_joint_calendar()
    kline, bench = s1.download_sources()
    px, source_max, source_diag = s1.load_price_panel(
        kline, stable["symbol"].astype(str).tolist(), symbol_to_cid, intervals
    )
    if source_max != date(2026, 9, 18):
        raise RuntimeError(f"unexpected pinned source max date {source_max}")

    feat_input = px[
        ["canonical_security_id", "bar_date", "open", "high", "low", "close", "amount"]
    ]
    features = s1.build_features(feat_input)
    panel_all = s1.build_outcomes(features, calendar, source_max)
    signal = panel_all[panel_all["signal_date"] <= s1.MAX_SIGNAL_DATE].copy()

    # Semantic reproduction gate. The frozen V2.8.1 Parquet byte SHA remains the
    # authority for the original artifact, but rewriting logically identical
    # Parquet bytes is not required here. Verify the research population and,
    # below, the exact Stage-1 daily statistics used by this diagnostic.
    snapshot_receipt = json.loads(SNAPSHOT_RECEIPT.read_text(encoding="utf-8"))
    frozen_panel = snapshot_receipt["panel"]
    semantic_population = {
        "rows": int(len(signal)),
        "unique_securities": int(signal["canonical_security_id"].nunique()),
        "min_signal_date": str(signal["signal_date"].min()),
        "max_signal_date": str(signal["signal_date"].max()),
    }
    expected_population = {
        "rows": int(frozen_panel["rows"]),
        "unique_securities": int(frozen_panel["unique_securities"]),
        "min_signal_date": str(frozen_panel["min_signal_date"]),
        "max_signal_date": str(frozen_panel["max_signal_date"]),
    }
    if semantic_population != expected_population:
        raise RuntimeError(
            f"canonical panel semantic population mismatch actual={semantic_population} "
            f"expected={expected_population}"
        )

    signal = attach_sector_context(signal, intervals)
    signal, sector_daily = build_sector_relative_state(signal)

    market = load_market_context(bench)
    signal = signal.merge(
        market,
        on="signal_date",
        how="left",
        validate="many_to_one",
    )
    signal["market_state"] = signal["market_state"].fillna("UNKNOWN_WARMUP")

    primary_dates = sorted(
        d
        for d, g in signal.groupby("signal_date", sort=True)
        if np.isfinite(pd.to_numeric(g["fwd_10"], errors="coerce")).any()
    )
    if not primary_dates:
        raise RuntimeError("no D+10 evaluable dates")
    signal = signal[signal["signal_date"].isin(primary_dates)].copy()

    daily_rows = []
    for d, g in signal.groupby("signal_date", sort=True):
        market_states = g["market_state"].dropna().unique().tolist()
        if len(market_states) != 1:
            raise RuntimeError(f"non-unique market state on {d}: {market_states}")
        market_state = market_states[0]
        market_ret20 = pd.to_numeric(g["market_ret20"], errors="coerce").dropna()
        market_rv = pd.to_numeric(g["market_rv10_over_rv60"], errors="coerce").dropna()
        mapped_share = float(g["sector_context_code"].ne("UNKNOWN").mean())

        for factor in FOCUS_FACTORS:
            ic10, n10 = rank_ic_with_count(g, factor, "fwd_10", 2)
            ic5, n5 = rank_ic_with_count(g, factor, "fwd_5", 2)
            sn10, sn_n10, sn_sector10 = sector_neutral_rank_ic(g, factor, "fwd_10")
            sn5, sn_n5, sn_sector5 = sector_neutral_rank_ic(g, factor, "fwd_5")

            rec = {
                "factor": factor,
                "signal_date": d.isoformat(),
                "market_state": market_state,
                "market_ret20": float(market_ret20.iloc[0]) if len(market_ret20) else np.nan,
                "market_rv10_over_rv60": float(market_rv.iloc[0]) if len(market_rv) else np.nan,
                "sector_mapped_share": mapped_share,
                "factor_finite_count": int(
                    np.isfinite(pd.to_numeric(g[factor], errors="coerce")).sum()
                ),
                "raw_ic_d10": ic10,
                "baseline_rows_d10": n10,
                "raw_ic_d5": ic5,
                "baseline_rows_d5": n5,
                "sector_neutral_ic_d10": sn10,
                "sector_neutral_rows_d10": sn_n10,
                "sector_neutral_eligible_sectors_d10": sn_sector10,
                "sector_neutral_ic_d5": sn5,
                "sector_neutral_rows_d5": sn_n5,
                "sector_neutral_eligible_sectors_d5": sn_sector5,
            }

            for state, prefix in (("STRONG", "strong"), ("WEAK", "weak")):
                h = g[g["sector_relative_state"].eq(state)]
                c10, cn10 = rank_ic_with_count(
                    h, factor, "fwd_10", MIN_CONDITIONED_ROWS
                )
                c5, cn5 = rank_ic_with_count(
                    h, factor, "fwd_5", MIN_CONDITIONED_ROWS
                )
                rec[f"{prefix}_sector_ic_d10"] = c10
                rec[f"{prefix}_sector_rows_d10"] = cn10
                rec[f"{prefix}_sector_ic_d5"] = c5
                rec[f"{prefix}_sector_rows_d5"] = cn5

            rec["strong_sector_stock_rows"] = int(
                g["sector_relative_state"].eq("STRONG").sum()
            )
            rec["weak_sector_stock_rows"] = int(
                g["sector_relative_state"].eq("WEAK").sum()
            )
            rec["unknown_sector_state_stock_rows"] = int(
                g["sector_relative_state"].eq("UNKNOWN").sum()
            )
            daily_rows.append(rec)

    daily = pd.DataFrame(daily_rows)

    # Reproduce the frozen V2.8.1 daily statistics for every factor/date used
    # here. This is the semantic integrity gate for the reconstructed panel.
    frozen_daily = pd.read_csv(STAGE1_DAILY, dtype={"signal_date": str})
    frozen_focus = frozen_daily[
        frozen_daily["factor"].isin(FOCUS_FACTORS)
    ][
        [
            "factor",
            "signal_date",
            "factor_finite_count",
            "rank_ic_d10",
            "rank_ic_d5",
        ]
    ].copy()
    current_focus = daily[
        [
            "factor",
            "signal_date",
            "factor_finite_count",
            "raw_ic_d10",
            "raw_ic_d5",
        ]
    ].copy()
    semantic_check = frozen_focus.merge(
        current_focus,
        on=["factor", "signal_date"],
        how="left",
        validate="one_to_one",
        suffixes=("_frozen", "_current"),
        indicator=True,
    )
    if not semantic_check["_merge"].eq("both").all():
        bad = semantic_check.loc[
            semantic_check["_merge"].ne("both"), ["factor", "signal_date", "_merge"]
        ].head(20).to_dict("records")
        raise RuntimeError(f"Stage-1 semantic date coverage mismatch: {bad}")

    count_equal = (
        pd.to_numeric(
            semantic_check["factor_finite_count_frozen"], errors="raise"
        ).astype("int64")
        == pd.to_numeric(
            semantic_check["factor_finite_count_current"], errors="raise"
        ).astype("int64")
    )
    if not count_equal.all():
        bad = semantic_check.loc[
            ~count_equal,
            [
                "factor",
                "signal_date",
                "factor_finite_count_frozen",
                "factor_finite_count_current",
            ],
        ].head(20).to_dict("records")
        raise RuntimeError(f"Stage-1 factor finite-count mismatch: {bad}")

    max_abs_diffs = {}
    for frozen_col, current_col, label in (
        ("rank_ic_d10", "raw_ic_d10", "rank_ic_d10"),
        ("rank_ic_d5", "raw_ic_d5", "rank_ic_d5"),
    ):
        a = pd.to_numeric(semantic_check[frozen_col], errors="coerce").to_numpy(float)
        b = pd.to_numeric(semantic_check[current_col], errors="coerce").to_numpy(float)
        nan_mismatch = np.isnan(a) != np.isnan(b)
        if nan_mismatch.any():
            raise RuntimeError(f"Stage-1 semantic NaN pattern mismatch for {label}")
        finite = np.isfinite(a) & np.isfinite(b)
        max_diff = float(np.max(np.abs(a[finite] - b[finite]))) if finite.any() else 0.0
        max_abs_diffs[label] = max_diff
        if max_diff > 1e-12:
            raise RuntimeError(
                f"Stage-1 semantic numerical mismatch for {label}: "
                f"max_abs_diff={max_diff} > 1e-12"
            )

    semantic_reproduction = {
        "status": "PASS",
        "population": semantic_population,
        "frozen_panel_reference_sha256": EXPECTED_PANEL_SHA,
        "stage1_daily_rows_compared": int(len(semantic_check)),
        "factor_finite_counts_exact": True,
        "max_abs_ic_difference": max_abs_diffs,
        "numerical_equivalence_tolerance": 1e-12,
        "parquet_byte_rewrite_used_as_gate": False,
    }

    market_summary = summarize_market(daily)
    interaction_summary = summarize_interactions(daily)
    quarter_summary = summarize_quarters(daily)

    daily_path = OUT / "V2.8.2_CONDITIONAL_DAILY_METRICS.csv"
    market_path = OUT / "V2.8.2_CONDITIONAL_MARKET_SUMMARY.csv"
    interaction_path = OUT / "V2.8.2_CONDITIONAL_MARKET_SECTOR_SUMMARY.csv"
    quarter_path = OUT / "V2.8.2_CONDITIONAL_QUARTER_SUMMARY.csv"

    daily.to_csv(daily_path, index=False, lineterminator="\n")
    market_summary.to_csv(market_path, index=False, lineterminator="\n")
    interaction_summary.to_csv(interaction_path, index=False, lineterminator="\n")
    quarter_summary.to_csv(quarter_path, index=False, lineterminator="\n")

    market_state_counts = (
        daily[["signal_date", "market_state"]]
        .drop_duplicates()
        .groupby("market_state")
        .size()
        .sort_index()
        .to_dict()
    )
    mapped_signal_share = float(signal["sector_context_code"].ne("UNKNOWN").mean())
    known_sector_state_share = float(signal["sector_relative_state"].isin(["STRONG", "WEAK"]).mean())

    receipt = {
        "schema": "AI_CORE_EVID_V2_8_2_CONDITIONAL_DIAGNOSTIC_RECEIPT_V1",
        "started_at_utc": started.isoformat(),
        "finished_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "EXPLORATORY_DIAGNOSTIC_COMPLETE",
        "promotion_effect": "NONE",
        "setup_or_episode_authorization": False,
        "contract_sha256": sha_file(CONTRACT),
        "v2_8_1_final_record_sha256": sha_file(FINAL_RECORD),
        "capco_sector_parser_receipt_seal": SECTOR_RECEIPT_SEAL,
        "capco_sector_rows_sha256": sha_file(SECTOR_ROWS),
        "capco_sector_effective_intervals_sha256": sha_file(SECTOR_INTERVALS),
        "pinned_stock_kline_revision": s1.KLINE_REV,
        "pinned_stock_kline_sha256": s1.KLINE_SHA,
        "pinned_benchmark_revision": s1.BENCH_REV,
        "pinned_benchmark_sha256": s1.BENCH_SHA,
        "frozen_v2_8_1_panel_reference_sha256": EXPECTED_PANEL_SHA,
        "semantic_panel_reproduction": semantic_reproduction,
        "source_diagnostics": source_diag,
        "primary_evaluation_first_date": primary_dates[0].isoformat(),
        "primary_evaluation_last_date": primary_dates[-1].isoformat(),
        "primary_evaluation_date_count": len(primary_dates),
        "focus_factors": FOCUS_FACTORS,
        "market_state_date_counts": {str(k): int(v) for k, v in market_state_counts.items()},
        "sector_mapped_signal_row_share": mapped_signal_share,
        "known_sector_relative_state_signal_row_share": known_sector_state_share,
        "sector_daily_context_rows": int(len(sector_daily)),
        "daily_metric_rows": int(len(daily)),
        "market_summary_rows": int(len(market_summary)),
        "market_sector_summary_rows": int(len(interaction_summary)),
        "quarter_summary_rows": int(len(quarter_summary)),
        "daily_metrics_sha256": sha_file(daily_path),
        "market_summary_sha256": sha_file(market_path),
        "market_sector_summary_sha256": sha_file(interaction_path),
        "quarter_summary_sha256": sha_file(quarter_path),
        "interpretation_guard": "Exploratory same-sample conditional diagnostics only. No V2.8.1 factor status changes and no PASS/promotion labels are produced.",
        "next_step": "REVIEW_PREDEFINED_MECHANISM_QUESTIONS_AND_FREEZE_ARCHITECTURE_DECISION",
    }
    receipt["receipt_sha256"] = stable_json_sha(receipt)
    receipt_path = OUT / "V2.8.2_CONDITIONAL_DIAGNOSTIC_RECEIPT.json"
    receipt_path.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(json.dumps(receipt, ensure_ascii=False, indent=2), flush=True)
    print("\nMARKET SUMMARY", flush=True)
    print(market_summary.to_string(index=False), flush=True)
    print("\nMARKET X SECTOR SUMMARY", flush=True)
    print(interaction_summary.to_string(index=False), flush=True)


if __name__ == "__main__":
    main()
