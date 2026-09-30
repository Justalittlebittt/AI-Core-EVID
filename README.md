# AI Core EVID

AI Core EVID is a personal A-share evidence and decision-discipline research system.

Its primary objective is **not** to predict the market with certainty or maximize return. Its job is to determine whether available evidence is strong enough to permit a contemplated action and whether that action violates precommitted risk and discipline rules.

## Current architecture — V2.9

```text
Governance Kernel
    ├── Evidence Engine
    ├── Validity Engine
    │     ├── Event-level evaluator
    │     └── Portfolio-path evaluator
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

Evidence strength remains unscored until a separately frozen, pre-outcome threshold contract is defined.

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

## Current next stage

The architecture and metric foundations are now sufficient to define the next research-layer contract:

**V2.9 Evidence Strength Threshold Contract**

That contract must be frozen before seeing the results of a qualifying future experiment. It must map predeclared validity dimensions into `STRONG / MODERATE / WEAK / INSUFFICIENT` without tuning thresholds to rescue observed outcomes.

No current V2.8.12 prospective E outcome data, fold3, or fold4 should be opened merely to design those thresholds.
