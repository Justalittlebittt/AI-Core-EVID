#!/usr/bin/env python3
"""Bounded source-only coverage audit for an immutable third-party PIT archive.

Does not read prices, outcomes, strategies, or frozen prospective evidence.
A filename-based deterministic sample is NOT a statistically representative universe.
"""
import argparse
import hashlib
import json
import math
import re
import struct
import zipfile
from pathlib import Path

from v31_qlib_pit_archive_probe import ARCHIVE_SHA256, HEADER, DATA, FIELDS, _find_member

PERIODS = (201803, 202003, 202203)
SAMPLE_COUNT = 24
SYMBOL_RE = re.compile(r"/financial/([036]\d{5}\.(?:SH|SZ))/pit\.data$")


def audit(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    if h.hexdigest() != ARCHIVE_SHA256:
        raise ValueError("PINNED_ARCHIVE_DIGEST_MISMATCH")

    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        mapping = json.loads(z.read(_find_member(names, "/financial/fields.json")))["fields"]
        ids = {int(k): v["name"] for k, v in mapping.items() if v.get("name") in FIELDS}
        if set(ids.values()) != set(FIELDS):
            raise ValueError("MISSING_REQUIRED_FIELDS")

        members = [(m.group(1), n) for n in names if (m := SYMBOL_RE.search(n))]
        if len(members) < SAMPLE_COUNT:
            raise ValueError("TOO_FEW_PIT_MEMBERS")
        # Pick sample before opening any individual financial binary, independent of value/outcome.
        selected = sorted(members, key=lambda row: (hashlib.sha256(row[0].encode()).hexdigest(), row[0]))[:SAMPLE_COUNT]
        rows = []
        for symbol, member in selected:
            raw = z.read(member)
            if len(raw) < HEADER.size:
                raise ValueError("TRUNCATED_HEADER:" + symbol)
            _, version, size, _, count, checksum = HEADER.unpack_from(raw)
            if size != DATA.size or len(raw) != HEADER.size + count * size:
                raise ValueError("INVALID_RECORD_LAYOUT:" + symbol)
            if hashlib.sha256(raw[HEADER.size:]).digest() != checksum:
                raise ValueError("INVALID_RECORD_CHECKSUM:" + symbol)
            versions = {}
            for offset in range(HEADER.size, len(raw), size):
                fid, notice_day, report_period, value, _ = DATA.unpack_from(raw, offset)
                if report_period not in PERIODS or fid not in ids or not math.isfinite(value):
                    continue
                key = (report_period, ids[fid])
                versions.setdefault(key, []).append((notice_day, value))
            for period in PERIODS:
                entry = {"symbol": symbol, "period": period, "fields": {}}
                for field in FIELDS:
                    records = sorted(versions.get((period, field), []))
                    first = records[0][0] if records else None
                    # This detects gross impossibility, not timestamp-/revision-level PIT integrity.
                    period_end = int(f"{period // 100}0930")
                    entry["fields"][field] = {
                        "present": bool(records),
                        "versions": len(records),
                        "first_vendor_notice_day": first,
                        "notice_after_quarter_end": bool(first and first > period_end),
                    }
                rows.append(entry)

    total = len(rows) * len(FIELDS)
    present = sum(v["present"] for row in rows for v in row["fields"].values())
    premature = sum(v["present"] and not v["notice_after_quarter_end"]
                    for row in rows for v in row["fields"].values())
    by_period = {
        str(p): {"present": sum(v["present"] for row in rows if row["period"] == p
                                for v in row["fields"].values()),
                 "possible": SAMPLE_COUNT * len(FIELDS)}
        for p in PERIODS
    }
    return {
        "schema": "V31_ARCHIVED_FINANCIAL_SOURCE_COVERAGE_ONLY_V1",
        "archive_sha256": h.hexdigest(),
        "selection_method": "lowest SHA256(symbol) among existing SH/SZ financial pit.data paths; before opening records",
        "selection_is_representative": False,
        "periods": list(PERIODS),
        "symbols": [symbol for symbol, _ in selected],
        "field_slots_present": present,
        "field_slots_total": total,
        "field_slots_premature": premature,
        "by_period": by_period,
        "rows": rows,
        "outcome_or_price_data_read": False,
        "original_filing_pdf_crosschecked": False,
        "vendor_historical_vintages_certified": False,
        "independent_alpha_verified": False,
        "trade_authorized": False,
        "status": "SOURCE_COVERAGE_DESCRIPTIVE_ONLY",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.archive)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("status", "field_slots_present",
          "field_slots_total", "field_slots_premature", "by_period",
          "outcome_or_price_data_read", "trade_authorized")}, ensure_ascii=False))
