# V2.9 Core earnings: actual source-recovery evidence (research only)

## 2026-10-30 primary finding

The earlier A-tier set has 310 companies. In the original Eastmoney financial-summary RPT_LICO_FN_CPD source, Q3 2026 DEDUCT_BASIC_EPS was non-null for only 20 of 3,833 rows, and for only 1 of 310 A-tier issuers. The field is *deducted basic earnings per share*, not a reliable substitute for deducted parent net profit.

A separate public source, RPT_F10_FINANCE_MAINFINADATA, was tested live using the REST endpoint https://datacenter.eastmoney.com/securities/api/data/v1/get (source HSF10; client PC). Its KCFJCXSYJLR and KCFJCXSYJLRTZ fields returned non-null deducted parent profit and related YoY growth for two named, matching test securities. One existing example from the full income statement RPT_F10_FINANCE_GINCOME: 600078.SH, 2026 Q3 report, parent profit 264724884.25 yuan, deducted parent profit 259509358.65 yuan, statement notice 2026-10-28. The MAINFINADATA response also returned issuer ORG_CODE and NOTICE_DATE for matching. The bank BINCOME endpoint returned the analogous fields for a bank test issuer. These facts are source capability tests, not validation of any investment hypothesis.

The fixed pre-2026-10-30 exclusive notice-date filter worked for both MAINFINADATA periods: source row counts were 4,645 for 2026-09-30 and 13,484 for 2026-06-30 in the diagnostic. Those are **unreconciled provider row counts**, NOT 310 matched companies; duplicate report grain, amendments, and missing A-tier identity matches must be measured on a complete byte-preserved capture.

## Source and scientific controls

The new v29_growth_core_earnings.py collects both periods with one publicly queried report name rather than 310 per-security requests. Each page must keep invariant pagination metadata; each page SHA256 is retained. Only the pre-existing financial A-tier is considered; no new ranking, threshold, alpha score, return information, brokerage execution or BUY/ADD authorization.

A candidate counts as matched only if exact market/security ID, ORG_CODE, vendor notice date, original parent-profit amount, and cutoff-compatible UPDATE_DATE all agree. The original A-tier financial source pages are also verified against their saved SHA256 hashes. Ambiguity and missing/contradictory data remain UNKNOWN and must not be silently promoted. The nonrecurring component is a *descriptive* parent-minus-deducted difference; a negative figure is not automatically fraud or bad company quality.

The captured report is **not independently audited issuer financials**. Official original exchange reports may disagree or be restated. The captured provider data cannot be retroactively labeled historical point-in-time research data. Results do not constitute out-of-sample validation.

## Next acceptance

1. Deterministic offline unit tests for source pages, pagination, raw financial identity join and no BUY promotion.
2. One complete live capture of both period sources followed by source-hash verification and the precise matched / unavailable A-tier counts.
3. Check a representative subset against the original exchange-issued Q3/H1 reports and then attach valuation and available trading-liquidity context. Only research candidates may be emitted; production BUY depends on separate prospective/out-of-sample strategy admission.

Run from a locally preserved financial source archive using the mainline script --financial-review, --financial-raw-dir, --core-raw-dir and --output arguments. Never upload private holdings. No V2.8.12 E-layer or Fold3/Fold4 research data is read or changed.

## Acceptance update: completed 2026-10-30

The previous pending real coverage requirement has now been **executed**: GitHub Actions run 41023214144 passed full Q3/H1 ingestion and 310/310 company-level source reconciliation; 310/310 deducted parent-profit fields available, 1 nonpositive Q3 cumulative and 2 nonpositive standalone Q3. See [the verified receipt](../research/V2.9_GROWTH_310_CORE_PROFIT_REAL_REVIEW_20261030.md). No financial data was labeled as historically PIT-certified or alpha-validated. The standalone market valuation feed still lacks full real coverage due upstream HTTP 502 and remains separate from this completed source-quality work.
