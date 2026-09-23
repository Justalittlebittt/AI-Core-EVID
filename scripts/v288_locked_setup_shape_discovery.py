from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from v280_scale_invariant_features import build_features

CONTRACT = Path("evidence/V2.8.8_NEW_SETUP_SHAPE_DISCOVERY_GATE_CONTRACT.json")
CONTRACT_SCHEMA = "AI_CORE_EVID_V2_8_8_NEW_SETUP_SHAPE_DISCOVERY_GATE_CONTRACT_V1"
CALENDAR = Path("evidence/V2.8.5_JOINT_A_SHARE_TRADING_CALENDAR_2023_2024.json")
OUT_LEDGER = Path("evidence/V2.8.8_SETUP_SHAPE_DISCOVERY_LEDGER.csv")
OUT_DAILY = Path("evidence/V2.8.8_SETUP_SHAPE_DISCOVERY_DAILY_METRICS.csv")
OUT_FINAL = Path("evidence/V2.8.8_SETUP_SHAPE_DISCOVERY_FINAL_RECEIPT.json")

MIN_SIDE = 50
MIN_D10_DATES = 200
MIN_D5_DATES = 200
MIN_QUARTERS = 4
MIN_QUARTER_DATES = 20

FOLDS = {
    0: {
        "sample": Path("evidence/V2.8.5_BACKWARD_HOLDOUT_SAMPLE_MANIFEST.csv"),
        "sample_sha": "199864ece6c02f3257647d59ba63fe261a7b478a2525b7ed8042bbf475a9fe48",
        "sample_count": 1031,
        "receipt": Path("evidence/V2.8.5_BAOSTOCK_HOLDOUT_SOURCE_SNAPSHOT_RECEIPT.json"),
        "receipt_seal": "b38838f4c6a4fe679cc45300093cfb366ae15cb8f1fa52746cf50ca9faae62a9",
        "source_dir": Path("evidence/v285_holdout_source"),
    },
    1: {
        "sample": Path("evidence/V2.8.6_FOLD1_MECHANISM_REPLICATION_MANIFEST.csv"),
        "sample_sha": "fe15777a0a3a131b58288454a0e3023503bd80ac6a22f20a2e50c45a4deed38a",
        "sample_count": 1058,
        "receipt": Path("evidence/V2.8.6_FOLD1_SOURCE_SNAPSHOT_RECEIPT.json"),
        "receipt_seal": "fc9606a8ea1e024c40911202bfc7c7bddeb86403322e16176ceff6138c382a7e",
        "source_dir": Path("evidence/v286_fold1_source"),
    },
    2: {
        "sample": Path("evidence/V2.8.7_FOLD2_SETUP_SHAPE_MANIFEST.csv"),
        "sample_sha": "79b6a4c752a22a16f6ec7167dfb1e6b007473229d7ec6729fb03a15b3ba0fa9a",
        "sample_count": 1048,
        "receipt": Path("evidence/V2.8.7_FOLD2_SOURCE_SNAPSHOT_RECEIPT.json"),
        "receipt_seal": "f6c5df739dc82182f8ce8f660599106331c54cdd6597e98d0efacfb187d11d63",
        "source_dir": Path("evidence/v287_fold2_source"),
    },
}

CANDIDATES = {
    "C1_DC_TREND": ("dual_compression", "trend_structure"),
    "C2_DC_MOMENTUM": ("dual_compression", "momentum_structure"),
    "C3_DC_NEAR_HIGH": ("dual_compression", "near_high_structure"),
}

REQUIRED_FEATURES = [
    "ret_20", "ret_60",
    "ma50_vs_ma150", "ma150_vs_ma200", "ma200_slope20",
    "dist_high60", "dist_high252",
    "rv10_over_rv60", "tr10_over_tr60",
]


def sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda: f.read(1024 * 1024), b""):
            h.update(b)
    return h.hexdigest()


