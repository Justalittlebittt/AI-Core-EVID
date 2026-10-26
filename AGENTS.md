# Repository agent operating rules

These rules apply to assistants, coding agents, and human operators performing repository tasks.

## GitHub Actions status and incident checks (mandatory)

Before reporting whether V2.8.4 Controlled Prospective E-Layer Observation, Infrastructure Smoke Diagnostic, or the daily monitor has run successfully, follow [the evidence-first status procedure](docs/operations/ACTIONS_STATUS_EVIDENCE_RULES.md).

In particular:
- Read schedule and current time first. Check actual GitHub Actions **runs**, not just commits.
- Inspect attempts and jobs; commit history alone misses pre-job failures.
- If the current connector cannot enumerate recent runs, use another authorized read-only route such as the existing GitHub-hosted daily monitor. Mark incomplete information `INCOMPLETE`, never `healthy`.
- Never repeat unchanged commit-only checks as if they prove no new failures.
- Distinguish infrastructure success from V2.8.12 prospective integrity and frozen research eligibility.
- Notify the user only under the declared incident/update thresholds; never invent a new event.

The monitoring procedure does not change scientific governance. Do not rerun a failed frozen task, modify frozen thresholds, inspect Fold3/Fold4, or assume V2.8.13 permission.

## No-passive-wait execution contract (P0, mandatory)

Follow [Operations No Passive Wait V1.0](docs/contracts/OPERATIONS_NO_PASSIVE_WAIT_V1.md) for every status, monitoring, recovery, or "continue" task. If work is executable now, a response ending merely in "waiting for the next schedule/data" is an `OPERATIONAL_PROCESS_FAILURE`. Time gates apply only to external future observations, not independent diagnostics. Complete the evidence gate, available-work scan, permitted execution, validation, and termination gate before concluding. Do not change frozen research contracts to satisfy this operational rule.
