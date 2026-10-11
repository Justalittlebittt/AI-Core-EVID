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

The prospective E-layer remains outcome-blind by contract. Its post-Epoch-2 runtime and scheduler operation are **not currently verified**; see the project DAG for operational blockers.

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

A qualitative evidence-strength mapping and synthetic synthesizer now exist, but **real strategy scoring remains unperformed**. Any experiment-specific numeric thresholds must be preregistered before outcome inspection.

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

## Current mainline priorities (as of 2026-10-11)

### Verified foundations versus research claims

- Governance, event-level/portfolio-path validity calculations, Decision Packet, and Discipline Engine have implemented foundations. Local critical Discipline/Packet regression is recorded in `evidence/V2.9_DISCIPLINE_POST_BASELINE_RUNTIME_RECEIPT_1.json`; **central end-to-end runtime is not claimed**.
- The evidence-strength **mapping contract already exists** at `evidence/V2.9_EVIDENCE_STRENGTH_MAPPING_CONTRACT.json`, with synthesis code at `scripts/v294_evidence_strength_synthesizer.py`. A new blanket threshold contract is not the next task. Specific numeric criteria for a future real experiment require pre-outcome registration, and **real strategy strength has not been scored**.
- V2.8.8 selected no setup; V2.8.10 rejected pure-price AC entry expansion. V2.8.12R finished **descriptive-only** due insufficient samples. None of these results authorizes a BUY/ADD strategy.
- V2.9.2 Batch-3 remained incomplete; V2.9.3 is static-ready only, with Chunk 3 outstanding and Batch-4 prohibited. GitHub-hosted execution provisioning remains unverified.
- V2.8.4 prospective Epoch 2 was restarted at 2026-09-27 following a coverage gap; post-change runtime validation is outstanding. No historical data can be relabeled prospective.

### Independent A-share market risk research (descriptive MVP, not live trading)

- `scripts/ashare_market_risk_descriptive.py` calculates 20/60-session realized volatility and the trailing 252-observation RV20 empirical percentile for CSI300 (000300.SH) and STAR50 (000688.SH) from caller-supplied, provenance-labeled daily close snapshots.
- `scripts/ashare_market_risk_akshare_fetch.py` is an **optional**, free AKShare/Eastmoney snapshot adapter. Source availability and real-market data retrieval are not yet runtime-validated. Use a separately saved immutable snapshot, never silent live data substitution.
- `validation/ashare_market_risk_descriptive_selftest.py` covers synthetic mechanics, as-of exclusion, source-mixing rejection, missing series, constant series, and UTC timestamp validity. Unit tests do **not** prove forecasting skill or real-data quality.
- No implied-volatility series, calibrated risk probability, actual return advantage, setup admission or brokerage actions are claimed by this descriptive MVP.

Run after obtaining a vetted snapshot:

```bash
python scripts/ashare_market_risk_descriptive.py --input-csv path/to/prices.csv --as-of YYYY-MM-DD
```

Optional AKShare acquisition (requires its external installation/network availability):

```bash
python scripts/ashare_market_risk_akshare_fetch.py --start-date 2024-01-01 --end-date YYYY-MM-DD --output-csv path/to/immutable_snapshot.csv
```

### Active next decisions

1. Validate the free index snapshot against market dates and independent index closes, then publish a dated **descriptive** risk report; add no arbitrary buy/sell thresholds.
2. Reuse the existing fail-closed Discipline Engine for user-provided risk/exit-rule inputs. Do not promote missing or synthetic strategy evidence to STRONG/MODERATE.
3. Preregister a distinct, economically justified selection experiment before inspecting outcomes; previously rejected setups remain rejected.
4. Keep Batch-3 and prospective Epoch 2 as independent, explicitly blocked/awaiting-runtime branches, not a global blocker for market-risk research.

The primary goal remains reducing emotion-driven investing errors, not guaranteeing market prediction.