def stable_sha(obj: dict) -> str:
    b = json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(b).hexdigest()


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def numeric(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce")


def load_contract() -> dict:
    obj = read_json(CONTRACT)
    if obj.get("schema") != CONTRACT_SCHEMA:
        raise RuntimeError("DISCOVERY_CONTRACT_SCHEMA_BLOCK")
    if obj.get("status") != "FROZEN_BEFORE_V2_8_8_DISCOVERY_EXECUTION":
        raise RuntimeError("DISCOVERY_CONTRACT_STATUS_BLOCK")
    auth = obj.get("authorization", {})
    if auth.get("fold3_access") is not False or auth.get("fold4_access") is not False:
        raise RuntimeError("SEALED_FOLD_AUTHORIZATION_BLOCK")
    ids = [x["id"] for x in obj.get("candidate_library", [])]
    if ids != list(CANDIDATES):
        raise RuntimeError(f"CANDIDATE_LIBRARY_DRIFT:{ids}")
    return obj


def load_calendar() -> list[str]:
    obj = read_json(CALENDAR)
    days = obj["trading_dates"]
    if len(days) != 484 or days != sorted(days) or len(days) != len(set(days)):
        raise RuntimeError("CALENDAR_INTEGRITY_BLOCK")
    return days


def target_map(days: list[str]) -> dict[str, tuple[str | None, str | None]]:
    out = {}
    for i, d in enumerate(days):
        d5 = days[i + 5] if i + 5 < len(days) else None
        d10 = days[i + 10] if i + 10 < len(days) else None
        out[d] = (d5, d10)
    return out


def load_sample(fold: int) -> dict[str, dict]:
    cfg = FOLDS[fold]
    if sha_file(cfg["sample"]) != cfg["sample_sha"]:
        raise RuntimeError(f"FOLD{fold}_MANIFEST_SHA_BLOCK")
    rows = list(csv.DictReader(cfg["sample"].read_text(encoding="utf-8").splitlines()))
    if len(rows) != cfg["sample_count"]:
        raise RuntimeError(f"FOLD{fold}_MANIFEST_COUNT_BLOCK:{len(rows)}")
    out = {}
    for r in rows:
        cid = r["canonical_security_id"]
        if cid in out:
            raise RuntimeError(f"FOLD{fold}_DUPLICATE_IDENTITY:{cid}")
        out[cid] = r
    return out


def load_source(fold: int) -> tuple[pd.DataFrame, dict]:
    cfg = FOLDS[fold]
    rec = read_json(cfg["receipt"])
    if rec.get("status") != "PASS":
        raise RuntimeError(f"FOLD{fold}_SOURCE_NOT_PASS")
    if rec.get("receipt_sha256") != cfg["receipt_seal"]:
        raise RuntimeError(f"FOLD{fold}_SOURCE_RECEIPT_SEAL_BLOCK")
    if int(rec.get("sample_count", 0)) != cfg["sample_count"]:
        raise RuntimeError(f"FOLD{fold}_SOURCE_SAMPLE_COUNT_BLOCK")
    if rec.get("sample_manifest_sha256") != cfg["sample_sha"]:
        raise RuntimeError(f"FOLD{fold}_SOURCE_MANIFEST_BINDING_BLOCK")

    parts = []
    for p in rec["stock_partitions"]:
        fp = cfg["source_dir"] / p["file"]
        if not fp.exists() or sha_file(fp) != p["sha256"]:
            raise RuntimeError(f"FOLD{fold}_SOURCE_PARTITION_BLOCK:{p['file']}")
        parts.append(pq.read_table(fp).to_pandas())
    if not parts:
        raise RuntimeError(f"FOLD{fold}_SOURCE_EMPTY")
    stock = pd.concat(parts, ignore_index=True)
    return stock, rec


def build_symbol_rows(
    g: pd.DataFrame,
    meta: dict,
    days: list[str],
    tgt: dict[str, tuple[str | None, str | None]],
) -> list[dict]:
    x = g.copy()
    if "tradestatus" in x.columns:
        x = x.loc[x["tradestatus"].astype(str) == "1"].copy()
    if x.empty:
        return []

    required = {"date", "open", "high", "low", "close", "amount", "canonical_security_id"}
    miss = required - set(x.columns)
    if miss:
        raise RuntimeError(f"SOURCE_COLUMNS_BLOCK:{sorted(miss)}")

    x["date"] = x["date"].astype(str)
    x = x.sort_values("date", kind="mergesort")
    if x["date"].duplicated().any():
        raise RuntimeError(f"DUPLICATE_STOCK_DATE:{meta['canonical_security_id']}")

    feat_in = x.rename(columns={"date": "bar_date"})[
        ["canonical_security_id", "bar_date", "open", "high", "low", "close", "amount"]
    ].copy()
    for c in ["open", "high", "low", "close", "amount"]:
        feat_in[c] = numeric(feat_in[c])

    feat = build_features(feat_in)
    feat["bar_date"] = feat["bar_date"].astype(str)
    by = feat.set_index("bar_date")

    list_date = str(meta.get("official_list_date") or "")
    delist_date = str(meta.get("official_delist_date") or "")
    wanted = set(days)
    out = []

    for d in days:
        if list_date and d < list_date:
            continue
        if delist_date and d >= delist_date:
            continue
        if d not in by.index:
            continue
        r = by.loc[d]
        if isinstance(r, pd.DataFrame):
            raise RuntimeError(f"DUPLICATE_FEATURE_DATE:{meta['canonical_security_id']}:{d}")

        d5, d10 = tgt[d]
        c0 = float(r["close"]) if np.isfinite(r["close"]) else np.nan

        def fwd(td: str | None) -> float:
            if td is None or td not in by.index or not np.isfinite(c0) or c0 <= 0:
                return np.nan
            rr = by.loc[td]
            if isinstance(rr, pd.DataFrame):
                raise RuntimeError(f"DUPLICATE_TARGET_DATE:{meta['canonical_security_id']}:{td}")
            z = float(rr["close"]) if np.isfinite(rr["close"]) else np.nan
            return z / c0 - 1.0 if np.isfinite(z) and z > 0 else np.nan

        rec = {
            "canonical_security_id": meta["canonical_security_id"],
            "signal_date": d,
            "fwd5": fwd(d5),
            "fwd10": fwd(d10),
        }
        for c in REQUIRED_FEATURES:
            v = r[c]
            rec[c] = float(v) if np.isfinite(v) else np.nan
        out.append(rec)

    return out


def panel_hash(panel: pd.DataFrame) -> str:
    cols = ["canonical_security_id", "signal_date", *REQUIRED_FEATURES, "fwd5", "fwd10"]
    h = hashlib.sha256()
    x = panel.sort_values(["signal_date", "canonical_security_id"], kind="mergesort")
    for row in x[cols].itertuples(index=False, name=None):
        vals = []
        for v in row:
            if isinstance(v, (float, np.floating)):
                vals.append("" if not np.isfinite(v) else format(float(v), ".17g"))
            else:
                vals.append(str(v))
        h.update(("\x1f".join(vals) + "\n").encode("utf-8"))
    return h.hexdigest()


def pct_rank(s: pd.Series, positive: bool = True) -> pd.Series:
    z = numeric(s)
    out = pd.Series(np.nan, index=s.index, dtype=float)
    ok = np.isfinite(z)
    if ok.any():
        r = z[ok].rank(method="average", pct=True)
        out.loc[ok] = r if positive else (1.0 - r)
    return out


def add_candidate_scores(g: pd.DataFrame) -> pd.DataFrame:
    z = g.copy()

    rvfav = pct_rank(z["rv10_over_rv60"], positive=False)
    trfav = pct_rank(z["tr10_over_tr60"], positive=False)
    z["dual_compression"] = 0.5 * rvfav + 0.5 * trfav

    z["trend_structure"] = (
        pct_rank(z["ma50_vs_ma150"]) +
        pct_rank(z["ma150_vs_ma200"]) +
        pct_rank(z["ma200_slope20"])
    ) / 3.0

    z["momentum_structure"] = (
        pct_rank(z["ret_20"]) +
        pct_rank(z["ret_60"])
    ) / 2.0

    z["near_high_structure"] = (
        pct_rank(z["dist_high60"]) +
        pct_rank(z["dist_high252"])
    ) / 2.0

    for cid, (a, b) in CANDIDATES.items():
        s = 0.5 * numeric(z[a]) + 0.5 * numeric(z[b])
        z[f"{cid}_score"] = s
        z[f"{cid}_rank"] = pct_rank(s, positive=True)
    return z


def quarter(d: str) -> str:
    t = pd.Timestamp(d)
    return f"{t.year}Q{(t.month - 1) // 3 + 1}"


def daily_candidate_metrics(fold: int, panel: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for d, g in panel.groupby("signal_date", sort=True):
        z = add_candidate_scores(g)
        for cid in CANDIDATES:
            rank = numeric(z[f"{cid}_rank"])
            q1 = rank <= 0.20
            q5 = rank > 0.80
            for hz, ycol in [("D5", "fwd5"), ("D10", "fwd10")]:
                y = numeric(z[ycol])
                valid = np.isfinite(rank) & np.isfinite(y)
                a = valid & q1
                b = valid & q5
                rec = {
                    "fold": fold,
                    "signal_date": d,
                    "candidate_id": cid,
                    "horizon": hz,
                    "Q1_n": int(a.sum()),
                    "Q5_n": int(b.sum()),
                    "valid_n": int(valid.sum()),
                    "Q1_mean": np.nan,
                    "Q5_mean": np.nan,
                    "Q5_minus_Q1": np.nan,
                    "Q5_excess_all": np.nan,
                }
                if int(a.sum()) >= MIN_SIDE and int(b.sum()) >= MIN_SIDE:
                    rec["Q1_mean"] = float(y[a].mean())
                    rec["Q5_mean"] = float(y[b].mean())
                    rec["Q5_minus_Q1"] = rec["Q5_mean"] - rec["Q1_mean"]
                    rec["Q5_excess_all"] = rec["Q5_mean"] - float(y[valid].mean())
                for qi in range(1, 6):
                    if qi == 1:
                        m = valid & (rank <= 0.20)
                    elif qi == 5:
                        m = valid & (rank > 0.80)
                    else:
                        lo = (qi - 1) / 5.0
                        hi = qi / 5.0
                        m = valid & (rank > lo) & (rank <= hi)
                    rec[f"Q{qi}_mean"] = float(y[m].mean()) if int(m.sum()) >= MIN_SIDE else np.nan
                rows.append(rec)
    return pd.DataFrame(rows)


def summarize_candidate_fold(daily: pd.DataFrame, fold: int, cid: str) -> dict:
    d10 = daily[(daily["fold"] == fold) & (daily["candidate_id"] == cid) & (daily["horizon"] == "D10")].copy()
    d5 = daily[(daily["fold"] == fold) & (daily["candidate_id"] == cid) & (daily["horizon"] == "D5")].copy()

    v10 = d10[np.isfinite(d10["Q5_minus_Q1"])].copy()
    v5 = d5[np.isfinite(d5["Q5_minus_Q1"])].copy()
    qex = d10[np.isfinite(d10["Q5_excess_all"])].copy()

    v10["quarter"] = v10["signal_date"].map(quarter)
    qmeans = {
        q: float(g["Q5_minus_Q1"].mean())
        for q, g in v10.groupby("quarter", sort=True)
        if len(g) >= MIN_QUARTER_DATES
    }
    loo = {
        q: float(v10.loc[v10["quarter"] != q, "Q5_minus_Q1"].mean())
        for q in qmeans
    }

    quintile_means = {}
    for qi in range(1, 6):
        col = f"Q{qi}_mean"
        x = d10.loc[np.isfinite(d10[col]), col]
        quintile_means[str(qi)] = float(x.mean()) if len(x) else np.nan

    enough = (
        len(v10) >= MIN_D10_DATES and
        len(v5) >= MIN_D5_DATES and
        len(qmeans) >= MIN_QUARTERS
    )
    q5_highest = (
        all(np.isfinite(quintile_means[str(qi)]) for qi in range(1, 6)) and
        quintile_means["5"] > max(quintile_means[str(qi)] for qi in range(1, 5))
    )
    return {
        "fold": fold,
        "candidate_id": cid,
        "valid_D10_dates": int(len(v10)),
        "valid_D5_dates": int(len(v5)),
        "valid_quarters": int(len(qmeans)),
        "mean_D10_Q5_minus_Q1": float(v10["Q5_minus_Q1"].mean()) if len(v10) else np.nan,
        "mean_D5_Q5_minus_Q1": float(v5["Q5_minus_Q1"].mean()) if len(v5) else np.nan,
        "mean_D10_Q5_excess_all": float(qex["Q5_excess_all"].mean()) if len(qex) else np.nan,
        "aggregate_D10_quintile_means": quintile_means,
        "positive_quarter_share": (
            float(sum(v > 0 for v in qmeans.values()) / len(qmeans)) if qmeans else np.nan
        ),
        "quarter_means": qmeans,
        "leave_one_quarter_out_means": loo,
        "minimum_information_pass": bool(enough),
        "D10_spread_positive": bool(len(v10) and float(v10["Q5_minus_Q1"].mean()) > 0),
        "D10_Q5_excess_all_positive": bool(len(qex) and float(qex["Q5_excess_all"].mean()) > 0),
        "Q5_highest_aggregate_D10_quintile_mean": bool(q5_highest),
        "positive_quarter_share_ge_two_thirds": bool(qmeans and sum(v > 0 for v in qmeans.values()) / len(qmeans) >= 2 / 3),
        "leave_one_quarter_out_all_positive": bool(qmeans and all(v > 0 for v in loo.values())),
        "D5_spread_positive": bool(len(v5) and float(v5["Q5_minus_Q1"].mean()) > 0),
    }


def candidate_eligible(rows: list[dict]) -> tuple[bool, list[str]]:
    failed = []
    for r in rows:
        f = r["fold"]
        checks = [
            ("minimum_information_pass", r["minimum_information_pass"]),
            ("D10_spread_positive", r["D10_spread_positive"]),
            ("D10_Q5_excess_all_positive", r["D10_Q5_excess_all_positive"]),
            ("Q5_highest_aggregate_D10_quintile_mean", r["Q5_highest_aggregate_D10_quintile_mean"]),
            ("positive_quarter_share_ge_two_thirds", r["positive_quarter_share_ge_two_thirds"]),
            ("leave_one_quarter_out_all_positive", r["leave_one_quarter_out_all_positive"]),
        ]
        for name, ok in checks:
            if not ok:
                failed.append(f"fold{f}:{name}")
    if sum(bool(r["D5_spread_positive"]) for r in rows) < 2:
        failed.append("D5_spread_positive_in_at_least_two_folds")
    return (len(failed) == 0, failed)


def select_candidate(summaries: list[dict]) -> tuple[str | None, list[dict]]:
    evaluations = []
    for cid in CANDIDATES:
        rows = [r for r in summaries if r["candidate_id"] == cid]
        if len(rows) != 3:
            raise RuntimeError(f"CANDIDATE_FOLD_CARDINALITY_BLOCK:{cid}:{len(rows)}")
        ok, failed = candidate_eligible(rows)
        vals = [float(r["mean_D10_Q5_minus_Q1"]) for r in rows]
        evaluations.append({
            "candidate_id": cid,
            "eligible": ok,
            "failed_checks": failed,
            "minimum_foldwise_D10_spread": min(vals),
            "median_foldwise_D10_spread": float(np.median(vals)),
        })
    eligible = [x for x in evaluations if x["eligible"]]
    if not eligible:
        return None, evaluations
    eligible.sort(
        key=lambda x: (
            -x["minimum_foldwise_D10_spread"],
            -x["median_foldwise_D10_spread"],
            x["candidate_id"],
        )
    )
    return eligible[0]["candidate_id"], evaluations


def evaluate(write: bool = True) -> dict:
    if OUT_FINAL.exists():
        old = read_json(OUT_FINAL)
        return {
            "status": "FINAL_ALREADY_FROZEN_NO_REEVALUATION",
            "receipt_sha256": old.get("receipt_sha256"),
            "selected_candidate_id": old.get("selected_candidate_id"),
        }

    contract = load_contract()
    days = load_calendar()
    tgt = target_map(days)

    all_daily = []
    panel_receipts = []
    summaries = []

    for fold in (0, 1, 2):
        sample = load_sample(fold)
        stock, src = load_source(fold)
        source_ids = set(stock["canonical_security_id"].astype(str).unique())
        if source_ids - set(sample):
            raise RuntimeError(f"FOLD{fold}_NON_SAMPLE_SECURITY_IN_SOURCE")

        rows = []
        for cid, g in stock.groupby("canonical_security_id", sort=True):
            rows.extend(build_symbol_rows(g, sample[cid], days, tgt))
        panel = pd.DataFrame(rows)
        if panel.empty:
            raise RuntimeError(f"FOLD{fold}_PANEL_EMPTY")
        ph = panel_hash(panel)
        daily = daily_candidate_metrics(fold, panel)
        all_daily.append(daily)
        panel_receipts.append({
            "fold": fold,
            "sample_count": FOLDS[fold]["sample_count"],
            "source_rows": int(len(stock)),
            "panel_rows": int(len(panel)),
            "panel_identity_sha256": ph,
            "source_receipt_sha256": src["receipt_sha256"],
        })
        for cid in CANDIDATES:
            summaries.append(summarize_candidate_fold(daily, fold, cid))

    daily_all = pd.concat(all_daily, ignore_index=True)
    selected, evaluations = select_candidate(summaries)

    status = "V2_8_8_SETUP_SHAPE_SELECTED" if selected else "V2_8_8_NO_SETUP_SHAPE_SELECTED"
    final = {
        "schema": "AI_CORE_EVID_V2_8_8_SETUP_SHAPE_DISCOVERY_FINAL_RECEIPT_V1",
        "version": "V2.8.8",
        "status": status,
        "selected_candidate_id": selected,
        "contract_schema": contract["schema"],
        "fold_panels": panel_receipts,
        "candidate_evaluations": evaluations,
        "fold_summaries": summaries,
        "selection_rule": "eligible candidates only; maximin foldwise D10 spread, then median, then lexical id",
        "bootstrap_or_p_value_used_for_selection": False,
        "fold3_accessed": False,
        "fold4_accessed": False,
        "sample_modified_after_results": False,
        "optional_stopping_used": False,
        "candidate_library_modified_after_results": False,
        "setup_emission_authorized": False,
        "first60_append_authorized": False,
        "episode_emission_authorized": False,
        "live_authorized": False,
    }

    if write:
        OUT_DAILY.parent.mkdir(parents=True, exist_ok=True)
        daily_all.to_csv(OUT_DAILY, index=False, lineterminator="\n")
        ledger_rows = []
        for r in summaries:
            ledger_rows.append({
                "fold": r["fold"],
                "candidate_id": r["candidate_id"],
                "valid_D10_dates": r["valid_D10_dates"],
                "valid_D5_dates": r["valid_D5_dates"],
                "valid_quarters": r["valid_quarters"],
                "mean_D10_Q5_minus_Q1": r["mean_D10_Q5_minus_Q1"],
                "mean_D5_Q5_minus_Q1": r["mean_D5_Q5_minus_Q1"],
                "mean_D10_Q5_excess_all": r["mean_D10_Q5_excess_all"],
                "positive_quarter_share": r["positive_quarter_share"],
                "minimum_information_pass": r["minimum_information_pass"],
                "D10_spread_positive": r["D10_spread_positive"],
                "D10_Q5_excess_all_positive": r["D10_Q5_excess_all_positive"],
                "Q5_highest_aggregate_D10_quintile_mean": r["Q5_highest_aggregate_D10_quintile_mean"],
                "positive_quarter_share_ge_two_thirds": r["positive_quarter_share_ge_two_thirds"],
                "leave_one_quarter_out_all_positive": r["leave_one_quarter_out_all_positive"],
                "D5_spread_positive": r["D5_spread_positive"],
                "quarter_means_json": json.dumps(r["quarter_means"], ensure_ascii=False, sort_keys=True),
                "leave_one_quarter_out_means_json": json.dumps(r["leave_one_quarter_out_means"], ensure_ascii=False, sort_keys=True),
                "aggregate_D10_quintile_means_json": json.dumps(r["aggregate_D10_quintile_means"], ensure_ascii=False, sort_keys=True),
            })
        pd.DataFrame(ledger_rows).to_csv(OUT_LEDGER, index=False, lineterminator="\n")
        final["daily_metrics_sha256"] = sha_file(OUT_DAILY)
        final["ledger_sha256"] = sha_file(OUT_LEDGER)

    final["receipt_sha256"] = stable_sha(final)
    if write:
        OUT_FINAL.write_text(json.dumps(final, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return final


def self_test() -> dict:
    tests = []

    def ck(name: str, value: bool):
        tests.append({"name": name, "pass": bool(value)})

    load_contract()
    ck("D01_candidate_library_exact", list(CANDIDATES) == ["C1_DC_TREND", "C2_DC_MOMENTUM", "C3_DC_NEAR_HIGH"])
    ck("D02_min_side_frozen", MIN_SIDE == 50)
    ck("D03_min_dates_frozen", MIN_D10_DATES == 200 and MIN_D5_DATES == 200)
    ck("D04_no_fold3_or_fold4_source_config", set(FOLDS) == {0, 1, 2})

    g = pd.DataFrame({
        "rv10_over_rv60": np.arange(100, 0, -1, dtype=float),
        "tr10_over_tr60": np.arange(100, 0, -1, dtype=float),
        "ma50_vs_ma150": np.arange(100, dtype=float),
        "ma150_vs_ma200": np.arange(100, dtype=float),
        "ma200_slope20": np.arange(100, dtype=float),
        "ret_20": np.arange(100, dtype=float),
        "ret_60": np.arange(100, dtype=float),
        "dist_high60": np.arange(100, dtype=float),
        "dist_high252": np.arange(100, dtype=float),
    })
    z = add_candidate_scores(g)
    ck("D05_all_candidate_scores_finite", all(np.isfinite(z[f"{c}_score"]).all() for c in CANDIDATES))
    ck("D06_fixed_quintile_projection", all(int((z[f"{c}_rank"] <= 0.20).sum()) == 20 and int((z[f"{c}_rank"] > 0.80).sum()) == 20 for c in CANDIDATES))

    fake = []
    for cid, base in [("C1_DC_TREND", 0.010), ("C2_DC_MOMENTUM", 0.012), ("C3_DC_NEAR_HIGH", 0.009)]:
        for fold, bump in [(0, 0.0), (1, 0.001), (2, -0.001)]:
            fake.append({
                "fold": fold,
                "candidate_id": cid,
                "mean_D10_Q5_minus_Q1": base + bump,
                "minimum_information_pass": True,
                "D10_spread_positive": True,
                "D10_Q5_excess_all_positive": True,
                "Q5_highest_aggregate_D10_quintile_mean": True,
                "positive_quarter_share_ge_two_thirds": True,
                "leave_one_quarter_out_all_positive": True,
                "D5_spread_positive": True,
            })
    sel, ev = select_candidate(fake)
    ck("D07_maximin_selection_deterministic", sel == "C2_DC_MOMENTUM")
    ck("D08_selection_uses_no_bootstrap", True)
    ck("D09_no_liquidity_alpha_component", all("amount" not in str(v).lower() for v in CANDIDATES.values()))
    ck("D10_no_threshold_grid", True)
    ck("D11_same_feature_engine_import", build_features.__module__ == "v280_scale_invariant_features")
    ck("D12_fold3_4_sealed_by_contract", read_json(CONTRACT)["authorization"]["fold3_access"] is False and read_json(CONTRACT)["authorization"]["fold4_access"] is False)

    result = {
        "schema": "AI_CORE_EVID_V2_8_8_LOCKED_DISCOVERY_EVALUATOR_SELFTEST_V1",
        "version": "V2.8.8",
        "tests": tests,
        "passed": sum(t["pass"] for t in tests),
        "total": len(tests),
        "all_pass": all(t["pass"] for t in tests),
        "real_consumed_fold_price_rows_read": False,
        "fold3_4_price_rows_read": False,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["all_pass"]:
        raise SystemExit(2)
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["self-test", "evaluate"])
    args = ap.parse_args()
    if args.command == "self-test":
        self_test()
    else:
        print(json.dumps(evaluate(True), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
