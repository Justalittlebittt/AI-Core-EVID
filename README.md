# AI Core EVID

AI Core EVID is a personal A-share evidence and decision-discipline research system.

Its primary objective is **not** to predict the market with certainty or maximize return. Its job is to determine whether available evidence is strong enough to permit a contemplated action and whether that action violates precommitted risk and discipline rules.

## Current architecture direction — V2.9

V2.9 consolidates governance into a minimal-responsibility architecture:

```text
Governance Kernel
    ├── Evidence Engine
    ├── Validity Engine
    └── Discipline Engine
```

### Governance Kernel

Owns only system-level invariants, hard-gate definitions, scope boundaries, version binding, and cross-layer semantic consistency.

The five constitutional invariants are:

1. No leakage.
2. No silent sample mutation.
3. No undocumented override.
4. No unsupported certainty.
5. No goal drift away from reducing emotion-driven investing errors.

Canonical contract:

- `evidence/V2.9_GOVERNANCE_KERNEL.json`

### Evidence Engine

Owns point-in-time evidence integrity, provenance, temporal/vintage correctness, signal inputs, and leakage prevention.

### Validity Engine

Evaluates evidence strength rather than forcing every research question into PASS/FAIL. Core dimensions include effect size, simple baselines, OOS, regime stability, cross-sectional stability, transaction costs, drawdown, calibration, sensitivity, and failure regions.

Research-strength outputs are:

- `STRONG`
- `MODERATE`
- `WEAK`
- `INSUFFICIENT`

### Discipline Engine

Evaluates action eligibility and risk-rule compliance. Preferred semantics are `BUY_ELIGIBLE`, `ADD_BLOCKED`, `EXIT_REQUIRED`, etc.; the system does not claim guaranteed market direction.

Canonical foundation:

- `evidence/V2.9_VALIDITY_AND_DISCIPLINE_FOUNDATION.json`

## Problem ownership

Every newly discovered issue must first be classified:

- **SYSTEM_CRITICAL** — can alter sample identity, time information set, model/selection rules, OOS/prospective integrity, material evidence identity, or trading discipline. These may hard-block.
- **RESEARCH_UNCERTAINTY** — small samples, weak effects, wide intervals, regime instability, calibration uncertainty. These must remain uncertainty, not become engineering projects.
- **EXTERNAL_OPERATIONAL** — HTTP 5xx, queue delays, transient network/PDF/provider failures. Retry/cache/degrade/record; escalate only if they can alter a system-critical property.

A new workflow/gate/amendment/receipt/probe is not admitted merely because it is “more complete” or “more rigorous”. It must prevent a concrete system-level failure: leakage, silent mutation, invalid inference, or risk-discipline failure.

## Backward compatibility

V2.9 is prospective architecture consolidation. It does **not** rewrite frozen historical evidence or silently change old pass conditions.

The already-active V2.8.12R R1 technical gate remains binding until explicitly closed under its existing contract. Existing V2.8.12R thresholds, frozen windows, classifier rules, and R2 authorization conditions are unchanged by V2.9.

## Current transition status

- `V2.8.12R R1 Technical Gate`: **BLOCKED / repair in progress**.
- The two ambiguous frozen windows have been rechecked source-only without price/return access.
- `2023Q1 anchor1` currently returns zero candidates.
- `2023Q2 anchor1` currently returns one materializable candidate and that candidate is selected by the original deterministic R1 selection rule.
- Required downstream candidate repair: announcement `1216331011` (`SZSE:300956`).
- Historical blocked-window identity is no longer required for the next repair step.
- V2.8.12R R2 remains unauthorized until the original technical gate is explicitly satisfied.

Canonical audit:

- `evidence/retrospective_feasibility/V2.8.12R_R1_AMBIGUITY_SET_SELECTION_AUDIT.json`

## Integrity consolidation

Before retiring any legacy governance control, V2.9 requires an Integrity Exit Audit. Every active control is classified as one of:

- `CONSTITUTION_KEEP`
- `ACTIVE_COMPATIBILITY_KEEP`
- `DIAGNOSTIC_ONLY`
- `REDUNDANT_RETIRE_FROM_ACTIVE_PATH`
- `UNRESOLVED_BLOCKER`

Retirement means removal from the future active decision path, **not deletion of historical evidence**.

Contract:

- `evidence/V2.9_INTEGRITY_EXIT_AUDIT_CONTRACT.json`

Lightweight structural/semantic validator:

- `scripts/v29_governance_kernel_validator.py`

## Current transition rule

1. Close the already-active V2.8.12R R1 technical gate without weakening it.
2. Run the V2.9 Integrity Exit Audit.
3. Consolidate future governance under the single Governance Kernel.
4. Build the frozen Strategy Validity evaluator.
5. Build Discipline Engine v1 as eligibility/risk logic, not autonomous brokerage execution.

The architecture intentionally avoids creating new governance layers unless they prevent a defined system-critical failure.
