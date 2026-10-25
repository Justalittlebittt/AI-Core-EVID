# Actions status checks — mandatory evidence-first procedure

Scope: Every human or AI agent reporting GitHub Actions status, infrastructure health, V2.8.4 Controlled Prospective E-Layer Observation, Infrastructure Smoke Diagnostic, or V2.8.12 prospective integrity for this repository. This procedure is an **operational observation rule**, not a change to frozen scientific thresholds.

## Non-negotiable sequence

1. **Time first.** Establish the actual current date/time and applicable timezone. Read the workflow YAML's `on.schedule`, plus other triggers, from the default branch; convert UTC cron to the relevant local timezone. GitHub scheduled workflows may be delayed or dropped; distinguish `not due`, `due but not observed`, and `observed`. Never infer a due time solely from the last run.
2. **Run listing first.** Query the Actions *runs* endpoint for each target workflow or use the validated `tools/diagnostics/actions_run_visibility.py` inside an Actions environment with `actions: read`. Enumerate recent runs and attempts with their actual `created_at`, `event`, `status`, `conclusion`, `run_attempt`, and URL. A Git commit search is an auxiliary evidence source, **never a substitute for run listing**, because pre-job failures and cancelled runs need not write commits.
3. **Inspect jobs and history.** For each relevant run examine per-attempt jobs and conclusions. Do not equate run-level `success` with prospective data integrity, or `0 new rows` with execution failure. For a failure, inspect step/log evidence to establish a root cause before labeling one.
4. **Separate findings.** Report independently: scheduling/delivery, runner startup, workflow step execution, receipt/finalization, append-only prospective ledger, and frozen V2.8.12 information gate. A successful workflow does not authorize further research.
5. **Be explicit about unavailable access.** If the chat connector lacks complete Runs enumeration, do not repeat commit-only checks as though they were a fresh complete diagnosis. Use the already validated read-only monitor (GitHub Actions `Daily Read-only Actions Health Monitor`), its logs/receipts, or another authorized read-only interface. When no path is accessible, label the check **INCOMPLETE**; state exactly which evidence was checked and what remains unknown. Do not claim `healthy` or `no newer run`.
6. **Notification gate.** Notify only on a newly verified real step execution success, a newly evidenced failure root cause, or a material change to V2.8.12 prospective integrity. Otherwise remain quiet for conditional monitoring requests. A normal repeated check initiated by the user may receive a minimal confirmation, but it must not be presented as a new event.
7. **No repeated dead-end loops.** If a tool cannot enumerate runs, stop relying on it for that purpose immediately; change evidence path. Never give multiple consecutive `no update` answers based exclusively on unchanged Git commits. Do not imply background work is happening unless a scheduled automation actually exists.

## Mandatory evidence in every internal check record

- Check timestamp and timezone, workflow names, evaluated expected schedule windows, and whether due.
- Run IDs, timestamps, event types, status and conclusions for each checked workflow; attempts, job count, and source URL where available.
- Evidence completeness flag and explicit unverified claims.
- Any change in receipt/ledger integrity, distinguished from execution health.
- Classification: `NOT_DUE`, `SUCCESS_VERIFIED`, `FAILURE_VERIFIED`, `DUE_NOT_OBSERVED`, or `INCOMPLETE`; do not silently convert `INCOMPLETE` to `SUCCESS_VERIFIED`.
- Decision whether notification criteria were met.

## Research and operational prohibitions

- No rerun of the same failed research task for the purpose of checking status.
- No modification of frozen research thresholds, sample identity, eligibility requirements, or append-only evidence to make a gate pass.
- Do not open Fold3/Fold4, consume price/return outcomes while the prospective E-layer remains sealed, or assert V2.8.13 authorization without an explicit authorized decision.
- Do not rewrite historical evidence, invent run timestamps, claim scheduled delivery guarantees, or confuse draft/PR tests with default-branch scheduled executions.
- Do not change research workflows merely to improve observational monitoring; isolate monitor fixes and verify them separately.

## Escalation and ownership

Missing scheduled runs after the due window are an operational uncertainty requiring direct Runs evidence and, if available, monitor logs, not a reason to rerun the frozen observation. Missing data, ledger integrity faults, or activation-gate anomalies are investigated under the existing research governance without editing scientific criteria. This rule is mandatory for future status checks, including after chat/context handoff.
