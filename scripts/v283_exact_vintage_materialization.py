from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import subprocess
import sys
import tempfile
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import duckdb
import numpy as np
import pandas as pd
from huggingface_hub import hf_hub_download

sys.path.insert(0, str(Path(__file__).resolve().parent))
from v280_scale_invariant_features import build_features

PINS_DIR = Path("evidence/v283_source_pins")
STABLE_AUDIT = Path("evidence/V2.8.1_VENDOR_VINTAGE_SYMBOL_AUDIT.csv")
CAL2026 = Path("evidence/V2.7.32_JOINT_A_SHARE_TRADING_CALENDAR_2026.json")
STABLE_BLOB_SHA = "4270eeb58e664b8d1d02a05c547b0d19310ad79a"
FIRST_SIGNAL_DATE = date(2026, 9, 22)
TZ = ZoneInfo("Asia/Shanghai")
SYMBOL_RE = re.compile(r"^(\d{6})\.(SS|SZ)$")
MIN_FACTOR_ROWS = 50

def sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda: f.read(1024 * 1024), b""):
            h.update(b)
    return h.hexdigest()

def stable_json_sha(obj) -> str:
    b = json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(b).hexdigest()

def git_blob_sha(path: Path) -> str:
    p = subprocess.run(["git", "hash-object", str(path)], check=True, capture_output=True, text=True)
    return p.stdout.strip()

def git_creation(path: Path) -> tuple[str, datetime]:
    p = subprocess.run(
        ["git", "log", "--diff-filter=A", "--follow", "--reverse", "--format=%H%x09%cI", "--", str(path)],
        check=True, capture_output=True, text=True
    )
    lines = [x.strip() for x in p.stdout.splitlines() if x.strip()]
    if not lines:
        raise RuntimeError(f"no creation commit for {path}")
    sha, ts = lines[0].split("\t", 1)
    return sha, datetime.fromisoformat(ts)

def parse_dt(v: str) -> datetime:
    return datetime.fromisoformat(str(v).replace("Z", "+00:00"))

def load_calendar() -> list[date]:
    obj = json.loads(CAL2026.read_text(encoding="utf-8"))
    days = [date.fromisoformat(x["date"]) for x in obj["dates"] if x["is_joint_a_share_trading_day"]]
    if len(days) != int(obj["trading_day_count"]):
        raise RuntimeError("2026 calendar count mismatch")
    if len(days) != len(set(days)):
        raise RuntimeError("duplicate 2026 trading dates")
    return days

def target_date(calendar: list[date], d: date, n: int) -> date | None:
    try:
        i = calendar.index(d)
    except ValueError:
        return None
    j = i + n
    return calendar[j] if j < len(calendar) else None

def session_window(d: date) -> tuple[datetime, datetime]:
    close = datetime.combine(d, time(15, 0, 0), TZ)
    cutoff = datetime.combine(d + timedelta(days=1), time(23, 59, 59), TZ)
    return close, cutoff

def load_pin_receipts() -> list[dict]:
    rows = []
    if not PINS_DIR.exists():
        return rows
    for p in sorted(PINS_DIR.glob("*.json")):
        obj = json.loads(p.read_text(encoding="utf-8"))
        commit_sha, committed_at = git_creation(p)
        obj["_path"] = str(p)
        obj["_commit_sha"] = commit_sha
        obj["_committed_at"] = committed_at.isoformat()
        rows.append(obj)
    return rows

def pin_candidates(d: date, receipts: list[dict] | None = None) -> list[dict]:
    close, cutoff = session_window(d)
    rows = receipts if receipts is not None else load_pin_receipts()
    out = []
    for r in rows:
        t = parse_dt(r["_committed_at"]).astimezone(TZ)
        if close < t <= cutoff:
            out.append(r)
    return sorted(out, key=lambda x: (parse_dt(x["_committed_at"]), x.get("_path", "")))

