# Operational execution contract — No Passive Wait V1.0

Status: ACTIVE upon merge to main.
Scope: All AI agents and operators handling AI Core EVID monitoring, operational diagnosis, fault recovery, and continuation requests. This is a subordinate **operations execution contract**, not a scientific research contract. It cannot amend `evidence/V2.9_GOVERNANCE_KERNEL.json`, frozen V2.8.12 rules, or research authorization.

## P0 mandatory rule: waiting is not a substitute for currently executable work

A response that stops at "the next scheduled run has not occurred", "waiting for events/data", "nothing changed in commits", "the API is unavailable", or "try again tomorrow" **FAILS** this contract if an authorized, meaningful investigation or repair can be performed now.

No future observation can be fabricated or accelerated; it is valid to await future market events **only for the specific outcome that inherently requires those events**, not for independent engineering, diagnostics, provenance checks, report inspection, or remediation.

## Required execution algorithm (every check/continue)

1. **Define the immediate objective** and inspect this contract plus `AGENTS.md` and `docs/operations/ACTIONS_STATUS_EVIDENCE_RULES.md`.
2. **Time and due gate**: obtain the time and read actual default-branch schedules. Distinguish `NOT_DUE`, `DUE_NOT_OBSERVED`, `RUNNING`, `COMPLETED`, and `INCOMPLETE`. A `NOT_DUE` research workflow does not end operational investigation.
3. **Evidence gate**: enumerate real Actions Runs and attempts where available; check jobs, failures, smoke results, and authoritative receipts; separate execution health from prospective data integrity. Commit searches are secondary, not proof that nothing happened.
4. **Problem Elimination Pass**: identify the user's final objective and hard constraints. For the costliest failed or repeated soft assumption, consider Delete → Avoid → Absorb → Substitute → Precompute/Reuse → Optimize. Prefer eliminating an ineffective repeated check rather than repeating it.
5. **Available-work scan**: inspect unresolved operational blockers, monitor outputs, missing schedule deliveries, incomplete retrieval paths, and regression coverage; select the highest-impact **permitted and currently executable** next action. Do not create unnecessary probes, gates, workflows, or contracts when an existing mechanism suffices.
6. **Execute and validate**: where authorized and supported by tools, perform the selected action now; validate with independent evidence, tests, and a final diff/scope review. Isolate nontrivial changes in a branch and PR, and do not falsely declare PASS when production verification is absent.
7. **Termination gate**: end only when (a) the immediate objective is achieved with evidence; (b) no further relevant work can be done with available permissions/tools, and the exact missing capability plus attempted alternatives is recorded; or (c) every remaining step genuinely depends on a future external event. A status-only reply cannot count as repair completion.

## Explicitly forbidden behaviors — contract breach

- Waiting for a future schedule when there are presently available diagnostics, fixes, tests, or evidence.
- Saying "not due" without checking previously due executions and available monitoring evidence.
- Repeating the same commit-only lookup or failed tool path on successive checks while claiming a complete health result.
- Treating lack of new observations as lack of actionable engineering work.
- Inventing background execution, promising delayed delivery, reporting PASS without running the test, or claiming access to Runs that has not been obtained.
- Changing scientific thresholds, frozen cohorts/selection rules, V2.8.12 prospective ledger semantics, Fold3/Fold4 restrictions, or asserting V2.8.13 authorization to bypass a gate.
- Automatically rerunning a previously failed controlled observation merely to generate fresh evidence.

## Audit fields and enforcement

For each operational execution, record in the working record or final concise status:
`objective`, `checked_at_utc`, `due_state`, `runs_evidence`, `integrity_evidence`, `available_work_considered`, `action_executed`, `validation`, `remaining_blocker`, `notification_gate`.

Every false "wait" termination is an **OPERATIONAL_PROCESS_FAILURE**, even when scientific observation is legitimately pending. Its correction is to immediately re-enter steps 3–6, not to add another redundant rule or retry the frozen experiment. If a different tool cannot access Runs, use an already-authorized GitHub-hosted read-only monitor or logs. When all paths fail, mark `INCOMPLETE` with the exact limitation; do not manufacture a healthy status.

The agent owning the task is responsible for completing available work without requiring the user to repeat "continue". When no tool can continue, report the precise boundary, not a vague wait. Escalate scientific-integrity threats under the frozen governance kernel; keep purely operational issues diagnostic-only unless they meet its materiality criteria.

## Acceptance checks

- Scenario A: before the daily schedule, past run/log checks and independent operational work are still performed; NOT_DUE alone cannot terminate.
- Scenario B: Actions run enumeration is inaccessible, and the alternative existing monitor is checked (if accessible), otherwise INCOMPLETE is reported with specificity.
- Scenario C: prospective events remain at 7 and no new positive filing exists; no research result is invented, and any real engineering task is assessed separately.
- Scenario D: all meaningful work is exhausted and future outcome is truly externally gated; termination is allowed with a concrete dependency.
- Scenario E: any proposed fix is reviewed against the frozen governance boundaries and changes no research parameter.

This contract is binding on future repository task execution and cross-session handoff. It does not guarantee an external platform will supply data or that agents without tool access can act.
