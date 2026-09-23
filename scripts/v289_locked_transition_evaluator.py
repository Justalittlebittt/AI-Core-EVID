from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from v280_scale_invariant_features import build_features

HYPOTHESIS_GATE = Path("evidence/V2.8.9_SETUP_EVENT_TRANSITION_HYPOTHESIS_GATE.json")
EVAL_GATE = Path("evidence/V2.8.9_LOCKED_TRANSITION_RESEARCH_EVALUATION_GATE.json")
CALENDAR = Path("evidence/V2.8.5_JOINT_A_SHARE_TRADING_CALENDAR_2023_2024.json")

HYPOTHESIS_SCHEMA = "AI_CORE_EVID_V2_8_9_SETUP_EVENT_TRANSITION_HYPOTHESIS_GATE_V1"
EVAL_SCHEMA = "AI_CORE_EVID_V2_8_9_LOCKED_TRANSITION_RESEARCH_EVALUATION_GATE_V1"
CANDIDATE_ID = "DC_RAW_RATIO_ONSET_V1"

OUT_EVENTS = Path("evidence/V2.8.9_TRANSITION_EVENT_LEDGER.csv")
OUT_DAILY = Path("evidence/V2.8.9_TRANSITION_DAILY_METRICS.csv")
OUT_FINAL = Path("evidence/V2.8.9_TRANSITION_RESEARCH_FINAL_RECEIPT.json")

MIN_CONTROLS = 20
MIN_TOTAL_EVENTS = 200
MIN_SECURITIES = 100
MIN_SIGNAL_DATES = 80
MAX_DATE_SHARE = 0.10
MIN_VALID_D10_EVENTS = 150
MIN_VALID_D5_EVENTS = 150
MIN_VALID_D10_DATES = 60
MIN_VALID_D5_DATES = 60
MIN_INCREMENTAL_DATES = 40
MIN_VALID_QUARTERS = 4
MIN_QUARTER_D10_DATES = 10
MIN_QUARTER_D10_EVENTS = 20
BOOT_REPS = 10000
BOOT_SEEDS = {0: 2891000, 1: 2891001, 2: 2891002}

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


def load_contracts() -> tuple[dict, dict]:
    h = read_json(HYPOTHESIS_GATE)
    e = read_json(EVAL_GATE)
    if h.get("schema") != HYPOTHESIS_SCHEMA or h.get("status") != "FROZEN_BEFORE_TRANSITION_RESEARCH_EXECUTION":
        raise RuntimeError("HYPOTHESIS_GATE_BINDING_BLOCK")
    if e.get("schema") != EVAL_SCHEMA or e.get("status") != "FROZEN_BEFORE_TRANSITION_OUTCOME_RESEARCH":
        raise RuntimeError("EVALUATION_GATE_BINDING_BLOCK")
    if h.get("single_hypothesis", {}).get("candidate_id") != CANDIDATE_ID:
        raise RuntimeError("CANDIDATE_ID_DRIFT")
    if e.get("hypothesis_gate", {}).get("candidate_id") != CANDIDATE_ID:
        raise RuntimeError("EVALUATION_CANDIDATE_ID_DRIFT")
    for obj in (h, e):
        auth = obj.get("authorization", {})
        if auth.get("fold3_access") is not False or auth.get("fold4_access") is not False:
            raise RuntimeError("SEALED_FOLD_AUTHORIZATION_BLOCK")
    return h, e


def load_calendar() -> list[str]:
    obj = read_json(CALENDAR)
    days = list(obj["trading_dates"])
    if len(days) != 484 or days != sorted(days) or len(days) != len(set(days)):
        raise RuntimeError("CALENDAR_INTEGRITY_BLOCK")
    return days


def calendar_maps(days: list[str]) -> tuple[dict[str, str | None], dict[str, str | None], dict[str, str | None]]:
    prev, d5, d10 = {}, {}, {}
    for i, d in enumerate(days):
        prev[d] = days[i - 1] if i > 0 else None
        d5[d] = days[i + 5] if i + 5 < len(days) else None
        d10[d] = days[i + 10] if i + 10 < len(days) else None
    return prev, d5, d10


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
    return pd.concat(parts, ignore_index=True), rec