def pin_source(pin: dict, repo_id: str) -> dict:
    rows = [x for x in pin.get("sources", []) if x.get("repo_id") == repo_id]
    if len(rows) != 1:
        raise RuntimeError(f"{repo_id}: expected one source row, got {len(rows)}")
    return rows[0]

def verify_pin_temporal_integrity(pin: dict) -> None:
    commit_time = parse_dt(pin["_committed_at"])
    for row in pin.get("sources", []):
        lm = parse_dt(row["repo_last_modified"])
        if lm > commit_time:
            raise RuntimeError(f"{row['repo_id']}: repo_last_modified after authoritative pin commit")

def materialize_pin(pin: dict) -> tuple[Path, Path]:
    verify_pin_temporal_integrity(pin)
    paths = {}
    for repo_id in ("AlphaDojo/dojo_stock_kline", "AlphaDojo/dojo_benchmark_kline"):
        r = pin_source(pin, repo_id)
        p = Path(hf_hub_download(
            repo_id=repo_id,
            filename=r["target_file"],
            repo_type="dataset",
            revision=r["revision_sha"],
        ))
        actual = sha_file(p)
        if actual != r["target_lfs_sha256"]:
            raise RuntimeError(f"{repo_id}: exact materialization SHA mismatch {actual}")
        paths[repo_id] = p
    return paths["AlphaDojo/dojo_stock_kline"], paths["AlphaDojo/dojo_benchmark_kline"]

def load_stable_symbol_meta(path: Path = STABLE_AUDIT) -> pd.DataFrame:
    if path == STABLE_AUDIT and git_blob_sha(path) != STABLE_BLOB_SHA:
        raise RuntimeError("stable vendor audit git blob mismatch")
    x = pd.read_csv(path, dtype=str).fillna("")
    required = {"symbol", "comparable", "price_stable"}
    if not required.issubset(x.columns):
        raise RuntimeError(f"stable audit columns missing: {required - set(x.columns)}")
    ok = x["comparable"].str.lower().eq("true") & x["price_stable"].str.lower().eq("true")
    x = x.loc[ok, ["symbol"]].copy()
    meta = []
    for sym in x["symbol"]:
        m = SYMBOL_RE.fullmatch(sym)
        if not m:
            raise RuntimeError(f"invalid stable vendor symbol: {sym}")
        code, suffix = m.groups()
        meta.append({
            "symbol": sym,
            "security_code": code,
            "exchange": "SSE" if suffix == "SS" else "SZSE",
        })
    out = pd.DataFrame(meta)
    if path == STABLE_AUDIT and len(out) != 5214:
        raise RuntimeError(f"stable vendor symbol count changed: {len(out)}")
    return out

def load_pit_authority(authority_path: Path, d: date) -> tuple[dict, pd.DataFrame]:
    obj = json.loads(authority_path.read_text(encoding="utf-8"))
    if obj.get("schema") != "AI_CORE_EVID_V2_8_3_PIT_DATE_AUTHORITY_V1":
        raise RuntimeError("PIT date authority schema mismatch")
    if obj.get("signal_date") != d.isoformat():
        raise RuntimeError("PIT date authority signal_date mismatch")
    if obj.get("status") != "PASS":
        raise RuntimeError("PIT date authority status not PASS")
    snap = Path(obj["universe_snapshot_file"])
    if not snap.exists():
        raise RuntimeError("PIT universe snapshot missing")
    if sha_file(snap) != obj["universe_snapshot_sha256"]:
        raise RuntimeError("PIT universe snapshot SHA mismatch")
    u = pd.read_csv(snap, dtype=str).fillna("")
    req = {"canonical_security_id", "exchange", "security_code"}
    if not req.issubset(u.columns):
        raise RuntimeError(f"PIT universe snapshot columns missing: {req - set(u.columns)}")
    if u["canonical_security_id"].duplicated().any():
        raise RuntimeError("PIT universe duplicate canonical_security_id")
    if u.duplicated(["exchange", "security_code"]).any():
        raise RuntimeError("PIT universe duplicate exchange/security_code")
    return obj, u

