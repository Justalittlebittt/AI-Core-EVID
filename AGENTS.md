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
