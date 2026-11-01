#!/usr/bin/env python3
"""One-time expansion of the already frozen 2x128 original-report source cohort.

Reuses verified first 12 per year without re-query and the existing strict
PDF table parser for remaining 116+116. Captures no prices or future outcomes.
Later vendor values never become historical financial features. Retrospective
2026-retrieved original PDFs are not certified original release-time bytes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

from v29_2023_2024_original_filing_discovery_256 import load_frozen_frames
from v29_prior_year_original_table_batch_24 import (
    OFFICIAL, VENDOR, FIELDS, one, sha,
)
from v29_original_table_reporting_precision import UNIT_SCALE

ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT / "research/v29_original_table_24_20261031/FIXED_24_ORIGINAL_YEAR_TABLE_FIELDS.json"
PRECISION = ROOT / "research/v29_original_table_24_20261031/PRECISION_RECONCILIATION.json"
SHARD_SIZE = 58
SHARD_COUNT = 4
PILOT_PER_YEAR = 12
SCHEMA = "V29_ORIGINAL_256_SOURCE_ONLY_FINANCIAL_FRAME_V1"


def canonical(data):
    return json.dumps(data, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def load_population():
    frozen, frame_hash = load_frozen_frames()
    official_bytes, vendor_bytes = OFFICIAL.read_bytes(), VENDOR.read_bytes()
    official, vendor = json.loads(official_bytes), json.loads(vendor_bytes)
    pilot_bytes, precision_bytes = PILOT.read_bytes(), PRECISION.read_bytes()
    pilot, precision = json.loads(pilot_bytes), json.loads(precision_bytes)
    if (original := official.get("schema")) != "V29_2023_2024_2X128_ORIGINAL_ANNUAL_REPORT_DISCOVERY_V1":
        raise ValueError("FROZEN_ORIGINAL_METADATA_SCHEMA_CHANGED:" + str(original))
    if (vendor.get("schema") != "V29_FY2022_FY2023_2X128_RETROSPECTIVE_VENDOR_FINANCIAL_SOURCE_V1"
            or official["sealed_prequery_cohorts_manifest_sha256"] != frame_hash
            or vendor["prequery_historical_frame_sha256"] != frame_hash
            or len(frozen["cohorts"]) != len(official["cohorts"]) != 2):
        raise ValueError("FROZEN_COHORT_OR_VENDOR_SOURCE_IDENTITY_CHANGED")
    if (pilot.get("schema") != "V29_PRIOR_2023_2024_FIXED_24_PDF_CURRENT_YEAR_FIELD_AUDIT_V1"
            or len(pilot.get("rows", [])) != 24
            or precision.get("underlying_frozen_24_current_year_source_evidence_sha256") != sha(pilot_bytes)
            or precision.get("confirmed_after_source_unit_rounding_review") != 3
            or pilot.get("no_historical_or_future_price_outcomes_queried") is not True):
        raise ValueError("PREVIOUS_24_ORIGINAL_EVIDENCE_CHANGED")

    all_targets, pilot_targets, remainder = [], [], []
    for fr, meta, fin in zip(frozen["cohorts"], official["cohorts"], vendor["cohorts"]):
        if (fr["cohort_id"] != meta["cohort_id"] or fr["cohort_id"] != fin["cohort_id"]
                or len(fr["selected_ids"]) != 128 or len(meta["rows"]) != 128
                or len(fin["rows"]) != 128):
            raise ValueError("COHORT_128_IDENTITY_OR_ORDER_CHANGED")
        bymeta = {x["security_id"]: x for x in meta["rows"]}
        byvendor = {x["security_id"]: x for x in fin["rows"]}
        if len(bymeta) != 128 or len(byvendor) != 128:
            raise ValueError("DUPLICATE_SOURCE_ISSUER")
        for i, sid in enumerate(fr["selected_ids"]):
            if sid not in bymeta or sid not in byvendor:
                raise ValueError("SOURCE_COHORT_NOT_COMPLETE")
            target = {
                "security_id": sid, "cohort_id": fr["cohort_id"],
                "fiscal_year": int(fr["report_period_end"][:4]),
                "expected_issued_year": fr["expected_issuer_publication_year"],
                "original_metadata": bymeta[sid],
                "retrospective_vendor": byvendor[sid],
            }
            all_targets.append(target)
            (pilot_targets if i < PILOT_PER_YEAR else remainder).append(target)
    if len(all_targets) != 256 or len(pilot_targets) != 24 or len(remainder) != 232:
        raise ValueError("SOURCE_256_POPULATION_SIZE_DRIFT")
    if len({(x["fiscal_year"], x["security_id"]) for x in all_targets}) != 256:
        raise ValueError("FROZEN_256_ISSUER_YEAR_DUPLICATE")
    for stored, target in zip(pilot["rows"], pilot_targets):
        chosen = target["original_metadata"].get("chosen")
        if (stored["security_id"] != target["security_id"]
                or stored["fiscal_year"] != target["fiscal_year"]
                or stored.get("official_announcement_day") !=
                (chosen["notice_day"] if chosen else None)
                or stored.get("official_original_pdf_url") !=
                (chosen["original_pdf_url"] if chosen else None)):
            raise ValueError("PREVIOUS_24_SOURCE_IDENTITY_DRIFT")
    return all_targets, pilot["rows"], remainder, {
        "frozen_membership_source_sha256": frame_hash,
        "2023_2024_original_discovery_sha256": sha(official_bytes),
        "2026_retrieved_vendor_metadata_sha256": sha(vendor_bytes),
        "first_24_original_source_sha256": sha(pilot_bytes),
        "first_24_precision_audit_sha256": sha(precision_bytes),
    }


def capture_shard(shard: int, fetch=None):
    if type(shard) is not int or not 0 <= shard < SHARD_COUNT:
        raise ValueError("INVALID_FIXED_SOURCE_SHARD")
    _, _, remaining, hashes = load_population()
    selected = remaining[shard * SHARD_SIZE:(shard + 1) * SHARD_SIZE]
    if len(selected) != SHARD_SIZE:
        raise ValueError("FROZEN_SHARD_PARTITION_INVALID")
    if fetch is None:
        from v29_original_filing_pdf_proof import fetch_binary
        fetch = fetch_binary
    rows = []
    for i, t in enumerate(selected, 1):
        r = one(t, fetch)
        rows.append(r)
        print("ORIGINAL256 %d/4 %02d/58 %s %s" % (
            shard + 1, i, t["security_id"], r["status"]), flush=True)
    return {
        "schema": "V29_ORIGINAL_256_SOURCE_REMAINING_SHARD_V1",
        "shard": shard, "first_remaining_index": shard * SHARD_SIZE,
        "source_manifest_hashes": hashes,
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "rows": rows,
        "original_pdf_raw_bytes_archived_by_this_job": False,
        "no_price_or_outcome_queries": True,
        "live_buy_eligibility": "NOT_AUTHORIZED",
    }


def original_values(row):
    values, pages, missing = {}, {}, []
    for field in FIELDS:
        source = row.get("field_sources", {}).get(field)
        if (not row.get("pdf_original_current_year_field_source")
                or not source or source.get("original_current_year_table_source_status")
                != "UNIQUE_FISCAL_YEAR_TABLE_CELL_EXTRACTED"):
            missing.append(field)
            continue
        value = Decimal(str(source.get("original_current_year_table_value")))
        evidence = source.get("original_pdf_table_evidence") or []
        if not value.is_finite() or not evidence:
            raise ValueError("SOURCE_FIELD_MISSING_OR_INVALID_ORIGINAL_CELL")
        for cell in evidence:
            scale = UNIT_SCALE.get(cell.get("unit_evidence"))
            if (scale is None or cell.get("financial_field") != field
                    or cell.get("fiscal_year_column_header") !=
                    str(row["fiscal_year"]) + "年"
                    or Decimal(str(cell.get("table_cell_numeric"))) * scale != value):
                raise ValueError("ORIGINAL_PDF_FIELD_YEAR_UNIT_OR_VALUE_CONFLICT")
        values[field] = str(value)
        pages[field] = sorted({x["source_pdf_page_1based"] for x in evidence})
    complete = len(values) == len(FIELDS)
    if complete and (not row.get("pdf_sha256_2026_retrieval")
                     or not row.get("official_announcement_day")):
        raise ValueError("COMPLETE_PDF_CELL_VALUES_WITHOUT_PDF_IDENTITY")
    return values, pages, missing, complete


def merge_shards(shards):
    all_targets, pilot, remaining, hashes = load_population()
    if len(shards) != SHARD_COUNT:
        raise ValueError("REQUIRE_ALL_FOUR_FIXED_SOURCE_SHARDS")
    captured = []
    for index, shard in enumerate(shards):
        if (shard.get("schema") != "V29_ORIGINAL_256_SOURCE_REMAINING_SHARD_V1"
                or shard.get("shard") != index
                or shard.get("first_remaining_index") != index * SHARD_SIZE
                or shard.get("source_manifest_hashes") != hashes
                or shard.get("no_price_or_outcome_queries") is not True
                or shard.get("live_buy_eligibility") != "NOT_AUTHORIZED"
                or len(shard.get("rows", [])) != SHARD_SIZE):
            raise ValueError("INCOMPLETE_OR_CHANGED_SOURCE_SHARD")
        for r, t in zip(shard["rows"],
                        remaining[index * SHARD_SIZE:(index + 1) * SHARD_SIZE]):
            if (r.get("security_id") != t["security_id"]
                    or r.get("fiscal_year") != t["fiscal_year"]
                    or r.get("live_buy_eligibility") != "NOT_AUTHORIZED"):
                raise ValueError("SHARD_ROW_MISMATCH_OR_TRADING_AUTHORITY")
            chosen = t["original_metadata"].get("chosen")
            if (r.get("official_announcement_day") !=
                    (chosen["notice_day"] if chosen else None)
                    or r.get("official_original_pdf_url") !=
                    (chosen["original_pdf_url"] if chosen else None)):
                raise ValueError("SHARD_ORIGINAL_ANNOUNCEMENT_CHANGED")
        captured.extend(shard["rows"])

    byid = {(r["security_id"], r["fiscal_year"]): r
            for r in pilot + captured}
    if len(byid) != 256:
        raise ValueError("DUPLICATE_OR_MISSING_ORIGINAL_256")
    ordered = []
    fields, statuses = Counter(), Counter()
    full_pdf_count = 0
    for t in all_targets:
        sid, year = t["security_id"], t["fiscal_year"]
        source = byid[sid, year]
        values, pages, missing, complete = original_values(source)
        statuses[source["status"]] += 1
        if source.get("pdf_original_current_year_field_source"):
            full_pdf_count += 1
        for f in values:
            fields[f] += 1
        ordered.append({
            "security_id": sid, "fiscal_year": year,
            "original_report_notice_date": source.get("official_announcement_day"),
            "original_report_pdf_url": source.get("official_original_pdf_url"),
            "original_pdf_sha256_captured_in_2026":
                source.get("pdf_sha256_2026_retrieval"),
            "original_report_source_status": source["status"],
            "original_year_table_values": values,
            "source_table_pages": pages,
            "missing_original_year_fields": missing,
            "four_original_fields_complete": complete,
            "historical_release_time_pdf_bytes_certified": False,
            "strict_historical_pit_certified": False,
            "strategy_alpha_validated": False,
            "live_buy_eligibility": "NOT_AUTHORIZED",
        })
    if len(ordered) != 256:
        raise ValueError("SOURCE_256_FRAME_COUNT_INVALID")
    source_receipt = {
        "schema": "V29_ORIGINAL_256_SOURCE_PDF_TABLE_EVIDENCE_V1",
        "manifest_sha256": hashes,
        "sample_size": 256,
        "reused_frozen_first_24": True,
        "new_source_issuer_year_count": 232,
        "source_pdf_bytes_not_embedded_in_repository": True,
        "no_price_or_outcome_queries": True,
        "live_buy_eligibility": "NOT_AUTHORIZED",
        "rows": [byid[t["security_id"], t["fiscal_year"]] for t in all_targets],
    }
    report = {
        "schema": SCHEMA,
        "source_evidence_sha256": sha(canonical(source_receipt)),
        "source_manifest_hashes": hashes,
        "frozen_issuer_year_count": 256,
        "frozen_first_24_reused_without_source_refetch": True,
        "additional_original_pdf_source_cases_attempted": 232,
        "original_pdf_full_identity_verified_count": full_pdf_count,
        "complete_four_field_count": sum(r["four_original_fields_complete"] for r in ordered),
        "incomplete_four_field_count": sum(not r["four_original_fields_complete"] for r in ordered),
        "per_field_original_table_coverage": dict(sorted(fields.items())),
        "source_status_counts": dict(sorted(statuses.items())),
        "source_values_from_original_year_table_cells_only": True,
        "later_2026_vendor_values_never_used_as_financial_features": True,
        "2023_2024_release_time_pdf_sha_certified": False,
        "strict_historical_pit_certified": False,
        "independent_untouched_oos_or_price_outcomes_used": False,
        "strategy_alpha_validated": False,
        "trade_authorized": False,
        "live_buy_eligibility": "NOT_AUTHORIZED",
        "rows": ordered,
    }
    return report, source_receipt


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="command", required=True)
    capture = sub.add_parser("capture")
    capture.add_argument("--shard", type=int, required=True)
    capture.add_argument("--out", type=Path, required=True)
    merge = sub.add_parser("merge")
    merge.add_argument("--shard-dir", type=Path, required=True)
    merge.add_argument("--out-dir", type=Path, required=True)
    args = ap.parse_args()
    if args.command == "capture":
        if args.out.exists():
            raise ValueError("REFUSE_OVERWRITE_EXISTING_SHARD")
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(capture_shard(args.shard), ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8")
    else:
        if args.out_dir.exists():
            raise ValueError("REFUSE_OVERWRITE_EXISTING_SOURCE_256_FRAME")
        shards = [json.loads((args.shard_dir / ("shard-%d.json" % i)).read_bytes())
                  for i in range(SHARD_COUNT)]
        frame, source = merge_shards(shards)
        args.out_dir.mkdir(parents=True)
        (args.out_dir / "ORIGINAL_SOURCE_256_FRAME.json").write_text(
            json.dumps(frame, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (args.out_dir / "ORIGINAL_PDF_TABLE_256_RECEIPT.json").write_text(
            json.dumps(source, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({k: v for k, v in frame.items() if k != "rows"},
                         ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
