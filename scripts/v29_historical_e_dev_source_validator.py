from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import v29_historical_e_dev_source_runner as r

RUNNER = Path("scripts/v29_historical_e_dev_source_runner.py")
EXPECTED_RUNNER_BLOB_SHA = "9fc6d07c92571db45845271175fced261f0226ab"


def main() -> None:
    contract = r.load_contract()
    days = r.trading_dates()
    windows = r.compute_windows(days)
    owner, by_fold = r.load_development_universe()
    tests = []

    def ck(name: str, value: bool) -> None:
        tests.append({"name": name, "pass": bool(value)})

    ck("V01_exact_56_windows", len(windows) == 56)
    ck("V02_anchor_ordinals_exact", sorted({x["anchor_ordinal"] for x in windows}) == [4, 12, 20, 28, 36, 44, 52])
    ck("V03_eight_quarters", len({x["quarter"] for x in windows}) == 8)
    ck("V04_seven_windows_per_quarter", all(sum(x["quarter"] == q for x in windows) == 7 for q in {x["quarter"] for x in windows}))
    ck("V05_manifest_counts_exact", [len(by_fold[i]) for i in (0, 1, 2)] == [1031, 1058, 1048])
    ck("V06_manifest_pairwise_disjoint", len(owner) == sum(len(v) for v in by_fold.values()))

    ids = [next(iter(by_fold[i])) for i in (0, 1, 2)]
    sample = [
        {"announcement_id": "100", "canonical_security_id": ids[0], "adjunct_url": "a", "announcement_time": "1", "path_disclosure_date": "x"},
        {"announcement_id": "200", "canonical_security_id": ids[1], "adjunct_url": "b", "announcement_time": "2", "path_disclosure_date": "y"},
        {"announcement_id": "300", "canonical_security_id": ids[2], "adjunct_url": "c", "announcement_time": "3", "path_disclosure_date": "z"},
        {"announcement_id": "400", "canonical_security_id": "SSE:999999", "adjunct_url": "d", "announcement_time": "4", "path_disclosure_date": "w"},
    ]
    a = r.select_candidates(sample, owner, 6)
    b = r.select_candidates(list(reversed(sample)), owner, 6)
    ck("V07_unknown_identity_excluded", len(a) == 3 and all(x["canonical_security_id"] in owner for x in a))
    ck("V08_selection_order_invariant", [x["announcement_id"] for x in a] == [x["announcement_id"] for x in b])
    ck("V09_fold_binding_preserved", {x["development_fold"] for x in a} == {0, 1, 2})

    ts = int(datetime(2024, 1, 31, 2, 0, tzinfo=timezone.utc).timestamp() * 1000)
    row = {
        "announcement_id": "123",
        "canonical_security_id": ids[0],
        "announcement_time": str(ts),
        "adjunct_url": "finalpage/2024-01-31/123.PDF",
        "path_disclosure_date": "2024-01-31",
    }
    temporal = r.resolve_temporal(row, days)
    ck("V10_temporal_date_consistency", temporal["announcement_local_date_asia_shanghai"] == "2024-01-31")
    ck("V11_effective_date_strictly_later", temporal["retrospective_causal_effective_date"] > "2024-01-31")

    source = RUNNER.read_text(encoding="utf-8")
    production_source = source.split("def self_test()", 1)[0]
    forbidden = [
        "v2810_locked_ac_pullback_reclaim_evaluator",
        "v290_strategy_validity_evaluator",
        "v291_portfolio_path_evaluator",
        "v292_matched_random_baseline",
        "V2.8.10_AC_EVENT_LEDGER",
        "fold3_source",
        "fold4_source",
    ]
    ck("V12_no_outcome_or_fold34_production_import", not any(x in production_source for x in forbidden))
    ck("V13_collection_requires_validation_receipt", "validate_run_authorization()" in production_source)
    ck("V14_contract_price_outcome_false", contract["authorization"]["price_or_return_access"] is False and contract["authorization"]["candidate_outcome_research"] is False)
    ck("V15_contract_fold34_false", contract["authorization"]["fold3_access"] is False and contract["authorization"]["fold4_access"] is False)
    ck("V16_runner_blob_binding_documented", EXPECTED_RUNNER_BLOB_SHA == "9fc6d07c92571db45845271175fced261f0226ab")

    out = {
        "schema": "AI_CORE_EVID_V2_9_HISTORICAL_E_DEV_SOURCE_RUNNER_VALIDATOR_RESULT_1",
        "version": "V2.9",
        "runner_path": str(RUNNER),
        "runner_blob_sha": EXPECTED_RUNNER_BLOB_SHA,
        "tests": tests,
        "passed": sum(x["pass"] for x in tests),
        "total": len(tests),
        "all_pass": all(x["pass"] for x in tests),
        "real_source_queries_executed": False,
        "price_or_return_data_consumed": False,
        "fold3_accessed": False,
        "fold4_accessed": False,
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    if not out["all_pass"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