def eligible_symbol_map(universe: pd.DataFrame, stable_meta: pd.DataFrame) -> pd.DataFrame:
    m = universe[["canonical_security_id", "exchange", "security_code"]].merge(
        stable_meta, on=["exchange", "security_code"], how="inner", validate="one_to_one"
    )
    if m["symbol"].duplicated().any():
        raise RuntimeError("eligible vendor symbol duplicated")
    return m.sort_values("canonical_security_id").reset_index(drop=True)

def sql_lit(v) -> str:
    return "'" + str(v).replace("'", "''") + "'"

def snapshot_max_dates(stock_path: Path, bench_path: Path, stable_symbols: list[str]) -> tuple[date | None, date | None]:
    con = duckdb.connect()
    con.register("stable_symbols", pd.DataFrame({"symbol": stable_symbols}))
    s = con.execute(f"""
      SELECT max(cast(k.bar_time as date))
      FROM read_parquet({sql_lit(stock_path)}) k
      INNER JOIN stable_symbols s ON cast(k.symbol as varchar)=s.symbol
      WHERE cast(k.kline_t as varchar)='1D'
    """).fetchone()[0]
    b = con.execute(f"""
      SELECT max(cast(bar_time as date))
      FROM read_parquet({sql_lit(bench_path)})
      WHERE cast(symbol as varchar)='000300.SS'
        AND cast(kline_t as varchar)='1D'
    """).fetchone()[0]
    con.close()
    return s, b

def load_stock_history(stock_path: Path, mapping: pd.DataFrame, d: date, bars: int = 61) -> pd.DataFrame:
    con = duckdb.connect()
    con.register("eligible_symbols", mapping[["symbol"]])
    q = f"""
      WITH x AS (
        SELECT cast(k.symbol as varchar) symbol,
               cast(k.bar_time as date) bar_date,
               cast(k.open as double) open,
               cast(k.high as double) high,
               cast(k.low as double) low,
               cast(k.close as double) close,
               cast(k.amount as double) amount,
               row_number() OVER (
                 PARTITION BY cast(k.symbol as varchar)
                 ORDER BY cast(k.bar_time as date) DESC
               ) rn
        FROM read_parquet({sql_lit(stock_path)}) k
        INNER JOIN eligible_symbols e ON cast(k.symbol as varchar)=e.symbol
        WHERE cast(k.kline_t as varchar)='1D'
          AND cast(k.bar_time as date) <= DATE {sql_lit(d.isoformat())}
      )
      SELECT symbol,bar_date,open,high,low,close,amount
      FROM x WHERE rn <= {int(bars)}
      ORDER BY symbol,bar_date
    """
    x = con.execute(q).fetchdf()
    con.close()
    if x.duplicated(["symbol", "bar_date"]).any():
        raise RuntimeError("duplicate stock symbol/bar_date in exact snapshot")
    x = x.merge(mapping[["symbol", "canonical_security_id"]], on="symbol", how="left", validate="many_to_one")
    return x

def benchmark_state(bench_path: Path, d: date) -> tuple[str, float, int]:
    con = duckdb.connect()
    b = con.execute(f"""
      SELECT cast(bar_time as date) bar_date, cast(close as double) close
      FROM read_parquet({sql_lit(bench_path)})
      WHERE cast(symbol as varchar)='000300.SS'
        AND cast(kline_t as varchar)='1D'
        AND cast(bar_time as date) <= DATE {sql_lit(d.isoformat())}
      ORDER BY bar_date DESC
      LIMIT 61
    """).fetchdf()
    con.close()
    b = b.sort_values("bar_date").reset_index(drop=True)
    if len(b) < 61 or pd.to_datetime(b["bar_date"]).dt.date.iloc[-1] != d:
        return "UNKNOWN_WARMUP", float("nan"), len(b)
    close = pd.to_numeric(b["close"], errors="coerce")
    lr = np.log(close / close.shift(1)).dropna().to_numpy(float)
    if len(lr) != 60:
        return "UNKNOWN_WARMUP", float("nan"), len(b)
    rv10 = float(np.std(lr[-10:], ddof=0))
    rv60 = float(np.std(lr[-60:], ddof=0))
    if not np.isfinite(rv10) or not np.isfinite(rv60) or rv60 <= 0:
        return "UNKNOWN_WARMUP", float("nan"), len(b)
    ratio = rv10 / rv60
    return ("CALM" if ratio <= 1.0 else "STRESSED"), float(ratio), len(b)

