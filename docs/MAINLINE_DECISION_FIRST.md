# Decision-first mainline — operating model V1

**Status:** Active development direction for new work upon merge; does not change frozen scientific contracts, historic evidence, or grant trading authority.

## One objective

Deliver a reproducible, point-in-time A-share decision-support loop: **candidate selection → evidence validation → action eligibility → position monitoring / disciplined exit → outcome feedback**. Optimize for preventing avoidable, emotion-driven investment errors; no guaranteed forecasts, autonomous trading, or return-maximization claim.

## What is a usable output?

One human-readable and machine-readable **Decision Case** for one security and an evaluation timestamp, with:
- security identity and timestamp; inputs' source, data vintage, missingness, and hashes;
- how the candidate was generated and the predeclared strategy/version;
- evidence strength and the underlying independently verified validity result, or `INSUFFICIENT` if not proven;
- contemplated action BUY/ADD/HOLD/REDUCE/EXIT, human-supplied risk fields, explicit eligibility outcome and reasons;
- precommitted invalidation, stop-loss, take-profit, review cadence, next permitted decision; uncertainty and no-action are acceptable;
- subsequent realized trade/observation separated from earlier decision-time evidence.

No recommendation is published without a traceable case; no BUY/ADD eligibility may be inferred just from an attractive candidate or synthetic test.

## Product lanes and ownership

| Lane | Meaning | Required output | Priority |
|---|---|---|---|
| A. Candidate and decision | Produce PIT-eligible A-share candidates, evaluate evidence, evaluate human-specified risk/action, track exits | One end-to-end auditable Decision Case | **P0 mainline** |
| B. Frozen prospective E-layer | Preserve V2.8.4 schedule, append-only receipts and V2.8.12 frozen gate | Independent observation evidence | Protected parallel lane; **not prerequisite** to unrelated A-lane implementation |
| C. Platform operations | Maintain runner, read-only failure discovery and necessary evidence access | Failure diagnosis only when it threatens A or B | On-demand support, not a product roadmap |

Research eligibility and risk gates remain binding. Product implementation may use *separately identified* public historical datasets and isolated fixtures, but may not borrow frozen prospective outcomes, Fold3/Fold4, or represent illustrative candidate rankings as statistically validated.

## Retain, reuse, retire

**Retain without rewriting:** `evidence/V2.9_GOVERNANCE_KERNEL.json`, existing V2.8.12/12R frozen contracts and evidence, historical provenance and pre-registration, fail-closed risk and discipline invariants.

**Reuse:** event-level and portfolio-path validity evaluators, Decision Packet adapter and Discipline Engine, existing evidence reader where suitable. Audit interfaces before invoking; never presume an implementation is a complete automated screen.

**Stop expanding:** new layers of diagnostic workflows, receipt chains, monitoring PRs, and operational contracts absent a demonstrated system-critical failure or a directly blocking Decision Case. Preserve deployed monitoring, avoid deleting historic receipts. No independent monitoring feature is allowed to outrank the mainline solely because it is easier to test.

## Only four delivery checkpoints

1. **Inventory integration inputs:** enumerate the actual candidate generator, PIT data adapters, existing validity evaluator, Decision Packet adapter, Discipline Engine, and position/state storage. Mark each as REUSABLE / MISSING / BLOCKED with one concrete repository path or evidence. **Do not invent a candidate engine.**
2. **One end-to-end isolated vertical slice:** from a frozen historical as-of date and openly identified non-Fold3/Fold4 fixtures, create one candidate and fail-closed Decision Case, using existing modules. No future bars at the as-of point. It may correctly conclude INSUFFICIENT. Test leakage, missing data, override failure, stop-loss and issuer identity.
3. **Historical testing and usable watchlist:** on a properly specified historical universe and benchmark, test screening effectiveness, portfolio-path assumptions, costs and risk controls, with OOS boundaries. Establish thresholds before looking at qualifying outcomes. If unavailable or insufficient, report the gap instead of claiming success.
4. **Read-only ongoing decision cadence:** produce current candidate/watchlist decisions from the latest *available* validated snapshot (not necessarily today's incomplete data), plus optional human-entered positions and review/exit triggers. User decides and executes trades. No automatic brokerage connectivity.

At every checkpoint, remove redundant components instead of adding parallel ones. Deliver user-visible decision cases, not only green CI indicators.

## Hard finish criteria and prioritization

The mainline is not done until a user can inspect one real, provenance-bound security Decision Case, reproduce its inputs and logic, and distinguish evidence-backed eligibility from insufficient evidence. A successful monitoring run is **not** mainline completion.

Any proposed engineering task must answer:
1. Which Decision Case field or binding requirement is blocked?
2. Is there an existing component to reuse?
3. Can the blocker be deleted, avoided, or absorbed, instead of creating another service?
4. What one executable test proves it is resolved?

If none of (1)–(4) yields a concrete mainline benefit or frozen-evidence integrity need, **defer**.

## Protected boundaries

- No revision of frozen research thresholds, sample definitions, sample windows, or unblinding.
- No Fold3/Fold4 read and no V2.8.13 authorization assertion.
- No rerunning failed controlled observations just to demonstrate progress.
- No automatic trade or fabricated historical outcome.
- Operations failures remain operational unless they threaten scientific integrity under the frozen governance kernel.

This is a **new operational product direction**, not a retroactive amendment to V2.9 scientific governance. It is deliberately one document rather than another stack of gates.
