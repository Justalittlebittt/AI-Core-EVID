# Mainline integration inventory — 2026-10-26

Purpose: first checkpoint in [Decision-first mainline](../MAINLINE_DECISION_FIRST.md). This is an evidence-based repository code inventory, not a claim that historical strategies are live-eligible.

| Necessary part | Located existing component | Status | Binding limitation |
|---|---|---|---|
| Historical factor research | `scripts/v281_stage1_factor_screen.py` | REUSE_AS_RESEARCH_ONLY | Hardcoded historical PIT/source receipts and retrospective-screen governance; not a production current-date ranking API |
| Event-level validity | `scripts/v290_strategy_validity_evaluator.py` | REUSABLE | Expects validated observations, no invented strength |
| Portfolio-path validity | `scripts/v291_portfolio_path_evaluator.py` | REUSABLE | Requires upstream execution-resolved chronological path |
| Decision packet validation | `scripts/v29_decision_packet_adapter.py` | REUSABLE | Strict fields/hashes and fail-closed behavior; source hashes are identity checks, not empirical proof |
| Investment discipline | `scripts/v29_discipline_engine.py` | REUSABLE | Human-supplied risk fields, no implied brokerage execution |
| Integrated no-action example | `scripts/v29_decision_case_demo.py` | SYNTHETIC_SLICE | Checks wiring only, cannot justify purchasing DEMO:000001 or any listed equity |
| Production PIT candidate screener | No general-purpose production entry point established in this inventory | NOT_YET_VERIFIED | Must determine universe, PIT source/vintage, strategy rule and reproducible ranking |
| Current-price/watcher with holdings | No production storage/position watcher established in this inventory | NOT_YET_VERIFIED | Must bind entered positions, state changes and review/exit rules without guessing fills |
| Evidence-strength preregistration | `README.md` identifies this as pending | BLOCKED_BY_PREREGISTRATION | Cannot assert STRONG or MODERATE based on retrospective outcomes |

## Scope gate

Do not reuse prospective V2.8.4/V2.8.12 outcome data or Fold3/Fold4 in any demo, product slice, ranking or backtest. No fabricated real current signals. A fail-closed, synthetic demonstration is engineering validation, not a completed real-security Decision Case.

## Next executable user-value step

Reuse existing historical factor data loader where legally accessible and provenance-appropriate **without** importing frozen prospective outcomes, define independent security as-of universe / data-vintage feed, then emit a verifiable historical candidate ranking with as-of inputs. Only then bind a security to a decision case. Do not expand monitoring tooling to accomplish this.
