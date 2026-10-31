# V2.9 FY2024/2025 growth-quality experiment: DO NOT PROMOTE

Post-hoc robustness audit on already observed 2025 outcomes. No parameter retuning; no OOS claim.

| Measure | Growth + ROE primary | Revenue growth only | ROE only |
|---|---:|---:|---:|
| Selected issuers | 29 | 29 | 29 |
| Mean net price-index excess | +1.374 pp | +2.649 pp | -1.332 pp |
| Median net price-index excess | -0.701 pp | +0.216 pp | -1.934 pp |
| Stock mean net return minus matched-day random stock mean | -0.105 pp | +1.170 pp | -2.811 pp |
| Random draws at or above screen (NOT p-value) | 51.03% | 24.30% | 96.27% |
| Mean excess removing largest winner (post hoc) | -0.456 pp | +0.864 pp | -1.906 pp |

Primary selection: 14/29 positive excess outcomes; 5/7 entry-day groups have negative mean excess. Single top name SSE:688313 contributes +1.815 pp to the average.

## Per entry session: primary rule

| Entry session | Selected | Mean net price-index excess |
|---|---:|---:|
| 2025-03-31 | 4 | -1.869 pp |
| 2025-04-21 | 3 | +20.057 pp |
| 2025-04-23 | 4 | -0.529 pp |
| 2025-04-24 | 3 | -2.764 pp |
| 2025-04-25 | 3 | -1.505 pp |
| 2025-04-28 | 6 | +3.816 pp |
| 2025-04-30 | 6 | -3.468 pp |

## Decision boundary

Evidence strength: INSUFFICIENT. Primary rule: DO NOT PROMOTE. BUY: NOT AUTHORIZED.
Revenue-only looks better inside this already inspected sample but may not be promoted based on that observation.
These are price-only close-to-close proxies with a 30bp cost assumption, not verified economic total returns or live fills.
Same-entry-day conditional random is not matched on industry, size, liquidity or other risks.
Random tail percentages must not be treated as untouched-OOS p-values.

Blocking evidence:

- 2026_VENDOR_FINANCIAL_VALUES_NOT_CERTIFIED_HISTORICAL_ASOF
- 2025_OUTCOMES_ALREADY_OBSERVED_NO_UNTOUCHED_OOS
- UNADJUSTED_PRICE_ONLY_VS_PRICE_INDEX_NOT_TOTAL_RETURN
- SEVEN_CONCENTRATED_DISCLOSURE_TRADING_EPISODES
- ORIGINAL_REPORT_AMOUNT_TEXT_NOT_SEMANTIC_FIELD_VINTAGE_CERTIFICATION
- NO_VERIFIED_REALISTIC_EXECUTABLE_FILL_OR_STOP_TAKE_PROFIT_PATH
- PRIMARY_NOT_BETTER_THAN_SAME_ENTRY_DAY_RANDOM
- PRIMARY_NONPOSITIVE_MEDIAN_EXCESS
- PRIMARY_MEAN_REVERSES_WITHOUT_ONE_TOP_WINNER

No more optimization on this 2025 cohort. Continue with the already registered 2026-10-30 122-issuer prospective experiment and preserve its ORIGINAL CSI300 total-return benchmark, fixed entry/exit definition, 30bp costs, and all 122 missing-data outcomes.

Inputs are the frozen 128-company factor result, feature rows and exploratory specification. Run the standalone v29_growth_quality_nonpromotion.py script with --out-dir to regenerate both files.
