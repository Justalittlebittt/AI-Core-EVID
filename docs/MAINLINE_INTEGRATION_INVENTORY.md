# Mainline integration inventory — updated 2026-10-27

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
| User-supplied holdings review | scripts/v29_daily_review.py, scripts/v29_position_watchlist.py, scripts/v29_exit_execution_readiness.py | REUSABLE_OFFLINE_NO_BROKER | Actual positions and sellability must be supplied; no orders, stored broker state or independently verified live feed |
| Evidence-strength preregistration | `README.md` identifies this as pending | BLOCKED_BY_PREREGISTRATION | Cannot assert STRONG or MODERATE based on retrospective outcomes |

## Scope gate

Do not reuse prospective V2.8.4/V2.8.12 outcome data or Fold3/Fold4 in any demo, product slice, ranking or backtest. No fabricated real current signals. A fail-closed, synthetic demonstration is engineering validation, not a completed real-security Decision Case.

## Next executable user-value step

The real historical identity-bound no-action example is now verified. The next blocker is a **predeclared candidate strategy with positive PIT/OOS validity evidence** and a separate current-vintage market data feed, not another monitoring workflow. Existing unpromoted ret_20 ranks cannot be treated as buy signals. Current watchlist review accepts private user-supplied positions but is not a validated full-market stock screener.

## 2026-10-27 checkpoint 2: verified full historical PIT cross-section

GitHub Actions [#40484949348](https://github.com/Justalittlebittt/AI-Core-EVID/actions/runs/40484949348) verified the new full-PIT as-of option in scripts/v29_pinned_historical_rank.py against the pinned AlphaDojo dataset revision and the independently hash-checked V2.8.1 PIT membership ledger.

- As-of date: 2026-09-09, not current trading data.
- PIT-active identities: 5,217; securities ranked: 5,198; excluded: 19 (11 without as-of bar and 8 lacking the required 21 bars).
- All ranks are based on unpromoted historical 20-session close returns; no current strategy, predictive validity, independently certified adjustment semantics, or live-buy authority is claimed.
- A real-identity historical Decision Case was produced for SZSE:300862. Its action result is NO_ACTION_INSUFFICIENT_EVIDENCE. Its risk inputs are explicitly **synthetic demonstration fields**, not user holdings.
- The Actions run provides complete ranking and example decision JSON as a 14-day downloadable artifact; the scripts and pinned hashes make this reproducible beyond artifact expiry.
- Actual completion: full historical descriptive candidate pool and fail-closed case. Not completed: scientifically admissible current candidate-selection rule, current data feed, real human-specified risk/position inputs and any authorized BUY decision.

No frozen prospective evidence, Fold3/Fold4, scientific threshold, sample or authorization was altered.
