# Closing-location strength — preregistered exploratory historical result (2026-10-27)

**Research disposition: NOT SUPPORTED; no candidate promotion, evidence-strength upgrade, or BUY/ADD eligibility.**

## Preregistration and execution provenance

- Independent hypothesis: top 10% of PIT-eligible stocks by close location `(close_D-low_D)/(high_D-low_D)` at D-close may outperform the same-day equal-weight eligible universe over the next five joint A-share sessions.
- Original contract: [EXPLORATORY_CLOSE_LOCATION_V1.json](EXPLORATORY_CLOSE_LOCATION_V1.json), committed at `a89632c1f0af3e55aabf50bcff8620396ad628f1` **before** running outcomes; Git blob SHA `1efdccdc9327f39e3e2887620a2821bf1f5338b5`.
- Scientific decisions (direction, signal decile, sample windows, cost, comparison, moving-block bootstrap and qualification criterion) remained frozen.
- The first [Actions attempt #40492488688](https://github.com/Justalittlebittt/AI-Core-EVID/actions/runs/40492488688) stopped on a synthetic-test expectation error: the synthetic fixture had 1/2 selected outcomes resolved, but the test incorrectly asserted 0/2. This did **not** process the real study's outcomes.
- Corrected **only** the synthetic coverage assertion, without changing the study contract or study code. Final [Actions #40492636735](https://github.com/Justalittlebittt/AI-Core-EVID/actions/runs/40492636735) passed the five synthetic tests and executed the pinned historical study. Full per-day result was uploaded as artifact `exploratory-close-location-v1` (30-day retention).

## Predeclared setup

- Signal dates: 2025-01-02 through 2026-09-09, frozen joint A-share trading-day calendar.
- Universe: official V2.8.1 PIT intervals and verified vendor-stable stock universe. Prices: exactly pinned AlphaDojo stock dataset, with a separate pinned CSI300 benchmark.
- Selection: top 10% of each signal-day's valid high/low/close bar range position, canonical security ID tie-break.
- Outcome: reference D-close to D+5 joint trading-session close; **not proof of a tradable close execution**. A fixed **0.30%** hypothetical round-trip cost is subtracted from selected return.
- Primary comparison: mean of signal-date selected net returns minus same-day signal-eligible all-stock equal-weight **gross** returns.
- Development 2025 and chronological 2026 are both retrospectively observable: **2026 is not untouched or pristine OOS**. No Fold3/4 or frozen V2.8.12 prospective outcomes were inspected.
- Serial-dependence diagnostic: fixed-seed 2,000 resamples of contiguous 20-day blocks from daily excess; this does not turn overlapping D+5 returns into an executed portfolio path.

## Observed real-data findings

| Predeclared diagnostic | Observation |
|---|---:|
| Signal days evaluated | 410 |
| Selected security-date events | 210,901 |
| Resolved selected D+5 outcomes | 99.7662% |
| Mean selected-net less broad-market-gross D+5 return | **-0.52237 percentage points** |
| Mean selected-net less CSI300 D+5 return | **-0.26127 percentage points** |
| 2025 development mean primary excess (243 signal days) | -0.59084 percentage points |
| 2026 chronological **nonpristine** mean primary excess (167 signal days) | -0.42274 percentage points |
| 20-day moving-block bootstrap 5th percentile of mean excess | -0.61196 percentage points |
| 20-day moving-block bootstrap 95th percentile of mean excess | -0.39892 percentage points |
| Quarters with negative mean primary excess | **7 out of 7** |

All preregistered observation-availability criteria could be evaluated, but the positive-effect criterion failed: the primary mean, both retrospective partitions, and the moving-block lower bound were negative. No alternative decile, reverse signal, horizon, cost or date range was tried to rescue the result.

## Interpretation and final disposition

This particular *strong close-position* hypothesis did not improve average five-session stock selection under the preregistered illustrative historical comparison. The negative average is not a formal estimate of a live-tradable strategy return. Prices, corporate-action adjustment, limit-up/down tradeability, and ability to execute at an already-known D close remain unverified, and five-session outcomes overlap substantially.

**Do not** promote this effect, inverse-select low close-location as a post hoc replacement, or modify the thresholds after seeing these outcomes. Do not claim STRONG or MODERATE or authorize BUY/ADD.

The already-confirmed V2.8.1 nine-factor nonpromotion and the separate negative opening-gap reversion test likewise remain in force. Rather than keep trying candidate ranking formulas against already viewed 2025–2026 outcomes, the next product-research task should be a genuinely prospective, first-observation-frozen, independently data-vintage-bound candidate hypothesis, with explicit execution realism; the meantime product can issue fail-closed no-action cases and review user-supplied positions.

## Integrity

- Frozen historical V2.8.1 evidence, sample definitions and scientific thresholds: unchanged.
- V2.8.12 prospective E outcomes, Fold3/Fold4: not consumed.
- Brokers/live execution: not used.
- Scientific status: `EXPLORATORY_NOT_SUPPORTED_OR_INSUFFICIENT`, no trade authorization.
