#!/usr/bin/env python3
"""One-off archived financial source identity and PIT event timing probe.

No future outcomes, scores, broker or new strategy. Uses a pinned external zip.
"""
import argparse
import bisect
import hashlib
import json
import math
import struct
import zipfile
from pathlib import Path

ARCHIVE_SHA256 = "50d6fbb35634eb858f0e665e4811cbcbdcaccfba1d1e0084e8b7227deae17757"
FIELDS = ("or_yoy", "roe_waa", "profit_dedt", "ocfps")
SECURITIES = ("600519.SH", "300408.SZ")
HEADER = struct.Struct("<8sII16sQ32s")
DATA = struct.Struct("<IIIdQ")


def _find_member(names, suffix):
    found = [x for x in names if x.endswith(suffix)]
    if len(found) != 1:
        raise ValueError(f"EXPECTED_ONE_MEMBER:{suffix}:{len(found)}")
    return found[0]


def _data_versions(raw, ids):
    if len(raw) < HEADER.size:
        raise ValueError("TRUNCATED_PIT_HEADER")
    magic, version, size, generation, count, digest = HEADER.unpack_from(raw)
    if size != DATA.size or len(raw) != HEADER.size + count * size:
        raise ValueError("INVALID_PIT_RECORD_COUNT_OR_SIZE")
    if hashlib.sha256(raw[HEADER.size:]).digest() != digest:
        raise ValueError("PIT_RECORD_HASH_MISMATCH")
    out = []
    for off in range(HEADER.size, len(raw), size):
        fid, day, period, val, next_ref = DATA.unpack_from(raw, off)
        if period == 202303 and fid in ids:
            if not 20231001 <= day <= 20260930:
                raise ValueError("IMPOSSIBLE_DISCLOSURE_TIME")
            if not math.isfinite(val):
                continue
            out.append({"field": ids[fid], "date": str(day), "value": val})
    return {"version": version, "magic": magic.decode("latin1"), "count": count, "period_2023q3": out}


def evaluate_archive(path):
    h = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    if h.hexdigest() != ARCHIVE_SHA256:
        raise ValueError("ARCHIVE_SHA256_DIFFERENT_FROM_PUBLIC_PIN")
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        fields_file = _find_member(names, "/financial/fields.json")
        cal_file = _find_member(names, "/calendars/day.txt")
        field_dict = json.loads(z.read(fields_file))
        definitions = field_dict["fields"]
        matched = {int(fid): obj["name"] for fid, obj in definitions.items() if obj.get("name") in FIELDS}
        if set(matched.values()) != set(FIELDS):
            raise ValueError("MISSING_REQUIRED_FINANCIAL_FIELDS")
        days = [line.strip() for line in z.read(cal_file).decode().splitlines() if line.strip()]
        if days != sorted(set(days)) or len(days) < 3000:
            raise ValueError("CALENDAR_NOT_ORDERED_OR_INCOMPLETE")
        reports = []
        for symbol in SECURITIES:
            name = _find_member(names, "/financial/" + symbol + "/pit.data")
            details = _data_versions(z.read(name), matched)
            values = details.pop("period_2023q3")
            events = {}
            for field in FIELDS:
                records = sorted((r for r in values if r["field"] == field), key=lambda x: x["date"])
                earliest = records[0]["date"] if records else None
                first_session = (days[bisect.bisect_right(days, f"{earliest[:4]}-{earliest[4:6]}-{earliest[6:]}")]
                                 if earliest and bisect.bisect_right(days, f"{earliest[:4]}-{earliest[4:6]}-{earliest[6:]}") < len(days)
                                 else None)
                events[field] = {"n_versions": len(records), "first_vendor_notice_day": earliest,
                                 "conservative_first_usable_session": first_session,
                                 "value_at_2023_11_01": next((r["value"] for r in reversed(records) if r["date"] <= "20231101"), None),
                                 "value_at_2023_09_30": next((r["value"] for r in reversed(records) if r["date"] <= "20230930"), None)}
                if earliest and events[field]["value_at_2023_09_30"] is not None:
                    raise ValueError("Q3_FUTURE_FINANCIAL_VALUE_VISIBLE_BEFORE_PERIOD_END")
            reports.append({"stock": symbol, **details, "fields": events})
        return {"schema": "V31_HF_QLIB_FINANCIAL_SOURCE_ARCHIVE_ONE_SHOT_PROBE_V1",
                "archive_sha256": h.hexdigest(), "archive_size_bytes": path.stat().st_size,
                "field_dictionary_member": fields_file, "tracked_numeric_financial_fields": len(definitions),
                "required_features_present": sorted(FIELDS), "calendar_dates": len(days),
                "first_calendar_day": days[0], "last_calendar_day": days[-1],
                "reports": reports, "outcome_or_price_data_read": False,
                "historical_original_pdf_numbers_authenticated": False,
                "same_day_original_filing_preclose_availability_proven": False,
                "source_vendor_versions_guaranteed_original_as_published": False,
                "buy_eligibility": "NOT_AUTHORIZED", "status": "SOURCE_STRUCTURE_AND_SAMPLE_ONLY"}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--archive", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    result = evaluate_archive(a.archive)
    a.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "calendar_dates": result["calendar_dates"],
                      "fields": result["required_features_present"], "reports": result["reports"],
                      "not_a_strategy_validation": True}, ensure_ascii=False))


if __name__ == "__main__":
    main()
