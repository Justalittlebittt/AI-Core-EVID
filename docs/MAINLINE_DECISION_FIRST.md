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

## Minimal necessary defensive programming (active engineering rule)

These rules govern new and changed code; they do not amend frozen research contracts or justify blanket removal of existing protections.

1. **Validate once per trust boundary.** Validate incoming data at the boundary that owns its contract. Do not repeatedly check an invariant inside downstream pure logic when the validated value has not changed. Validate again only after a new external input, a transformation that can invalidate the invariant, or a distinct high-consequence boundary.
2. **Do not stack no-op checks or exception wrappers.** Reject duplicate null checks and broad `try/except` chains that merely log-and-rethrow, silently return `None`, or disguise the original failure. Catch exceptions only to perform a defined recovery, translate an error at a genuine boundary, add necessary diagnosis, or guarantee cleanup.
3. **Prefer local, readable code to gratuitous abstractions.** Keep one-off simple logic inline. Extract a function when it materially clarifies a complex responsibility, isolates side effects, enables meaningful tests, or removes substantive duplication. Call count alone is not the criterion.
4. **Require approval for speculative low-impact defenses.** Before adding complicated handling for an unobserved, low-impact edge case, explain the concrete failure mode, expected impact, implementation and maintenance cost, and simpler alternative. Do not quietly add the mechanism. This approval requirement does **not** waive non-negotiable protections for point-in-time leakage, sample identity/integrity, frozen rules, outcome blindness, or trading-risk discipline.
5. **Make new complexity earn its place.** New locks, retries, state machines, compatibility shims, validation gates, and recovery frameworks must name a credible failure mode, the boundary responsible for it, and why a simpler approach is insufficient. Prefer delete, avoid, reuse, or local handling before adding infrastructure.

**Review standard:** classify each proposed removal as redundant, necessary, or unverified; do not remove unverified guards. Tests should focus on observable behavior and scientific invariants rather than counting checks, catches, or lines of code. Do not alter archived/frozen historical modules merely to enforce style.

## Protected boundaries

- No revision of frozen research thresholds, sample definitions, sample windows, or unblinding.
- No Fold3/Fold4 read and no V2.8.13 authorization assertion.
- No rerunning failed controlled observations just to demonstrate progress.
- No automatic trade or fabricated historical outcome.
- Operations failures remain operational unless they threaten scientific integrity under the frozen governance kernel.

This is a **new operational product direction**, not a retroactive amendment to V2.9 scientific governance. It is deliberately one document rather than another stack of gates.

## V3.1 zero-wait evidence boundary — 2026-11-10

**Current operational research verdict:** **NO VERIFIED ALPHA / NO BUY.** The source-bound candidate-to-risk loop is functional (`scripts/v31_unified_eight_decision_gate.py`), but a working Decision Case and an attractive issuer are not evidence of repeatable predictive excess return. Do not call an unpromoted research candidate an executable recommendation.

**Do not restart completed or invalid experiments:**

- The 2025 and 2026 retrospective growth+ROE comparisons were not promoted: `research/v29_2025_growth_quality_nonpromotion/NONPROMOTION_VERDICT.json` and `research/v31_2026_cross_year_growth_roe/RESULT.json`.
- The 2023/24 absolute-low-volatility one-shot did **not** satisfy its predeclared year-by-year and month-share criteria: `research/v31_2023_2024_lowvol_one_shot/RESULT.json`; no threshold or factor-sign reversal.
- The separately preregistered 2023/24 **long-only 20-session short-term reversal** one-shot reusing the already-observed frozen daily archive also failed (20/20 valid months, 2024 mean below zero, 10/20 positive months): `research/v31_2023_2024_short_reversal_one_shot/RESULT.json`. Do not tune, reverse, or relabel that hindsight source as pristine untouched OOS.
- The separate historical E-layer setup discovery selected **no** candidate after three precommitted fold evaluations: `evidence/V2.8.8_SETUP_SHAPE_DISCOVERY_FINAL_RECEIPT.json`. Do not relabel fold-wise IC as live/realizable net alpha.
- Historic FY2022/23 issuer metadata: 245/256 original-announcement/vendor dates match but **251/256** vendor finance records were updated after the original year; **only 15/24** original-report development observations currently have all four figures. Official metadata match does not certify historical financial **values**. Evidence: `research/V2.9_2023_2024_256_SOURCE_LINEAGE_RECONCILIATION.json`, `research/V2.9_ORIGINAL_24_SOURCE_ONLY_DEVELOPMENT_FRAME_20261101.md`.
- Protected V2.8.12 prospective E shadow has **3 filings by 2 issuers**, versus a frozen minimum of 20 events, 12 issuers, 12 signal days, 6 distinct months and max 20% issuer share. Its gate **forbids opening price/return outcomes until readiness and a separate outcome contract**, even when the calendar horizon has passed. Do not consume it or Fold3/Fold4 as a shortcut: `evidence/V2.8.12_PROSPECTIVE_E_EVENT_SHADOW_ACCUMULATION_GATE.json` and `evidence/V2.8.12_CONTINUOUS_PROSPECTIVE_EPOCH_AMENDMENT_1.json`.

**Problem-elimination / minimal-source rule:** A contemporaneously generated (e.g. 2023-dated) PDF **hash receipt** is not a universal hard prerequisite for *exploratory* historical reconstruction; dated, issuer-verified original filings with originally published year-column values, correction/restatement chronology and conservative next-session timing can substantiate reconstruction, with its actual 2026 retrieval timestamp disclosed. However a retrospective 2026 vendor update date, announcement metadata, original PDF downloaded years later or a 15-name PDF subset alone **cannot** certify a full-year historical tradable return backtest or untouched OOS. Do not silently relax any frozen pre-outcome or scientific contract.

**Next-work triage:** No additional parameter grids, new factors, historical data-platform rebuild, manual quarterly PDF sweeps, scheduler tuning, or downstream buying components **without a specifically identified, presently available independent evidence source capable of changing the NO BUY decision**. Never wait for a future date to proceed with unrelated ready work; preserve ongoing frozen observations separately and never override their data-access rules. The research branch is **EVIDENCE_BLOCKED_AS_OF_2026_11_10**, not waiting on engineering. The stock research/watchlist entry and account discipline can remain usable as clearly labeled non-trading decision support; user account, stops and official execution cannot be invented.
