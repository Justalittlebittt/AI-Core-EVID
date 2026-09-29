from __future__ import annotations

import json
import re
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AMEND = ROOT / "evidence/V2.8.12_DATA_COMPLETENESS_AND_SCHEDULER_RECOVERY_AMENDMENT_1.json"
CADENCE2 = ROOT / "evidence/V2.8.12_SHADOW_CADENCE_AMENDMENT_2.json"
WORKFLOW = ROOT / ".github/workflows/v284-controlled-prospective-e-layer.yml"
ACCUMULATOR = ROOT / "scripts/v2812_shadow_accumulator.py"


def rj(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def scan_dates(as_of: date):
    return {as_of - timedelta(days=i) for i in range(3)}


def self_test():
    amend = rj(AMEND)
    cadence2 = rj(CADENCE2)
    workflow = WORKFLOW.read_text(encoding="utf-8")
    accumulator = ACCUMULATOR.read_text(encoding="utf-8")
    tests = []

    def ck(name, value):
        tests.append({"name": name, "pass": bool(value)})

    ck(
        "R01_amendment_active",
        amend["status"] == "ACTIVE_POST_SEAL_OPERATIONAL_SEMANTICS_AMENDMENT",
    )
    ck(
        "R02_primary_goal_is_data_coverage_not_cron_perfection",
        amend["operational_model"]["primary_objective"]
        == "PROSPECTIVE_DATA_COVERAGE_WITH_CAUSAL_TIMESTAMP_INTEGRITY"
        and amend["operational_model"]["scheduler_role"]
        == "AUTOMATION_TRIGGER_NOT_RESEARCH_EVIDENCE",
    )
    ck(
        "R03_active_off_peak_daily_cron_bound",
        cadence2["active_cadence"]["cron_utc"] == "17 1 * * *"
        and amend["operational_model"]["active_cron_utc"] == "17 1 * * *"
        and bool(re.search(r'cron:\s*["\']17 1 \* \* \*["\']', workflow)),
    )
    ck(
        "R04_three_calendar_day_overlap_bound",
        amend["operational_model"]["scan_window_calendar_days"] == 3
        and "timedelta(days=2)" in workflow,
    )

    next_run = date(2026, 9, 30)
    next_window = scan_dates(next_run)
    ck(
        "R05_one_missed_day_recoverable",
        date(2026, 9, 29) in next_window,
    )
    ck(
        "R06_two_consecutive_missed_days_recoverable",
        date(2026, 9, 28) in next_window and date(2026, 9, 29) in next_window,
    )
    ck(
        "R07_three_consecutive_missed_days_not_fully_coverable",
        date(2026, 9, 27) not in next_window
        and amend["recovery_capacity"]["maximum_consecutive_missed_daily_cycles_automatically_coverable_by_next_successful_run"] == 2,
    )
    recovery = amend["recovery_semantics"]
    ck(
        "R08_no_backdating_and_manual_recovery_keeps_true_trigger_identity",
        recovery["backdating_observation_time_to_the_missed_schedule_time_forbidden"] is True
        and recovery["manual_run_may_not_be_relabelled_as_schedule"] is True
        and recovery["manual_recovery_dispatch_must_use_actual_observation_time"] is True
        and recovery["manual_recovery_dispatch_does_not_count_as_scheduler_empirical_confirmation"] is True,
    )
    ck(
        "R09_manual_recovery_is_allowed_but_optional_inside_overlap",
        recovery["manual_recovery_dispatch_authorized_if_needed"] is True
        and recovery["manual_recovery_dispatch_is_optional_while_dates_remain_inside_a_future_overlap_window"] is True,
    )
    ck(
        "R10_announcement_dedup_remains_authoritative",
        amend["operational_model"]["announcement_dedup_authority"]
        == "evidence/V2.8.4_E_LAYER_OBSERVATION_LEDGER.csv"
        and 'r["announcement_id"]==event["announcement_id"]' in accumulator
        and 'return "NO_ACTION_DUPLICATE"' in accumulator,
    )
    incident = amend["2026_09_29_incident_interpretation"]
    ck(
        "R11_missed_20260929_not_falsely_declared_success_or_captured",
        incident["target_schedule_trigger_observed"] is False
        and incident["today_data_is_declared_already_captured"] is False
        and incident["today_schedule_is_declared_successful"] is False,
    )
    ck(
        "R12_next_window_contains_20260929",
        incident["next_day_window_if_2026_09_30_run_succeeds"]
        == {"start": "2026-09-28", "end": "2026-09-30", "contains_missed_date_2026_09_29": True},
    )
    ck(
        "R13_manual_recovery_today_is_valid_data_collection_not_schedule_success",
        incident["manual_recovery_today_would_be_valid_data_collection_if_run"] is True
        and incident["manual_recovery_today_would_not_count_as_schedule_success"] is True,
    )
    gov = amend["governance"]
    ck(
        "R14_no_manual_recovery_required_for_one_or_two_misses",
        gov["manual_intervention_required_for_one_missed_cycle"] is False
        and gov["manual_intervention_required_for_two_consecutive_missed_cycles"] is False,
    )
    ck(
        "R15_three_or_more_misses_force_explicit_recovery_audit",
        gov["explicit_recovery_audit_required_at_three_or_more_consecutive_missed_cycles"] is True,
    )
    ck(
        "R16_research_and_execution_boundaries_unchanged",
        gov["research_semantics_changed"] is False
        and gov["outcome_research_authorized"] is False
        and gov["price_or_return_data_authorized"] is False
        and gov["fold3_access"] is False
        and gov["fold4_access"] is False
        and gov["live_authorized"] is False
        and gov["brokerage_execution_authorized"] is False
        and gov["autonomous_financial_decision_authorized"] is False,
    )

    passed = sum(t["pass"] for t in tests)
    out = {
        "schema": "AI_CORE_EVID_V2_8_12_SCHEDULER_RECOVERY_SEMANTICS_SELFTEST_V1",
        "passed": passed,
        "total": len(tests),
        "status": "PASS" if passed == len(tests) else "FAIL",
        "tests": tests,
    }
    print(json.dumps(out, indent=2))
    if passed != len(tests):
        sys.exit(1)


if __name__ == "__main__":
    self_test()