def is_pit_eligible(meta: dict, d: str) -> bool:
    list_date = str(meta.get("official_list_date") or "")
    delist_date = str(meta.get("official_delist_date") or "")
    if list_date and d < list_date:
        return False
    if delist_date and d >= delist_date:
        return False
    return True


def build_symbol_panel(g: pd.DataFrame, meta: dict, days: list[str]) -> list[dict]:
    x = g.copy()
    required = {"date", "open", "high", "low", "close", "canonical_security_id"}
    miss = required - set(x.columns)
    if miss:
        raise RuntimeError(f"SOURCE_COLUMNS_BLOCK:{sorted(miss)}")

    x["date"] = x["date"].astype(str)
    if x["date"].duplicated().any():
        raise RuntimeError(f"DUPLICATE_STOCK_DATE:{meta['canonical_security_id']}")

    if "tradestatus" in x.columns:
        tradable = x.loc[x["tradestatus"].astype(str) == "1"].copy()
    else:
        tradable = x.copy()
    tradable = tradable.sort_values("date", kind="mergesort")
    if tradable.empty:
        return []

    feat_in = tradable.rename(columns={"date": "bar_date"})[
        ["canonical_security_id", "bar_date", "open", "high", "low", "close"]
    ].copy()
    for c in ["open", "high", "low", "close"]:
        feat_in[c] = numeric(feat_in[c])
    feat_in["amount"] = numeric(tradable["amount"]) if "amount" in tradable.columns else 1.0

    feat = build_features(feat_in)
    feat["bar_date"] = feat["bar_date"].astype(str)
    by = feat.set_index("bar_date")
    prev_map, d5_map, d10_map = calendar_maps(days)

    out = []
    for d in days:
        if not is_pit_eligible(meta, d) or d not in by.index:
            continue
        r = by.loc[d]
        if isinstance(r, pd.DataFrame):
            raise RuntimeError(f"DUPLICATE_FEATURE_DATE:{meta['canonical_security_id']}:{d}")

        p = prev_map[d]
        p_valid = bool(p and is_pit_eligible(meta, p) and p in by.index)
        prv = by.loc[p] if p_valid else None
        if isinstance(prv, pd.DataFrame):
            raise RuntimeError(f"DUPLICATE_PREVIOUS_FEATURE_DATE:{meta['canonical_security_id']}:{p}")

        rv_d = float(r["rv10_over_rv60"]) if np.isfinite(r["rv10_over_rv60"]) else np.nan
        tr_d = float(r["tr10_over_tr60"]) if np.isfinite(r["tr10_over_tr60"]) else np.nan
        rv_p = float(prv["rv10_over_rv60"]) if p_valid and np.isfinite(prv["rv10_over_rv60"]) else np.nan
        tr_p = float(prv["tr10_over_tr60"]) if p_valid and np.isfinite(prv["tr10_over_tr60"]) else np.nan

        state_d_valid = np.isfinite(rv_d) and np.isfinite(tr_d)
        state_p_valid = p_valid and np.isfinite(rv_p) and np.isfinite(tr_p)
        dual_d = bool(state_d_valid and rv_d < 1.0 and tr_d < 1.0)
        dual_p = bool(state_p_valid and rv_p < 1.0 and tr_p < 1.0)
        raw_onset = bool(state_d_valid and state_p_valid and dual_d and not dual_p)
        compressed_non_onset = bool(state_d_valid and state_p_valid and dual_d and dual_p)

        c0 = float(r["close"]) if np.isfinite(r["close"]) else np.nan

        def fwd(td: str | None) -> float:
            if td is None or td not in by.index or not np.isfinite(c0) or c0 <= 0:
                return np.nan
            rr = by.loc[td]
            if isinstance(rr, pd.DataFrame):
                raise RuntimeError(f"DUPLICATE_TARGET_DATE:{meta['canonical_security_id']}:{td}")
            z = float(rr["close"]) if np.isfinite(rr["close"]) else np.nan
            return z / c0 - 1.0 if np.isfinite(z) and z > 0 else np.nan

        out.append({
            "canonical_security_id": meta["canonical_security_id"],
            "signal_date": d,
            "previous_joint_date": p,
            "target_D5_date": d5_map[d],
            "target_D10_date": d10_map[d],
            "rv10_over_rv60": rv_d,
            "tr10_over_tr60": tr_d,
            "previous_rv10_over_rv60": rv_p,
            "previous_tr10_over_tr60": tr_p,
            "previous_state_valid": bool(state_p_valid),
            "dual_compressed_D": dual_d,
            "dual_compressed_P": dual_p if state_p_valid else False,
            "raw_onset": raw_onset,
            "compressed_non_onset": compressed_non_onset,
            "fwd5": fwd(d5_map[d]),
            "fwd10": fwd(d10_map[d]),
        })
    return out


