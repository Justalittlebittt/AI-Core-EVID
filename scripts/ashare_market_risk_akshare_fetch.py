"""Fetch free public index daily close snapshots through AKShare/Eastmoney.

Optional acquisition adapter; scientific calculations are in ashare_market_risk_descriptive.py.
Never assert historical point-in-time access from a retrospective download.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import date, datetime, timezone
from pathlib import Path

INDEXES = {"000300": "000300.SH", "000688": "000688.SH"}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--start-date", required=True, help="YYYY-MM-DD")
    p.add_argument("--end-date", required=True, help="YYYY-MM-DD")
    p.add_argument("--output-csv", required=True, type=Path)
    args = p.parse_args()
    start = date.fromisoformat(args.start_date)
    end = date.fromisoformat(args.end_date)
    if start > end:
        raise ValueError("START_DATE_AFTER_END_DATE")
    if args.output_csv.exists():
        raise FileExistsError("IMMUTABLE_SNAPSHOT_OUTPUT_ALREADY_EXISTS")
    import akshare as ak
    from importlib.metadata import version
    collected_at = datetime.now(timezone.utc).isoformat()
    records = []
    counts = {}
    for symbol, index_id in INDEXES.items():
        df = ak.index_zh_a_hist(symbol=symbol, period="daily",
                              start_date=start.strftime("%Y%m%d"),
                              end_date=end.strftime("%Y%m%d"))
        if df is None or df.empty or not {"日期", "收盘"}.issubset(df.columns):
            raise RuntimeError("INDEX_SOURCE_UNAVAILABLE:" + symbol)
        count = 0
        for _, row in df.iterrows():
            trading_day = date.fromisoformat(str(row["日期"])[:10])
            if trading_day < start or trading_day > end:
                raise RuntimeError("INDEX_SOURCE_OUT_OF_QUERY_RANGE:" + symbol)
            records.append({
                "index_id": index_id, "date": trading_day.isoformat(),
                "close": str(row["收盘"]),
                "source_id": "AKSHARE_INDEX_ZH_A_HIST_EASTMONEY",
                "retrieved_at_utc": collected_at
            })
            count += 1
        counts[index_id] = count
    args.output_csv.parent.mkdir(parents=True, exist_ok=True)
    # Write atomically after BOTH index requests complete.
    tmp = args.output_csv.with_name(args.output_csv.name + ".tmp")
    if tmp.exists():
        raise FileExistsError("STALE_TEMPORARY_SNAPSHOT")
    try:
        with tmp.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["index_id","date","close","source_id","retrieved_at_utc"],
                                    lineterminator="\n")
            writer.writeheader()
            writer.writerows(records)
        from ashare_market_risk_descriptive import load_rows
        load_rows(tmp)
        tmp.replace(args.output_csv)
    finally:
        if tmp.exists():
            tmp.unlink()
    sha = hashlib.sha256(args.output_csv.read_bytes()).hexdigest()
    receipt = {
        "schema": "AI_CORE_EVID_ASHARE_INDEX_SOURCE_SNAPSHOT_V1",
        "source": "AKShare.index_zh_a_hist/Eastmoney",
        "akshare_version": version("akshare"),
        "captured_at_utc": collected_at,
        "query_start_date": start.isoformat(),
        "query_end_date": end.isoformat(),
        "rows_per_index": counts,
        "snapshot_sha256": sha,
        "historical_PIT_verified": False,
        "notes": "Free public data; source availability, trading-session coverage and provider revisions require independent validation"
    }
    manifest = args.output_csv.with_name(args.output_csv.name + ".manifest.json")
    manifest.write_text(json.dumps(receipt, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(receipt, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
