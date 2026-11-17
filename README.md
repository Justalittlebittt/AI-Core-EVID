# AI Core EVID

AI Core EVID is a personal A-share evidence and decision-discipline research system.

**User outcome:** discover A-share candidates with a predeclared, reproducible stock-selection rule that demonstrates repeatable **out-of-sample, after-cost, realistically executable excess return**, then issue timestamped buy/hold/reduce/exit eligibility with strict position and exit discipline. Profitable prediction is the research objective; preventing unproven or undisciplined trades is a non-negotiable safety constraint, not a substitute for predictive value. Neither a working pipeline nor repeated `NO BUY` decisions constitutes a validated predictor or a completed investment goal. No guaranteed forecasts, autonomous brokerage orders, or return-maximization claim.

## Active product mainline — prediction first (V3.2)

**The product is a credible stock forecast, not an audit platform.** New development starts with an economically motivated hypothesis and actually available decision-time data, then tests the predicted **future** net excess return and realistic execution **on independent observations**, and only afterward promotes a candidate to a real-security Decision Case. Prior stock-price appreciation is **not** universally required to enter the candidate pool.

**Canonical architecture and priority:** [Prediction-first Architecture V3.2](docs/PREDICTION_FIRST_ARCHITECTURE_V3_2.md). Existing implementation interfaces and safety constraints: [Decision-first mainline](docs/MAINLINE_DECISION_FIRST.md). These are complementary: V3.2 governs **what gets built next**, V2.9 documents **what the existing engines already do**.

```text
Public decision-time data
    ↓
Economic hypothesis / feature feasibility
    ↓
Future-return forecast or candidate ranking + uncertainty
    ↓
Independent after-cost / fill-aware evaluation
    ↓
Real issuer Decision Case + existing Discipline Engine
    ↓
Human-controlled position / exit / feedback

Frozen prospective evidence: parallel, unchanged, outcome-blind
GitHub Actions / data audits: essential support, never the product
```

**Research state (2026-11-17): NO VERIFIED ALPHA / NO BUY.** Closed low-volatility, reversal, medium-term momentum and growth-quality development tests did not establish a usable predictor. Do not reopen these same historical windows to search for a more flattering sign, horizon or threshold. The prospective 122/8 and V2.8.12 E-layer studies remain protected, unmodified and independently scheduled.

## Existing scientific foundation — V2.9

```text
Governance Kernel
    ├── Evidence Engine
    ├── Validity Engine (event + portfolio path)
    └── Decision Packet → Discipline Engine
```

The five constitutional invariants remain:

1. No leakage.
2. No silent sample mutation.
3. No undocumented override.
4. No unsupported certainty.
5. No goal drift away from reducing emotion-driven investing errors.

Canonical governance contract:

- `evidence/V2.9_GOVERNANCE_KERNEL.json`

## Current system state

### Evidence / historical closure

- V2.8.12R R1 technical gate has been reconciled and closed under its original rules.
- The repaired cohort reached 16/16 frozen-window query completeness and preserved the original classifier/sample rules.
- R2 historical outcome resolution was completed without changing the frozen cohort.
- V2.8.12R was finally classified **descriptive-only** because the historical sample floor failed; no feasibility/alpha claim was authorized.
- Historical V2.8.12R evidence remains immutable.

### Prospective E-layer

The active prospective E-layer remains outcome-blind and scheduled.

Current readiness status remains `ACCUMULATING_PROSPECTIVE_E_EVENTS` unless its frozen information gate later passes. The readiness gate requires all of:

- at least 20 prospective positive filing-events;
- at least 12 distinct issuers;
- at least 12 distinct effective dates;
- at least 6 calendar months;
- maximum single-issuer event share <= 20%;
- provenance/integrity PASS;
- no price/return consumption during accumulation.

Until that gate passes, no prospective E outcome research is authorized and fold3/fold4 remain sealed.

### Integrity consolidation

V2.9 Integrity Exit Audit is complete. Historical controls were classified into constitutional, compatibility, diagnostic, retired-from-active-path, or unresolved-blocker classes. Historical evidence was retained; retirement means removal from future active paths, not deletion.

