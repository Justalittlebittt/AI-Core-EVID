#!/usr/bin/env python3
"""Freeze two independent historical membership SOURCE COVERAGE frames.

Purpose: acquire truly 2023/2024-issued FY2022/FY2023 original filings.
Selection uses only as-of membership identifiers and fixed SHA ordering.
The 2026 reconstructed membership source is NOT itself a contemporaneous PIT
snapshot; old financial outcomes exist already, so this is NOT pristine OOS.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import date,datetime,timezone
from pathlib import Path

from v29_historical_universe_sampling import (
    INTERVALS,INTERVALS_SHA256,select_membership_frame
)

SAMPLE_SIZE=128
COHORTS=(
    ("FY2022_ISSUED2023",date(2023,1,3),"2022-12-31",2023,"V29_FY2022_ORIGINAL_SOURCE_SAMPLE_20261031_V1"),
    ("FY2023_ISSUED2024",date(2024,1,2),"2023-12-31",2024,"V29_FY2023_ORIGINAL_SOURCE_SAMPLE_20261031_V1"),
)
SCHEMA="V29_EARLIER_ORIGINAL_FILING_2023_2024_SOURCE_COHORTS_V1"

def sha(raw):
    return hashlib.sha256(raw).hexdigest()

def select_cohorts(interval_path=INTERVALS):
    raw=Path(interval_path).read_bytes()
    if sha(raw)!=INTERVALS_SHA256:
        raise ValueError("FROZEN_HISTORICAL_MEMBERSHIP_SOURCE_CHANGED")
    rows=list(csv.DictReader(raw.decode("utf-8-sig").splitlines()))
    result=[]
    for title,asof,fiscal,issued,seed in COHORTS:
        frame=select_membership_frame(rows,frame_date=asof,
                                      sample_size=SAMPLE_SIZE,seed=seed)
        # This is only a future-delisting diagnostic: the selection never reads
        # or conditions on the 2026 survivorship information.
        byid={r["canonical_security_id"]:r for r in rows}
        future_delisted=sum(bool(byid[sid]["official_delist_date"])
                            and date.fromisoformat(byid[sid]["official_delist_date"])<date(2026,10,31)
                            for sid in frame["selected_ids"])
        result.append({
            "cohort_id":title,
            "asof_membership_date":asof.isoformat(),
            "report_period_end":fiscal,
            "expected_issuer_publication_year":issued,
            "source_selection_seed":seed,
            "population_count":frame["population_count"],
            "population_sha256":frame["population_ids_sha256"],
            "selected_count":frame["sample_count"],
            "selected_ids_sha256":frame["selected_ids_sha256"],
            "selected_ids":frame["selected_ids"],
            "selected_prior_to_filing_publication_based_on_membership_alone":True,
            "future_delisted_before_2026_10_31_diagnostic_count":future_delisted,
            "future_delisting_NOT_used_for_membership_or_sampling":True,
        })
    return {
        "schema":SCHEMA,
        "frozen_member_interval_sha256":INTERVALS_SHA256,
        "reconstruction_2026_not_contemporaneous_original_exchange_snapshot":True,
        "historical_outcomes_already_known_at_2026_sampling":True,
        "source_only_sample_no_outcome_data_read":True,
        "chronological_untouched_oos_certified":False,
        "financial_fields_asof_verified":False,
        "live_buy_eligibility":"NOT_AUTHORIZED",
        "cohorts":result,
    }

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--out",required=True,type=Path)
    a=parser.parse_args()
    if a.out.exists():
        raise ValueError("NO_OVERWRITE_OF_LOCKED_PRIOR_YEAR_COHORT")
    result=select_cohorts()
    a.out.parent.mkdir(parents=True,exist_ok=True)
    a.out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"schema":SCHEMA,
                      "samples":[{"year":x["expected_issuer_publication_year"],
                                  "population":x["population_count"],
                                  "selected":x["selected_count"],
                                  "frozen_sha256":x["selected_ids_sha256"],
                                  "later_delisted_in_128":x["future_delisted_before_2026_10_31_diagnostic_count"]}
                                 for x in result["cohorts"]],
                      "oos":False,"BUY":"NOT_AUTHORIZED"},ensure_ascii=False))

if __name__=="__main__":
    main()
