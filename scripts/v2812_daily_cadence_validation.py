from __future__ import annotations

import json
from pathlib import Path

OLD = Path("evidence/V2.8.12_SHADOW_CADENCE_CONTRACT.json")
AMEND = Path("evidence/V2.8.12_SHADOW_CADENCE_AMENDMENT_1.json")
WORKFLOW = Path(".github/workflows/v284-controlled-prospective-e-layer.yml")
SHADOW_STATUS = Path("evidence/V2.8.12_SHADOW_INFORMATION_GATE_STATUS.json")


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def self_test() -> dict:
    old = read_json(OLD)
    amend = read_json(AMEND)
    status = read_json(SHADOW_STATUS)
    workflow = WORKFLOW.read_text(encoding="utf-8")
    tests: list[dict] = []

    def check(name: str, condition: bool) -> None:
        tests.append({"name": name, "pass": bool(condition)})

    check(
        "C01_old_contract_preserved_as_historical_freeze",
        old["cadence"]["cron_utc"] == "0 1 * * 2-6"
        and old["integration"]["active_now"] is False,
    )
    check(
        "C02_amendment_is_active_schedule_authority",
        amend["status"] == "ACTIVE_CADENCE_SUPERSESSION"
        and amend["active_cadence"]["cron_utc"] == "0 1 * * *",
    )
    check(
        "C03_active_workflow_runs_every_calendar_day",
        'cron: "0 1 * * *"' in workflow
        and 'cron: "0 1 * * 2-6"' not in workflow,
    )
    check(
        "C04_local_time_semantics_remain_0900_shanghai",
        amend["active_cadence"]["local_interpretation"]
        == "09:00 Asia/Shanghai every calendar day"
        and "TZ=Asia/Shanghai date +%F" in workflow,
    )
    check(
        "C05_three_calendar_day_overlap_preserved",
        amend["scan_semantics_unchanged"]["overlap_calendar_days"] == 3
        and "timedelta(days=2)" in workflow,
    )
    check(
        "C06_announcement_dedup_authority_preserved",
        amend["scan_semantics_unchanged"]["announcement_dedup_authority"]
        == "evidence/V2.8.4_E_LAYER_OBSERVATION_LEDGER.csv",
    )
    check(
        "C07_serial_concurrency_preserved",
        "group: v284-v2812-prospective-e-shadow-serial" in workflow
        and "cancel-in-progress: false" in workflow,
    )
    check(
        "C08_v284_to_v2812_pipeline_preserved",
        "python scripts/v284_incremental_e_layer_runner.py scan" in workflow
        and "python scripts/v284_incremental_e_layer_runner.py finalize" in workflow
        and "python scripts/v2812_shadow_accumulator.py accumulate" in workflow,
    )
    check(
        "C09_daily_amendment_binding_is_fail_closed",
        'a["status"]=="ACTIVE_CADENCE_SUPERSESSION"' in workflow
        and 'a["active_cadence"]["cron_utc"]=="0 1 * * *"' in workflow,
    )
    check(
        "C10_no_outcome_or_broker_execution_path_added",
        all(
            token not in workflow.lower()
            for token in [
                "v283_outcome_resolver.py",
                "fwd5",
                "fwd10",
                "submit_order",
                "place_order",
                "brokerage_api",
                "broker_client",
            ]
        ),
    )
    check(
        "C11_research_permissions_remain_closed",
        amend["governance"]["outcome_research_authorized"] is False
        and amend["governance"]["price_or_return_data_authorized"] is False
        and amend["governance"]["fold3_access"] is False
        and amend["governance"]["fold4_access"] is False
        and amend["governance"]["live_authorized"] is False
        and amend["governance"]["brokerage_execution_authorized"] is False,
    )
    check(
        "C12_shadow_readiness_not_changed_by_schedule_amendment",
        status["status"] == "ACCUMULATING_PROSPECTIVE_E_EVENTS"
        and status["price_or_return_data_consumed"] is False
        and status["outcome_research_authorized"] is False,
    )
    check(
        "C13_weekend_gap_class_removed",
        amend["problem_elimination_pass"]["selected_action"]
        == "DELETE_TRADING_DAY_SCHEDULE_ASSUMPTION"
        and amend["active_cadence"]["frequency"] == "DAILY",
    )

    result = {
        "schema": "AI_CORE_EVID_V2_8_12_DAILY_CADENCE_VALIDATION_V1",
        "tests": tests,
        "passed": sum(t["pass"] for t in tests),
        "total": len(tests),
        "all_pass": all(t["pass"] for t in tests),
        "real_collection_run_triggered_by_validation": False,
        "price_or_return_data_consumed": False,
        "research_thresholds_changed": False,
        "fold3_4_accessed": False,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["all_pass"]:
        raise SystemExit(2)
    return result


if __name__ == "__main__":
    self_test()