Canonical audit contract:

- `evidence/V2.9_INTEGRITY_EXIT_AUDIT_CONTRACT.json`

## Validity Engine

The Validity Engine now has two foundations.

### Event-level validity

- Contract: `evidence/V2.9_STRATEGY_VALIDITY_FRAMEWORK_CONTRACT.json`
- Evaluator: `scripts/v290_strategy_validity_evaluator.py`

It reports effect size, benchmark-relative performance, transaction-cost drag, supplied train/OOS partitions, regimes, parameter sensitivity, concentration, and calibration without inventing evidence-strength thresholds.

### Portfolio-path validity

- Contract: `evidence/V2.9_PORTFOLIO_PATH_EXECUTION_CONTRACT.json`
- Evaluator: `scripts/v291_portfolio_path_evaluator.py`

This layer computes chronological portfolio metrics only from an **upstream execution-resolved path**. It does not invent holding periods, fills, position sizes, overlapping-signal allocation, leverage, slippage, limit-up/limit-down behavior, or transaction-cost assumptions.

Drawdown and portfolio-path statistics therefore have actual path semantics rather than being reconstructed from unordered event rows.

The general evidence-strength mapping is already frozen in `evidence/V2.9_EVIDENCE_STRENGTH_MAPPING_CONTRACT.json`. It does **not** establish a real strategy's strength: any experiment-specific numeric decision rules must be preregistered before that experiment's qualifying outcomes, and independent OOS and post-cost evidence are still missing.

## Decision Packet and Discipline Engine

Decision Packet and Discipline Engine v1 are implemented as fail-closed decision-support layers.

- `evidence/V2.9_DECISION_PACKET_CONTRACT.json`
- `evidence/V2.9_DISCIPLINE_ENGINE_V1_CONTRACT.json`

They evaluate action eligibility and risk-rule compliance. They do not provide autonomous brokerage execution or guaranteed market-direction predictions.

Core discipline protections include:

- stop-loss lock;
- invalidation-triggered exit;
- position and risk-budget limits;
- anti-FOMO controls;
- anti-averaging-down controls;
- take-profit adjustment discipline;
- override logging that cannot convert a blocked action into an eligible one.

## Problem ownership

Every new issue must first be classified:

- **SYSTEM_CRITICAL** — can alter sample identity, decision-time information, model/selection rules, OOS/prospective integrity, material evidence identity, or trading discipline. May hard-block.
- **RESEARCH_UNCERTAINTY** — small samples, weak effects, wide intervals, regime instability, calibration uncertainty. Must remain uncertainty rather than becoming engineering repair work.
- **EXTERNAL_OPERATIONAL** — transient HTTP/provider/network/queue failures. Retry/cache/degrade/record; escalate only if a system-critical property can be affected.

A new workflow/gate/amendment/receipt/probe is not justified merely because it is “more rigorous” or “more complete”. It must prevent a specific system-level failure.

## Research-layer next stage (parallel, not product blocker)

**Do not recreate an evidence-strength mapping contract.** V2.9 already has its frozen general mapping and existing validity/discipline evaluators. The unresolved scientific question is whether any *specific, predeclared* candidate strategy demonstrates a repeatable positive post-cost advantage on genuinely independent data.

The separate, fixed 122-issuer growth cohort (`research/V2.9_GROWTH_122_FORWARD_EVALUATION_PROTOCOL.json`) is an observation of **one** future 20-session episode, not a current BUY strategy or sufficient OOS replication. Preserve its original sample, benchmark, costs, execution proxy and outcome embargo; do not reselect or optimize after inspecting it. New experiments require their own pre-outcome registered rules and valid decision-time source vintages.

Keep the V2.8.4/V2.8.12 prospective E-lane running independently and do not open Fold3/Fold4 or authorize V2.8.13. Do not re-run closed historical negative hypotheses, create a parallel monitor, or automatically restart cancelled one-off source expansion without identifying a direct missing requirement of the decision mainline.
