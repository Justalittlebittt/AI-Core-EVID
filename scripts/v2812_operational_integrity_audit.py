from __future__ import annotations

import json
from pathlib import Path

import v284_incremental_e_layer_runner as runner
import v2812_shadow_accumulator as shadow

WORKFLOW = Path('.github/workflows/v284-controlled-prospective-e-layer.yml')
RUNNER = Path('scripts/v284_incremental_e_layer_runner.py')
SHADOW = Path('scripts/v2812_shadow_accumulator.py')
TRANSPORT = Path('evidence/V2.8.12_TRANSPORT_RELIABILITY_AMENDMENT_1.json')
DAILY_RECEIPT = Path('evidence/V2.8.12_DAILY_CADENCE_VALIDATION_RECEIPT.json')
CADENCE2 = Path('evidence/V2.8.12_SHADOW_CADENCE_AMENDMENT_2.json')
SHADOW_STATUS = Path('evidence/V2.8.12_SHADOW_INFORMATION_GATE_STATUS.json')


def rj(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8'))


def main() -> None:
    tests = []

    def ck(name: str, value: bool) -> None:
        tests.append({'name': name, 'pass': bool(value)})

    wf = WORKFLOW.read_text(encoding='utf-8')
    src = RUNNER.read_text(encoding='utf-8')
    shsrc = SHADOW.read_text(encoding='utf-8')
    ta = rj(TRANSPORT)
    daily = rj(DAILY_RECEIPT)
    cadence2 = rj(CADENCE2)
    status = rj(SHADOW_STATUS)

    ck('O01_daily_cadence_validation_pass', daily.get('status') == 'PASS')
    ck('O02_workflow_daily_0117_utc', cadence2.get('status') == 'ACTIVE_SCHEDULER_RELIABILITY_SUPERSESSION' and cadence2['active_cadence']['cron_utc'] == '17 1 * * *' and 'cron: "17 1 * * *"' in wf)
    ck('O03_serial_concurrency_preserved', 'group: v284-v2812-prospective-e-shadow-serial' in wf and 'cancel-in-progress: false' in wf)
    ck('O04_three_calendar_day_overlap_preserved', 'timedelta(days=2)' in wf and daily['current_operational_cadence']['overlap_calendar_days'] == 3)

    ck('O05_transport_amendment_frozen', ta.get('status') == 'FROZEN_BEFORE_TRANSPORT_PATCH_VALIDATION')
    ck('O06_cninfo_home_preflight_removed', 'api.get("https://www.cninfo.com.cn/"' not in src and 'CNINFO_HOME_HTTP_' not in src)
    ck('O07_direct_target_pdf_fetch_preserved', 'loc["official_url"]' in src and 'PDF_FETCH_HTTP_' in src)
    ck('O08_pdf_signature_and_hash_validation_preserved', 'cm.validate_pdf_bytes' in src and 'te.validate_pdf(cp' in src)
    ck('O09_per_filing_blocker_isolation_preserved', 'except Exception as e:' in src and '"pipeline_status":"BLOCKED"' in src)

    candidate = {'announcement_id': 'retry-me'}
    ck('O10_blocked_or_uncommitted_candidate_retries_next_overlap', runner.unseen_rows([candidate], []) == [candidate])
    ck('O11_successfully_observed_candidate_dedups_next_overlap', runner.unseen_rows([candidate], [{'announcement_id': 'retry-me'}]) == [])

    base_event = {
        'announcement_id': 'A1',
        'canonical_security_id': 'SSE:600001',
        'source_object_sha256': 'a' * 64,
        'decision_sha256': 'b' * 64,
    }
    ck('O12_shadow_duplicate_is_noop', shadow.assess([base_event], dict(base_event)) == 'NO_ACTION_DUPLICATE')
    changed = dict(base_event)
    changed['decision_sha256'] = 'c' * 64
    ck('O13_shadow_same_announcement_conflict_blocks', shadow.assess([base_event], changed) == 'BLOCK_CONFLICT')

    ordered = [
        'Controlled prospective scan',
        'Commit authoritative observation receipt',
        'Finalize append-only ledger from authoritative commit',
        'Commit prospective ledger finalization',
        'Append V2.8.12 prospective shadow events and audit blind readiness',
        'Commit V2.8.12 shadow ledger, ratifications and readiness status',
    ]
    positions = [wf.find(x) for x in ordered]
    ck('O14_pipeline_stage_order_preserved', all(p >= 0 for p in positions) and positions == sorted(positions))

    ck('O15_observation_commit_before_finalization', wf.find('OBS_SHA="$(git rev-parse HEAD)"') < wf.find('python scripts/v284_incremental_e_layer_runner.py finalize'))
    ck('O16_git_rebase_before_each_push_path_present', wf.count('git pull --rebase origin main') >= 3 and wf.count('git push') >= 3)

    prohibited = ['v283_outcome_resolver', 'fwd10', 'fwd5', 'AUTO_BUY', 'submit_order', 'place_order', 'brokerage_api', 'broker_client']
    runner_prod = src.split('def self_test():', 1)[0]
    shadow_prod = shsrc.split('def self_test():', 1)[0]
    combined = (wf + '\n' + runner_prod + '\n' + shadow_prod).lower()
    ck('O17_no_outcome_or_broker_execution_path', all(x.lower() not in combined for x in prohibited))
    ck('O18_shadow_status_still_blind', status.get('schema') == 'AI_CORE_EVID_V2_8_12_SHADOW_INFORMATION_GATE_STATUS_V2' and status.get('readiness_epoch') == 'V2.8.12_CONTINUOUS_PROSPECTIVE_EPOCH_2' and status.get('readiness_epoch_start_asia_shanghai') == '2026-09-27' and status.get('price_or_return_data_consumed') is False and status.get('outcome_research_authorized') is False)
    ck('O19_fold3_fold4_remain_closed', status.get('fold3_accessed') is False and status.get('fold4_accessed') is False)

    # A scheduler cannot be proven by source inspection. This audit deliberately
    # leaves first real daily schedule execution as an external evidence item.
    external_scheduler_confirmation = False

    result = {
        'schema': 'AI_CORE_EVID_V2_8_12_OPERATIONAL_INTEGRITY_AUDIT_SELFTEST_V1',
        'tests': tests,
        'passed': sum(t['pass'] for t in tests),
        'total': len(tests),
        'all_static_and_synthetic_pass': all(t['pass'] for t in tests),
        'first_real_daily_scheduled_run_observed': external_scheduler_confirmation,
        'status': 'STATIC_AND_SYNTHETIC_PASS_PENDING_FIRST_REAL_DAILY_SCHEDULED_RUN' if all(t['pass'] for t in tests) else 'OPERATIONAL_INTEGRITY_AUDIT_FAILED',
        'real_collection_run_triggered_by_audit': False,
        'price_or_return_data_consumed': False,
        'research_thresholds_changed': False,
        'shadow_ledger_modified': False,
        'fold3_4_accessed': False,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result['all_static_and_synthetic_pass']:
        raise SystemExit(2)


if __name__ == '__main__':
    main()