def build_signal_panel(stock_path: Path, mapping: pd.DataFrame, d: date) -> pd.DataFrame:
    x = load_stock_history(stock_path, mapping, d, 61)
    inp = x[["canonical_security_id", "bar_date", "open", "high", "low", "close", "amount"]]
    f = build_features(inp)
    f["bar_date"] = pd.to_datetime(f["bar_date"]).dt.date
    y = f[f["bar_date"] == d][
        ["canonical_security_id", "bar_date", "rv10_over_rv60", "tr10_over_tr60"]
    ].copy()
    sym = mapping.set_index("canonical_security_id")["symbol"]
    y["symbol"] = y["canonical_security_id"].map(sym)
    y = y.rename(columns={"bar_date": "signal_date"})
    return y[["canonical_security_id", "symbol", "signal_date", "rv10_over_rv60", "tr10_over_tr60"]].sort_values(
        "canonical_security_id"
    ).reset_index(drop=True)

def load_endpoint_prices(stock_path: Path, signal_panel: pd.DataFrame, d: date, t: date) -> pd.DataFrame:
    symbols = signal_panel[["canonical_security_id", "symbol"]].drop_duplicates()
    con = duckdb.connect()
    con.register("wanted", symbols[["symbol"]])
    q = f"""
      SELECT cast(k.symbol as varchar) symbol,
             cast(k.bar_time as date) bar_date,
             cast(k.close as double) close
      FROM read_parquet({sql_lit(stock_path)}) k
      INNER JOIN wanted w ON cast(k.symbol as varchar)=w.symbol
      WHERE cast(k.kline_t as varchar)='1D'
        AND cast(k.bar_time as date) IN (DATE {sql_lit(d.isoformat())}, DATE {sql_lit(t.isoformat())})
    """
    z = con.execute(q).fetchdf()
    con.close()
    if z.duplicated(["symbol", "bar_date"]).any():
        raise RuntimeError("duplicate endpoint key in T-vintage snapshot")
    z["bar_date"] = pd.to_datetime(z["bar_date"]).dt.date
    dpx = z[z["bar_date"] == d][["symbol", "close"]].rename(columns={"close": "source_close_d"})
    tpx = z[z["bar_date"] == t][["symbol", "close"]].rename(columns={"close": "source_close_t"})
    out = symbols.merge(dpx, on="symbol", how="left").merge(tpx, on="symbol", how="left")
    out["forward_return"] = out["source_close_t"] / out["source_close_d"] - 1.0
    out["outcome_status"] = np.where(
        np.isfinite(pd.to_numeric(out["forward_return"], errors="coerce")),
        "RESOLVED", "OUTCOME_UNAVAILABLE_NO_SHIFT"
    )
    return out

