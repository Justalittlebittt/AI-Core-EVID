#!/usr/bin/env python3
"""Reconstruct original-annual-table *research observations* from frozen 24 evidence.

Never fill source fields from retrospectively updated vendor records.
The 2026-fetched original-PDF content is NOT a contemporaneous 2023/2024
publication-time byte certificate, and no outcome or buy decision is permitted.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ORIGINAL = ROOT / "research/v29_original_table_24_20261031/FIXED_24_ORIGINAL_YEAR_TABLE_FIELDS.json"
PRECISION = ROOT / "research/v29_original_table_24_20261031/PRECISION_RECONCILIATION.json"
FIELDS = ("revenue_yuan", "parent_net_profit_yuan",
          "revenue_growth_yoy_pct", "weighted_roe_pct")
UNIT = {"yuan": Decimal("1"), "thousand_yuan": Decimal("1000"),
        "ten_thousand_yuan": Decimal("10000"), "percentage_points": Decimal("1")}
SCHEMA = "V29_ORIGINAL_24_SOURCE_ONLY_HISTORICAL_RESEARCH_FRAME_V1"


def reconstruct(original_bytes: bytes, precision_bytes: bytes) -> dict:
    original, precision = json.loads(original_bytes), json.loads(precision_bytes)
    digest = hashlib.sha256(original_bytes).hexdigest()
    if (original.get("schema") != "V29_PRIOR_2023_2024_FIXED_24_PDF_CURRENT_YEAR_FIELD_AUDIT_V1"
            or original.get("frozen_audit_sample_count") != 24
            or original.get("attempted_count") != 24
            or len(original.get("rows", [])) != 24
            or original.get("live_buy_eligibility") != "NOT_AUTHORIZED"
            or original.get("this_2026_retrospective_archive_proves_original_report_release_time_hash") is not False
            or original.get("no_historical_or_future_price_outcomes_queried") is not True
            or precision.get("schema") != "V29_FY2022_FY2023_24_ORIGINAL_SOURCE_REPORTING_PRECISION_RECONCILIATION_V1"
            or precision.get("underlying_frozen_24_current_year_source_evidence_sha256") != digest
            or precision.get("fixed_issuer_year_denominator") != 24
            or precision.get("confirmed_after_source_unit_rounding_review") != 3
            or precision.get("live_buy_eligibility") != "NOT_AUTHORIZED"):
        raise ValueError("FROZEN_ORIGINAL_SOURCE_OR_PRECISION_INTEGRITY_FAILED")

    conflicts = precision["remaining_review_issuer_field_pairs"]
    conflict_map = {}
    for item in conflicts:
        key = (item["security_id"], item["fiscal_year"])
        field = item["financial_field"]
        if field not in FIELDS or field in conflict_map.get(key, ()):
            raise ValueError("DUPLICATE_OR_INVALID_VERSION_DIFFERENCE")
        conflict_map.setdefault(key, []).append(field)
    if sum(map(len, conflict_map.values())) != 3:
        raise ValueError("FROZEN_VERSION_DIFFERENCE_COUNT_CHANGED")

    output = []
    seen = set()
    for row in original["rows"]:
        sid, year = row["security_id"], row["fiscal_year"]
        key = sid, year
        if key in seen or year not in (2022, 2023):
            raise ValueError("ORIGINAL_SAMPLE_IDENTITY_OR_YEAR_INVALID")
        seen.add(key)
        published = row.get("official_announcement_day")
        if published is not None and not published.startswith(str(year + 1) + "-"):
            raise ValueError("ORIGINAL_ANNOUNCEMENT_YEAR_MISMATCH")

        values, pages, missing = {}, {}, []
        for field in FIELDS:
            source = row.get("field_sources", {}).get(field)
            if (not row.get("pdf_original_current_year_field_source")
                    or source is None
                    or source.get("original_current_year_table_source_status") !=
                       "UNIQUE_FISCAL_YEAR_TABLE_CELL_EXTRACTED"):
                missing.append(field)
                continue
            amount = Decimal(str(source["original_current_year_table_value"]))
            evidence = source["original_pdf_table_evidence"]
            if not evidence or not amount.is_finite():
                raise ValueError("ORIGINAL_TABLE_NUMERIC_OR_PROVENANCE_MISSING")
            for cell in evidence:
                scale = UNIT.get(cell.get("unit_evidence"))
                if (scale is None or cell.get("financial_field") != field
                        or cell.get("fiscal_year_column_header") != str(year) + "年"
                        or Decimal(str(cell["table_cell_numeric"])) * scale != amount):
                    raise ValueError("ORIGINAL_TABLE_CELL_UNIT_YEAR_OR_IDENTITY_MISMATCH")
            values[field] = str(amount)
            pages[field] = sorted({cell["source_pdf_page_1based"] for cell in evidence})

        complete = len(values) == len(FIELDS)
        if complete and (not published or not row.get("pdf_sha256_2026_retrieval")):
            raise ValueError("COMPLETE_FIELDS_WITHOUT_ORIGINAL_REPORT_IDENTITY")
        output.append({
            "security_id": sid, "fiscal_year": year,
            "original_report_notice_date": published,
            "original_report_pdf_url": row.get("official_original_pdf_url"),
            "original_pdf_sha256_captured_2026": row.get("pdf_sha256_2026_retrieval"),
            "original_published_table_values": values,
            "source_table_pages": pages, "missing_fields": missing,
            "four_original_fields_complete": complete,
            "all_four_values_positive_descriptive_only": (
                all(Decimal(values[f]) > 0 for f in FIELDS) if complete else None),
            "original_vs_2026_vendor_material_difference_fields": sorted(conflict_map.get(key, [])),
            "historical_original_report_release_time_bytes_certified": False,
            "strict_historical_pit_certified": False,
            "current_executable_quote_certified": False,
            "buy_add_eligibility": "NOT_AUTHORIZED",
        })
    if len(seen) != 24 or not all(key in seen for key in conflict_map):
        raise ValueError("FROZEN_SAMPLE_OR_CONFLICT_MISSING")

    complete_rows = [r for r in output if r["four_original_fields_complete"]]
    positives = [r["security_id"] for r in complete_rows
                 if r["all_four_values_positive_descriptive_only"]]
    return {
        "schema": SCHEMA,
        "source_original_24_sha256": digest,
        "source_original_24_path": str(ORIGINAL.relative_to(ROOT)),
        "source_precision_audit_path": str(PRECISION.relative_to(ROOT)),
        "frozen_issuer_year_count": 24, "complete_four_field_count": len(complete_rows),
        "incomplete_four_field_count": 24 - len(complete_rows),
        "all_four_positive_descriptive_count": len(positives),
        "all_four_positive_security_ids_not_alpha": positives,
        "source_vs_later_vendor_material_difference_field_count": 3,
        "source_values_taken_only_from_original_fiscal_year_pdf_table_cells": True,
        "vendor_2026_numeric_values_used_as_features": False,
        "original_pdf_bytes_retrieved_in_2026_not_release_time_sha": True,
        "historical_pit_reconstruction_complete": False,
        "historical_exchange_universe_and_execution_verified": False,
        "independent_oos_or_future_outcomes_used": False,
        "strategy_alpha_validated": False,
        "live_buy_eligibility": "NOT_AUTHORIZED",
        "rows": output,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, help="Optional output; never overwrite research receipts")
    args = parser.parse_args()
    result = reconstruct(ORIGINAL.read_bytes(), PRECISION.read_bytes())
    report = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.out is not None:
        if args.out.exists():
            raise ValueError("REFUSE_OVERWRITE_SOURCE_ONLY_RESEARCH_FRAME")
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(report, encoding="utf-8")
    else:
        print(report, end="")


if __name__ == "__main__":
    main()
