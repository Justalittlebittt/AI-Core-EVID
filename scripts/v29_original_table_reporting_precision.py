"""Precise comparison of original PDF cell to later vendor at PDF DISPLAY precision.

A PDF's "单位: 千元" with a cell of 1,034,595 represents a 1,000-CNY
reporting quantum, not 1 CNY or 0.01 CNY. It is a serious data error to
interpret differences smaller than half the quantum as a restatement.
Always preserve both original printed and retrospectively updated values.
"""
from __future__ import annotations
from decimal import Decimal,ROUND_HALF_UP,InvalidOperation

UNIT_SCALE={
    "yuan":Decimal("1"),
    "thousand_yuan":Decimal("1000"),
    "ten_thousand_yuan":Decimal("10000"),
    "percentage_points":Decimal("1"),
}
COMPARABLE=("revenue_yuan","parent_net_profit_yuan",
            "revenue_growth_yoy_pct","weighted_roe_pct")

def source_quantum(entry):
    if (entry.get("original_current_year_table_source_status")!=
            "UNIQUE_FISCAL_YEAR_TABLE_CELL_EXTRACTED"):
        return None
    source_value=entry.get("original_current_year_table_value")
    evidence=entry.get("original_pdf_table_evidence") or []
    if source_value is None or not evidence:
        raise ValueError("NO_ACTUAL_YEAR_COLUMN_SOURCE_FOR_PRECISION")
    original=Decimal(str(source_value))
    quanta=[]
    for hit in evidence:
        if hit.get("financial_field")!=entry["financial_field"]:
            raise ValueError("PDF_EVIDENCE_WRONG_FINANCIAL_FIELD")
        unit=hit.get("unit_evidence")
        scale=UNIT_SCALE.get(unit)
        if scale is None:
            raise ValueError("PDF_EVIDENCE_WITHOUT_VERIFIED_REPORTING_UNIT")
        cell=Decimal(str(hit["table_cell_numeric"]))
        if cell*scale!=original:
            raise ValueError("PDF_SOURCE_CELL_DOES_NOT_MATCH_NORMALIZED_ORIGINAL_VALUE")
        # Decimal's exponent respects SOURCE cell decimal places, not its
        # post-multiplier CNY textual representation.
        quantum=Decimal(1).scaleb(cell.as_tuple().exponent)*scale
        if quantum<=0:
            raise ValueError("INVALID_ORIGINAL_PDF_REPORTING_QUANTUM")
        quanta.append(quantum)
    return min(quanta)

def reconcile_field(entry):
    """Returns comparison + quantum; never certifies historical release-time SHA."""
    field=entry["financial_field"]
    if field not in COMPARABLE:
        raise ValueError("NOT_FROZEN_FOUR_SOURCE_FIELDS")
    result={
        "financial_field":field,
        "original_year_value":entry.get("original_current_year_table_value"),
        "retrospective_2026_vendor_value":entry.get("vendor_2026_source_value"),
        "source_pdf_evidence":entry.get("original_pdf_table_evidence",[]),
        "original_release_pdf_bytes_SHA_time_certified":False,
        "source_vs_vendor_asof_version_identical_proven":False,
    }
    quantum=source_quantum(entry)
    if quantum is None:
        result["status"]="ORIGINAL_TABLE_FIELD_UNRESOLVED"
        return result
    result["original_reporting_quantum"]=str(quantum)
    if entry.get("vendor_2026_source_value") is None:
        result["status"]="ORIGINAL_TABLE_FIELD_FOUND_VENDOR_NOT_AVAILABLE"
        return result
    source=Decimal(str(entry["original_current_year_table_value"]))
    vendor=Decimal(str(entry["vendor_2026_source_value"]))
    rounded=(vendor/quantum).quantize(Decimal("1"),rounding=ROUND_HALF_UP)*quantum
    delta=vendor-source
    result.update({
        "later_vendor_minus_source_unrounded":str(delta),
        "later_vendor_rounded_to_original_source_reporting_precision":str(rounded),
        "absolute_difference_cny_or_percentage_points":str(abs(delta)),
        "maximum_comparable_presentation_rounding_difference":str(quantum/2),
    })
    if delta==0:
        result["status"]="SAME_NUMERIC_VALUE_AS_ORIGINAL_PUBLISHED_CELL"
    elif rounded==source:
        result["status"]="COMPATIBLE_WITH_ORIGINAL_REPORTING_PRECISION_NOT_VERSION_PROOF"
    else:
        result["status"]="DIFFERENCE_BEYOND_PUBLISHED_PRECISION_REQUIRES_SOURCE_REVIEW"
    return result