def write_json(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    unsigned = dict(obj)
    unsigned.pop("receipt_sha256", None)
    obj["receipt_sha256"] = stable_json_sha(unsigned)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

def signal_preflight(d: date, pit_authority: Path | None, calendar: list[date]) -> tuple[str, dict, pd.DataFrame | None]:
    if d < FIRST_SIGNAL_DATE:
        return "BOUNDARY_BLOCKED", {}, None
    if d not in calendar:
        return "CALENDAR_BLOCKED", {}, None
    t5, t10 = target_date(calendar, d, 5), target_date(calendar, d, 10)
    if t5 is None or t10 is None:
        return "CALENDAR_BLOCKED", {}, None
    diag = {"target_date_d5": t5.isoformat(), "target_date_d10": t10.isoformat()}
    if pit_authority is None or not pit_authority.exists():
        return "PIT_AUTHORITY_MISSING", diag, None
    try:
        pit_obj, universe = load_pit_authority(pit_authority, d)
    except Exception as e:
        diag["pit_error"] = str(e)
        return "PIT_AUTHORITY_BLOCKED", diag, None
    diag["pit_authority_sha256"] = sha_file(pit_authority)
    diag["pit_universe_rows"] = int(len(universe))
    diag["pit_universe_snapshot_sha256"] = pit_obj["universe_snapshot_sha256"]
    return "PASS", diag, universe

def run_signal(args) -> None:
    d = date.fromisoformat(args.signal_date)
    out = Path(args.out_dir)
    calendar = load_calendar()
    pre, diag, universe = signal_preflight(d, Path(args.pit_authority) if args.pit_authority else None, calendar)
    receipt = {
        "schema": "AI_CORE_EVID_V2_8_3_SIGNAL_ELIGIBILITY_RECEIPT_V1",
        "version": "V2.8.3",
        "signal_date": d.isoformat(),
        "status": pre,
        **diag,
        "H1_H2_interim_statistics_computed": False,
    }
    receipt_path = out / f"V2.8.3_SIGNAL_ELIGIBILITY_{d.isoformat()}.json"
    if pre != "PASS":
        write_json(receipt_path, receipt)
        print(json.dumps(receipt, ensure_ascii=False, indent=2))
        return

    stable = load_stable_symbol_meta()
    mapping = eligible_symbol_map(universe, stable)
    receipt["stable_vendor_pit_overlap"] = int(len(mapping))
    candidates = pin_candidates(d)
    receipt["candidate_pin_count"] = len(candidates)
    if not candidates:
        receipt["status"] = "SOURCE_PIN_MISSING"
        write_json(receipt_path, receipt)
        print(json.dumps(receipt, ensure_ascii=False, indent=2))
        return

    selected = None
    selected_paths = None
    rejected = []
    stable_symbols = stable["symbol"].tolist()
    for pin in candidates:
        stock, bench = materialize_pin(pin)
        smax, bmax = snapshot_max_dates(stock, bench, stable_symbols)
        if smax == d and bmax == d:
            selected = pin
            selected_paths = (stock, bench)
            break
        rejected.append({
            "pin": pin.get("_path"),
            "stock_max_bar_date": str(smax),
            "benchmark_max_bar_date": str(bmax),
        })

    receipt["rejected_candidate_pins"] = rejected
    if selected is None:
        receipt["status"] = "SOURCE_INELIGIBLE"
        write_json(receipt_path, receipt)
        print(json.dumps(receipt, ensure_ascii=False, indent=2))
        return

    stock, bench = selected_paths
    panel = build_signal_panel(stock, mapping, d)
    state, ratio, bench_rows = benchmark_state(bench, d)
    counts = {
        f: int(np.isfinite(pd.to_numeric(panel[f], errors="coerce")).sum())
        for f in ("rv10_over_rv60", "tr10_over_tr60")
    }
    panel_path = out / f"V2.8.3_SIGNAL_FACTOR_PANEL_{d.isoformat()}.csv"
    panel_path.parent.mkdir(parents=True, exist_ok=True)
    panel.to_csv(panel_path, index=False, lineterminator="\n")

    receipt.update({
        "selected_pin_file": selected["_path"],
        "selected_pin_creation_commit": selected["_commit_sha"],
        "selected_pin_authoritative_observed_at": selected["_committed_at"],
        "source_identity_sha256": selected["source_identity_sha256"],
        "market_state": state,
        "market_rv10_over_rv60": ratio,
        "benchmark_history_rows": bench_rows,
        "factor_finite_counts": counts,
        "signal_panel_rows": int(len(panel)),
        "signal_panel_sha256": sha_file(panel_path),
        "signal_panel_file": str(panel_path),
    })
    if state not in {"CALM", "STRESSED"} or min(counts.values()) < MIN_FACTOR_ROWS:
        receipt["status"] = "FEATURE_DATA_BLOCKED"
    else:
        receipt["status"] = "ELIGIBLE_FEATURE_SOURCE"
    write_json(receipt_path, receipt)
    print(json.dumps(receipt, ensure_ascii=False, indent=2))

def run_outcome(args) -> None:
    d = date.fromisoformat(args.signal_date)
    n = int(args.horizon)
    if n not in {5, 10}:
        raise RuntimeError("horizon must be 5 or 10")
    out = Path(args.out_dir)
    calendar = load_calendar()
    t = target_date(calendar, d, n)
    receipt = {
        "schema": "AI_CORE_EVID_V2_8_3_OUTCOME_MATERIALIZATION_RECEIPT_V1",
        "version": "V2.8.3",
        "signal_date": d.isoformat(),
        "horizon": n,
        "status": "CALENDAR_BLOCKED" if t is None else "PENDING",
        "H1_H2_interim_statistics_computed": False,
    }
    receipt_path = out / f"V2.8.3_OUTCOME_D{n}_{d.isoformat()}.json"
    if t is None:
        write_json(receipt_path, receipt)
        print(json.dumps(receipt, ensure_ascii=False, indent=2))
        return
    receipt["target_date"] = t.isoformat()

    panel_path = Path(args.signal_panel)
    if not panel_path.exists():
        raise RuntimeError("signal factor panel missing")
    panel = pd.read_csv(panel_path, dtype={"canonical_security_id": str, "symbol": str})
    req = {"canonical_security_id", "symbol", "signal_date"}
    if not req.issubset(panel.columns):
        raise RuntimeError(f"signal panel columns missing: {req - set(panel.columns)}")
    if set(panel["signal_date"].astype(str)) != {d.isoformat()}:
        raise RuntimeError("signal panel date mismatch")
    candidates = pin_candidates(t)
    receipt["candidate_pin_count"] = len(candidates)
    if not candidates:
        receipt["status"] = "SOURCE_PIN_MISSING"
        write_json(receipt_path, receipt)
        print(json.dumps(receipt, ensure_ascii=False, indent=2))
        return

    stable = load_stable_symbol_meta()
    stable_symbols = stable["symbol"].tolist()
    selected = None
    stock_path = None
    rejected = []
    for pin in candidates:
        stock, bench = materialize_pin(pin)
        smax, bmax = snapshot_max_dates(stock, bench, stable_symbols)
        if smax == t and bmax == t:
            selected = pin
            stock_path = stock
            break
        rejected.append({
            "pin": pin.get("_path"),
            "stock_max_bar_date": str(smax),
            "benchmark_max_bar_date": str(bmax),
        })
    receipt["rejected_candidate_pins"] = rejected
    if selected is None:
        receipt["status"] = "SOURCE_INELIGIBLE"
        write_json(receipt_path, receipt)
        print(json.dumps(receipt, ensure_ascii=False, indent=2))
        return

    result = load_endpoint_prices(stock_path, panel, d, t)
    result["signal_date"] = d.isoformat()
    result["target_date"] = t.isoformat()
    result["horizon"] = n
    opath = out / f"V2.8.3_OUTCOME_PANEL_D{n}_{d.isoformat()}.csv"
    result.to_csv(opath, index=False, lineterminator="\n")
    finite = int(result["outcome_status"].eq("RESOLVED").sum())
    receipt.update({
        "status": "OUTCOME_READY",
        "selected_pin_file": selected["_path"],
        "selected_pin_creation_commit": selected["_commit_sha"],
        "selected_pin_authoritative_observed_at": selected["_committed_at"],
        "source_identity_sha256": selected["source_identity_sha256"],
        "outcome_panel_file": str(opath),
        "outcome_panel_sha256": sha_file(opath),
        "rows": int(len(result)),
        "resolved_rows": finite,
        "unavailable_rows": int(len(result) - finite),
        "endpoint_rule": "D_AND_T_CLOSE_FROM_SAME_TARGET_SESSION_VINTAGE",
    })
    write_json(receipt_path, receipt)
    print(json.dumps(receipt, ensure_ascii=False, indent=2))

def make_synthetic_snapshot(root: Path, signal_date: date, symbols: list[str], scale: float = 1.0, extra_dates: list[date] | None = None) -> tuple[Path, Path, list[date]]:
    hist = list(pd.bdate_range(end=pd.Timestamp(signal_date), periods=61).date)
    dates = hist + list(extra_dates or [])
    rows = []
    base_returns = np.array([0.01 if i % 2 == 0 else -0.01 for i in range(50)] + [0.002 if i % 2 == 0 else -0.002 for i in range(10)])
    for j, sym in enumerate(symbols):
        close = [100.0 + j]
        for r in base_returns:
            close.append(close[-1] * (1.0 + r * (1.0 + j * 0.0005)))
        for k in range(len(extra_dates or [])):
            close.append(close[-1] * (1.0 + 0.02))
        for d, c in zip(dates, close):
            c *= scale
            rows.append({
                "symbol": sym, "kline_t": "1D", "bar_time": pd.Timestamp(d),
                "open": c * 0.999, "high": c * 1.01, "low": c * 0.99, "close": c, "amount": 1e8 + j
            })
    stock = root / "stock.parquet"
    pd.DataFrame(rows).to_parquet(stock, index=False)

    bclose = [3000.0]
    for r in base_returns:
        bclose.append(bclose[-1] * (1.0 + r))
    for k in range(len(extra_dates or [])):
        bclose.append(bclose[-1] * 1.001)
    brows = [{
        "symbol": "000300.SS", "kline_t": "1D", "bar_time": pd.Timestamp(d),
        "close": c * scale
    } for d, c in zip(dates, bclose)]
    bench = root / "bench.parquet"
    pd.DataFrame(brows).to_parquet(bench, index=False)
    return stock, bench, dates

def self_test() -> None:
    tests = []
    def check(name, cond, detail=None):
        tests.append({"name": name, "pass": bool(cond), "detail": detail})

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        d = date(2026, 6, 30)
        symbols = [f"{i:06d}.SZ" for i in range(1, 71)]
        stock, bench, hist = make_synthetic_snapshot(root, d, symbols)
        universe = pd.DataFrame({
            "canonical_security_id": [f"SZSE:{i:06d}" for i in range(1, 72)],
            "exchange": ["SZSE"] * 71,
            "security_code": [f"{i:06d}" for i in range(1, 72)],
        })
        stable = pd.DataFrame({
            "symbol": symbols,
            "security_code": [f"{i:06d}" for i in range(1, 71)],
            "exchange": ["SZSE"] * 70,
        })
        mapping = eligible_symbol_map(universe, stable)
        check("M01_stable_vendor_exclusion", len(mapping) == 70)

        smax, bmax = snapshot_max_dates(stock, bench, symbols)
        check("M02_exact_signal_max_date", smax == d and bmax == d, [str(smax), str(bmax)])

        panel = build_signal_panel(stock, mapping, d)
        counts = [np.isfinite(panel[x]).sum() for x in ("rv10_over_rv60", "tr10_over_tr60")]
        check("M03_factor_panel_finite", min(counts) == 70, counts)

        state, ratio, n = benchmark_state(bench, d)
        check("M04_market_state_calm", state == "CALM" and ratio < 1.0 and n == 61, [state, ratio, n])

        check("M05_boundary_guard", date(2026, 9, 21) < FIRST_SIGNAL_DATE)

        synthetic_calendar = list(pd.bdate_range("2026-06-01", "2026-07-31").date)
        check("M06_calendar_targets",
              target_date(synthetic_calendar, d, 5) == date(2026, 7, 7)
              and target_date(synthetic_calendar, d, 10) == date(2026, 7, 14))

        t5 = target_date(synthetic_calendar, d, 5)
        extra = [x for x in synthetic_calendar if d < x <= t5]
        tstock, tbench, _ = make_synthetic_snapshot(root / "t5", d, symbols, scale=0.5, extra_dates=extra)
        # Rewrite the target-date close to exactly 1.10x the same-vintage D close.
        z = pd.read_parquet(tstock)
        for sym in symbols:
            dmask = (z["symbol"] == sym) & (pd.to_datetime(z["bar_time"]).dt.date == d)
            tmask = (z["symbol"] == sym) & (pd.to_datetime(z["bar_time"]).dt.date == t5)
            dp = float(z.loc[dmask, "close"].iloc[0])
            z.loc[tmask, ["open", "high", "low", "close"]] = [dp * 1.099, dp * 1.11, dp * 1.09, dp * 1.10]
        z.to_parquet(tstock, index=False)
        outcome = load_endpoint_prices(tstock, panel, d, t5)
        check("M07_same_T_vintage_endpoint_rule",
              np.allclose(outcome["forward_return"].dropna().to_numpy(float), 0.10, atol=1e-12))

        d_source = pd.read_parquet(stock)
        sample_sym = symbols[0]
        d_old = float(d_source[(d_source["symbol"] == sample_sym) & (pd.to_datetime(d_source["bar_time"]).dt.date == d)]["close"].iloc[0])
        t_new = float(z[(z["symbol"] == sample_sym) & (pd.to_datetime(z["bar_time"]).dt.date == t5)]["close"].iloc[0])
        wrong = t_new / d_old - 1.0
        check("M08_cross_vintage_wrong_method_detected", abs(wrong - 0.10) > 0.1, wrong)

        dupe = pd.concat([z, z.iloc[[0]]], ignore_index=True)
        dup_path = root / "dupe.parquet"
        dupe.to_parquet(dup_path, index=False)
        blocked = False
        try:
            load_endpoint_prices(dup_path, panel, d, t5)
        except RuntimeError as e:
            blocked = "duplicate endpoint key" in str(e)
        check("M09_duplicate_endpoint_blocked", blocked)

        pre, _, _ = signal_preflight(date(2026, 9, 21), None, list(pd.bdate_range("2026-01-01", "2026-12-31").date))
        check("M10_pre_activation_signal_blocked", pre == "BOUNDARY_BLOCKED", pre)

        pre2, _, _ = signal_preflight(date(2026, 9, 22), None, list(pd.bdate_range("2026-01-01", "2026-12-31").date))
        check("M11_missing_PIT_blocks_before_download", pre2 == "PIT_AUTHORITY_MISSING", pre2)

        fake_receipts = [
            {"_committed_at": "2026-09-22T07:30:00+00:00", "_path": "a"},
            {"_committed_at": "2026-09-23T01:00:00+00:00", "_path": "b"},
            {"_committed_at": "2026-09-24T01:00:00+00:00", "_path": "c"},
        ]
        cand = pin_candidates(date(2026, 9, 22), fake_receipts)
        check("M12_pin_window_deterministic", [x["_path"] for x in cand] == ["b"], [x["_path"] for x in cand])

    result = {
        "schema": "AI_CORE_EVID_V2_8_3_EXACT_VINTAGE_RUNNER_SELFTEST_V1",
        "tests": tests,
        "passed": sum(1 for x in tests if x["pass"]),
        "total": len(tests),
        "all_pass": all(x["pass"] for x in tests),
    }
    result["receipt_sha256"] = stable_json_sha(result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["all_pass"]:
        raise SystemExit(2)

def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="command", required=True)

    sub.add_parser("self-test")

    s = sub.add_parser("signal")
    s.add_argument("--signal-date", required=True)
    s.add_argument("--pit-authority", default="")
    s.add_argument("--out-dir", default="v283_exact_materialization")

    o = sub.add_parser("outcome")
    o.add_argument("--signal-date", required=True)
    o.add_argument("--horizon", required=True, choices=["5", "10"])
    o.add_argument("--signal-panel", required=True)
    o.add_argument("--out-dir", default="v283_exact_materialization")

    args = ap.parse_args()
    if args.command == "self-test":
        self_test()
    elif args.command == "signal":
        run_signal(args)
    else:
        run_outcome(args)

if __name__ == "__main__":
    main()