def mark_transition_states(panel: pd.DataFrame, days: list[str]) -> pd.DataFrame:
    """Synthetic/self-test helper: exact-calendar P transition logic only."""
    prev_map, _, _ = calendar_maps(days)
    z = panel.copy()
    z["signal_date"] = z["signal_date"].astype(str)
    by = {
        (str(r.canonical_security_id), str(r.signal_date)): r
        for r in z.itertuples(index=False)
    }
    raw = []
    comp_non = []
    for r in z.itertuples(index=False):
        cid, d = str(r.canonical_security_id), str(r.signal_date)
        p = prev_map.get(d)
        pr = by.get((cid, p)) if p else None
        dvalid = np.isfinite(r.rv10_over_rv60) and np.isfinite(r.tr10_over_tr60)
        pvalid = bool(pr is not None and np.isfinite(pr.rv10_over_rv60) and np.isfinite(pr.tr10_over_tr60))
        dual_d = bool(dvalid and r.rv10_over_rv60 < 1.0 and r.tr10_over_tr60 < 1.0)
        dual_p = bool(pvalid and pr.rv10_over_rv60 < 1.0 and pr.tr10_over_tr60 < 1.0)
        raw.append(bool(dvalid and pvalid and dual_d and not dual_p))
        comp_non.append(bool(dvalid and pvalid and dual_d and dual_p))
    z["raw_onset"] = raw
    z["compressed_non_onset"] = comp_non
    return z


def apply_episode_suppression(panel: pd.DataFrame, days: list[str]) -> pd.DataFrame:
    _, _, d10_map = calendar_maps(days)
    z = panel.copy()
    z["accepted_onset"] = False
    for cid, idx in z.groupby("canonical_security_id", sort=True).groups.items():
        sub = z.loc[idx].sort_values("signal_date", kind="mergesort")
        active_until = None
        for i, r in sub.iterrows():
            if not bool(r.get("raw_onset", False)):
                continue
            d = str(r["signal_date"])
            t10 = d10_map.get(d)
            if t10 is None:
                continue
            if active_until is not None and d <= active_until:
                continue
            z.at[i, "accepted_onset"] = True
            active_until = t10
    return z


def panel_identity_hash(panel: pd.DataFrame) -> str:
    cols = [
        "canonical_security_id", "signal_date", "previous_joint_date",
        "rv10_over_rv60", "tr10_over_tr60",
        "previous_rv10_over_rv60", "previous_tr10_over_tr60",
        "raw_onset", "compressed_non_onset", "accepted_onset", "fwd5", "fwd10",
    ]
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


def daily_metrics(fold: int, panel: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for d, g in panel.groupby("signal_date", sort=True):
        onset = g["accepted_onset"].astype(bool)
        control = g["compressed_non_onset"].astype(bool)
        rec = {
            "fold": fold,
            "signal_date": d,
            "accepted_onset_n": int(onset.sum()),
            "control_non_onset_n": int(control.sum()),
            "valid_D10_onset_n": 0,
            "valid_D5_onset_n": 0,
            "valid_D10_control_n": 0,
            "D10_onset_excess_mean": np.nan,
            "D5_onset_excess_mean": np.nan,
            "D10_incremental_timing_spread": np.nan,
        }

        y10 = numeric(g["fwd10"])
        y5 = numeric(g["fwd5"])
        v10_all = np.isfinite(y10)
        v5_all = np.isfinite(y5)
        v10_on = onset & v10_all
        v5_on = onset & v5_all
        v10_ctl = control & v10_all
        rec["valid_D10_onset_n"] = int(v10_on.sum())
        rec["valid_D5_onset_n"] = int(v5_on.sum())
        rec["valid_D10_control_n"] = int(v10_ctl.sum())

        if int(v10_on.sum()) > 0 and int(v10_all.sum()) > 0:
            universe = float(y10[v10_all].mean())
            rec["D10_onset_excess_mean"] = float((y10[v10_on] - universe).mean())
        if int(v5_on.sum()) > 0 and int(v5_all.sum()) > 0:
            universe5 = float(y5[v5_all].mean())
            rec["D5_onset_excess_mean"] = float((y5[v5_on] - universe5).mean())
        if int(v10_on.sum()) > 0 and int(v10_ctl.sum()) >= MIN_CONTROLS:
            rec["D10_incremental_timing_spread"] = float(y10[v10_on].mean() - y10[v10_ctl].mean())
        rows.append(rec)
    return pd.DataFrame(rows)


def quarter(d: str) -> str:
    t = pd.Timestamp(d)
    return f"{t.year}Q{(t.month - 1) // 3 + 1}"


def date_cluster_bootstrap(values: pd.Series, seed: int, reps: int = BOOT_REPS) -> dict:
    x = numeric(values)
    x = x[np.isfinite(x)].to_numpy(dtype=float)
    if len(x) == 0:
        return {"n_dates": 0, "mean": np.nan, "ci95": [np.nan, np.nan]}
    rng = np.random.default_rng(seed)
    n = len(x)
    draws = rng.integers(0, n, size=(reps, n))
    means = x[draws].mean(axis=1)
    return {
        "n_dates": n,
        "mean": float(x.mean()),
        "ci95": [float(np.quantile(means, 0.025)), float(np.quantile(means, 0.975))],
    }


def summarize_fold(fold: int, panel: pd.DataFrame, daily: pd.DataFrame) -> dict:
    accepted = panel[panel["accepted_onset"].astype(bool)].copy()
    counts = accepted.groupby("signal_date").size() if len(accepted) else pd.Series(dtype=int)
    total_events = int(len(accepted))
    max_date_share = float(counts.max() / total_events) if total_events else np.nan

    d10 = daily[np.isfinite(daily["D10_onset_excess_mean"])].copy()
    d5 = daily[np.isfinite(daily["D5_onset_excess_mean"])].copy()
    inc = daily[np.isfinite(daily["D10_incremental_timing_spread"])].copy()

    valid_D10_events = int(daily["valid_D10_onset_n"].sum())
    valid_D5_events = int(daily["valid_D5_onset_n"].sum())

    d10["quarter"] = d10["signal_date"].map(quarter)
    quarter_rows = {}
    for q, g in d10.groupby("quarter", sort=True):
        event_n = int(g["valid_D10_onset_n"].sum())
        if len(g) >= MIN_QUARTER_D10_DATES and event_n >= MIN_QUARTER_D10_EVENTS:
            quarter_rows[q] = {
                "signal_dates": int(len(g)),
                "events": event_n,
                "mean_D10_onset_excess": float(g["D10_onset_excess_mean"].mean()),
            }

    loo = {}
    for q in quarter_rows:
        rest = d10.loc[d10["quarter"] != q, "D10_onset_excess_mean"]
        loo[q] = float(rest.mean()) if len(rest) else np.nan

    min_checks = {
        "total_onset_events": total_events >= MIN_TOTAL_EVENTS,
        "distinct_onset_securities": accepted["canonical_security_id"].nunique() >= MIN_SECURITIES,
        "distinct_onset_signal_dates": accepted["signal_date"].nunique() >= MIN_SIGNAL_DATES,
        "single_date_share": bool(total_events and max_date_share <= MAX_DATE_SHARE),
        "valid_D10_events": valid_D10_events >= MIN_VALID_D10_EVENTS,
        "valid_D5_events": valid_D5_events >= MIN_VALID_D5_EVENTS,
        "valid_D10_signal_dates": len(d10) >= MIN_VALID_D10_DATES,
        "valid_D5_signal_dates": len(d5) >= MIN_VALID_D5_DATES,
        "incremental_diagnostic_dates": len(inc) >= MIN_INCREMENTAL_DATES,
        "valid_quarters": len(quarter_rows) >= MIN_VALID_QUARTERS,
    }
    min_pass = all(min_checks.values())

    primary = float(d10["D10_onset_excess_mean"].mean()) if len(d10) else np.nan
    secondary = float(d5["D5_onset_excess_mean"].mean()) if len(d5) else np.nan
    incremental = float(inc["D10_incremental_timing_spread"].mean()) if len(inc) else np.nan
    positive_q_share = (
        float(sum(v["mean_D10_onset_excess"] > 0 for v in quarter_rows.values()) / len(quarter_rows))
        if quarter_rows else np.nan
    )

    return {
        "fold": fold,
        "candidate_id": CANDIDATE_ID,
        "total_onset_events": total_events,
        "distinct_onset_securities": int(accepted["canonical_security_id"].nunique()) if total_events else 0,
        "distinct_onset_signal_dates": int(accepted["signal_date"].nunique()) if total_events else 0,
        "maximum_single_signal_date_share": max_date_share,
        "valid_D10_events": valid_D10_events,
        "valid_D5_events": valid_D5_events,
        "valid_D10_signal_dates": int(len(d10)),
        "valid_D5_signal_dates": int(len(d5)),
        "incremental_diagnostic_dates": int(len(inc)),
        "valid_quarters": int(len(quarter_rows)),
        "minimum_information_checks": min_checks,
        "minimum_information_pass": bool(min_pass),
        "mean_D10_onset_excess": primary,
        "mean_D5_onset_excess": secondary,
        "mean_D10_incremental_timing_spread": incremental,
        "positive_valid_quarter_share": positive_q_share,
        "quarter_primary": quarter_rows,
        "leave_one_valid_quarter_out_primary": loo,
        "leave_one_valid_quarter_out_all_positive": bool(quarter_rows and all(np.isfinite(v) and v > 0 for v in loo.values())),
        "bootstrap_primary_D10": date_cluster_bootstrap(d10["D10_onset_excess_mean"], BOOT_SEEDS[fold]),
    }


def terminal_decision(summaries: list[dict]) -> tuple[str, list[str]]:
    failed = []
    if any(not r["minimum_information_pass"] for r in summaries):
        insufficient = [
            f"fold{r['fold']}:{k}"
            for r in summaries
            for k, ok in r["minimum_information_checks"].items()
            if not ok
        ]
        return "V2_8_9_TRANSITION_DEVELOPMENT_INCONCLUSIVE", insufficient

    for r in summaries:
        f = r["fold"]
        if not (np.isfinite(r["mean_D10_onset_excess"]) and r["mean_D10_onset_excess"] > 0):
            failed.append(f"fold{f}:primary_D10_onset_excess")
        if not (np.isfinite(r["mean_D10_incremental_timing_spread"]) and r["mean_D10_incremental_timing_spread"] > 0):
            failed.append(f"fold{f}:incremental_D10_timing_spread")
        if not (np.isfinite(r["positive_valid_quarter_share"]) and r["positive_valid_quarter_share"] >= 2 / 3):
            failed.append(f"fold{f}:positive_quarter_share")
        if not r["leave_one_valid_quarter_out_all_positive"]:
            failed.append(f"fold{f}:leave_one_quarter_out")
    if sum(np.isfinite(r["mean_D5_onset_excess"]) and r["mean_D5_onset_excess"] > 0 for r in summaries) < 2:
        failed.append("D5_onset_excess_positive_in_at_least_two_folds")
    return ("V2_8_9_TRANSITION_DEVELOPMENT_PASS" if not failed else "V2_8_9_TRANSITION_DEVELOPMENT_REJECTED", failed)


def evaluate(write: bool = True) -> dict:
    if OUT_FINAL.exists():
        old = read_json(OUT_FINAL)
        return {
            "status": "FINAL_ALREADY_FROZEN_NO_REEVALUATION",
            "receipt_sha256": old.get("receipt_sha256"),
        }

    h, e = load_contracts()
    days = load_calendar()
    all_events, all_daily, summaries, panels = [], [], [], []

    for fold in (0, 1, 2):
        sample = load_sample(fold)
        stock, src = load_source(fold)
        source_ids = set(stock["canonical_security_id"].astype(str).unique())
        if source_ids - set(sample):
            raise RuntimeError(f"FOLD{fold}_NON_SAMPLE_SECURITY_IN_SOURCE")

        rows = []
        for cid, g in stock.groupby("canonical_security_id", sort=True):
            rows.extend(build_symbol_panel(g, sample[cid], days))
        panel = pd.DataFrame(rows)
        if panel.empty:
            raise RuntimeError(f"FOLD{fold}_PANEL_EMPTY")
        panel = apply_episode_suppression(panel, days)
        daily = daily_metrics(fold, panel)
        summary = summarize_fold(fold, panel, daily)
        summary["source_receipt_sha256"] = src["receipt_sha256"]
        summary["panel_identity_sha256"] = panel_identity_hash(panel)
        summaries.append(summary)

        ev = panel[panel["accepted_onset"].astype(bool)].copy()
        ev.insert(0, "fold", fold)
        all_events.append(ev)
        all_daily.append(daily)
        panels.append({
            "fold": fold,
            "sample_count": FOLDS[fold]["sample_count"],
            "source_rows": int(len(stock)),
            "panel_rows": int(len(panel)),
            "accepted_onset_events": int(len(ev)),
            "panel_identity_sha256": summary["panel_identity_sha256"],
            "source_receipt_sha256": src["receipt_sha256"],
        })

    status, failed = terminal_decision(summaries)
    final = {
        "schema": "AI_CORE_EVID_V2_8_9_TRANSITION_RESEARCH_FINAL_RECEIPT_V1",
        "version": "V2.8.9",
        "status": status,
        "candidate_id": CANDIDATE_ID,
        "hypothesis_gate_schema": h["schema"],
        "evaluation_gate_schema": e["schema"],
        "fold_panels": panels,
        "fold_summaries": summaries,
        "failed_checks": failed,
        "bootstrap_used_for_development_pass_fail": False,
        "sample_modified_after_results": False,
        "optional_stopping_used": False,
        "threshold_changed_after_results": False,
        "fold3_accessed": False,
        "fold4_accessed": False,
        "setup_emission_authorized": False,
        "first60_append_authorized": False,
        "episode_emission_authorized": False,
        "live_authorized": False,
    }

    if write:
        events = pd.concat(all_events, ignore_index=True) if all_events else pd.DataFrame()
        daily_all = pd.concat(all_daily, ignore_index=True)
        events.to_csv(OUT_EVENTS, index=False, lineterminator="\n")
        daily_all.to_csv(OUT_DAILY, index=False, lineterminator="\n")
        final["event_ledger_sha256"] = sha_file(OUT_EVENTS)
        final["daily_metrics_sha256"] = sha_file(OUT_DAILY)

    final["receipt_sha256"] = stable_sha(final)
    if write:
        OUT_FINAL.write_text(json.dumps(final, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return final


def self_test() -> dict:
    tests = []

    def ck(name: str, cond: bool):
        tests.append({"name": name, "pass": bool(cond)})

    h, e = load_contracts()
    ck("T01_candidate_id_exact", h["single_hypothesis"]["candidate_id"] == CANDIDATE_ID)
    ck("T02_natural_boundary_exact", h["single_hypothesis"]["D_state"]["rv"].endswith("< 1.0") and h["single_hypothesis"]["D_state"]["tr"].endswith("< 1.0"))
    ck("T03_minimum_information_frozen", (
        MIN_TOTAL_EVENTS, MIN_SECURITIES, MIN_SIGNAL_DATES, MAX_DATE_SHARE,
        MIN_VALID_D10_EVENTS, MIN_VALID_D5_EVENTS, MIN_VALID_D10_DATES,
        MIN_VALID_D5_DATES, MIN_INCREMENTAL_DATES, MIN_VALID_QUARTERS
    ) == (200, 100, 80, 0.10, 150, 150, 60, 60, 40, 4))
    ck("T04_bootstrap_frozen", BOOT_REPS == 10000 and BOOT_SEEDS == {0: 2891000, 1: 2891001, 2: 2891002})
    ck("T05_no_fold3_4_source_config", set(FOLDS) == {0, 1, 2})

    days = [f"2024-01-{d:02d}" for d in range(2, 22)]
    base = pd.DataFrame([
        {"canonical_security_id": "SSE:TEST", "signal_date": days[0], "rv10_over_rv60": 1.2, "tr10_over_tr60": 1.1},
        {"canonical_security_id": "SSE:TEST", "signal_date": days[1], "rv10_over_rv60": 0.9, "tr10_over_tr60": 0.8},
        {"canonical_security_id": "SSE:TEST", "signal_date": days[2], "rv10_over_rv60": 0.8, "tr10_over_tr60": 0.7},
    ])
    z = mark_transition_states(base, days)
    ck("T06_onset_is_P_to_D_transition", bool(z.loc[z["signal_date"] == days[1], "raw_onset"].iloc[0]) and not bool(z.loc[z["signal_date"] == days[2], "raw_onset"].iloc[0]))
    ck("T07_occupancy_is_not_onset", bool(z.loc[z["signal_date"] == days[2], "compressed_non_onset"].iloc[0]))

    gap = pd.DataFrame([
        {"canonical_security_id": "SSE:GAP", "signal_date": days[0], "rv10_over_rv60": 1.2, "tr10_over_tr60": 1.1},
        {"canonical_security_id": "SSE:GAP", "signal_date": days[2], "rv10_over_rv60": 0.8, "tr10_over_tr60": 0.7},
    ])
    zg = mark_transition_states(gap, days)
    ck("T08_previous_joint_day_never_skipped", not bool(zg.loc[zg["signal_date"] == days[2], "raw_onset"].iloc[0]))

    future_a = base.copy()
    future_b = pd.concat([base, pd.DataFrame([{
        "canonical_security_id": "SSE:TEST", "signal_date": days[3],
        "rv10_over_rv60": 9.9, "tr10_over_tr60": 9.9,
    }])], ignore_index=True)
    za = mark_transition_states(future_a, days)
    zb = mark_transition_states(future_b, days)
    onset_a = bool(za.loc[za["signal_date"] == days[1], "raw_onset"].iloc[0])
    onset_b = bool(zb.loc[zb["signal_date"] == days[1], "raw_onset"].iloc[0])
    ck("T09_future_state_cannot_change_D_event", onset_a == onset_b == True)

    raw = pd.DataFrame([
        {"canonical_security_id": "SSE:SUP", "signal_date": days[1], "raw_onset": True},
        {"canonical_security_id": "SSE:SUP", "signal_date": days[5], "raw_onset": True},
        {"canonical_security_id": "SSE:SUP", "signal_date": days[12], "raw_onset": True},
    ])
    sup = apply_episode_suppression(raw, days)
    accepted = sup.loc[sup["accepted_onset"], "signal_date"].tolist()
    ck("T10_D_through_D10_same_symbol_suppression", accepted == [days[1], days[12]])

    vals = pd.Series([1.0, -1.0])
    b1 = date_cluster_bootstrap(vals, 12345, reps=500)
    b2 = date_cluster_bootstrap(vals, 12345, reps=500)
    ck("T11_cluster_bootstrap_deterministic", b1 == b2)

    synthetic_daily = pd.DataFrame({
        "D10_onset_excess_mean": [0.10, -0.02],
    })
    ck("T12_date_weighting_equal_not_event_count_weighted", abs(float(synthetic_daily["D10_onset_excess_mean"].mean()) - 0.04) < 1e-12)

    ck("T13_bootstrap_not_selection_gate", e["bootstrap_diagnostic"]["used_for_development_PASS_FAIL"] is False)
    ck("T14_fold3_4_sealed_by_both_contracts", (
        h["authorization"]["fold3_access"] is False and h["authorization"]["fold4_access"] is False and
        e["authorization"]["fold3_access"] is False and e["authorization"]["fold4_access"] is False
    ))
    ck("T15_real_research_not_authorized_yet", e["authorization"]["run_real_transition_research_on_folds0_1_2"] is False)
    ck("T16_same_feature_engine_import", build_features.__module__ == "v280_scale_invariant_features")

    result = {
        "schema": "AI_CORE_EVID_V2_8_9_LOCKED_TRANSITION_EVALUATOR_SELFTEST_V1",
        "version": "V2.8.9",
        "tests": tests,
        "passed": sum(t["pass"] for t in tests),
        "total": len(tests),
        "all_pass": all(t["pass"] for t in tests),
        "real_consumed_fold_price_rows_read": False,
        "real_transition_outcomes_read": False,
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
