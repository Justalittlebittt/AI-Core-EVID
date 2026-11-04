# Mainline integration inventory — updated 2026-11-02

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
| General evidence-strength mapping | `evidence/V2.9_EVIDENCE_STRENGTH_MAPPING_CONTRACT.json` and `scripts/v294_evidence_strength_synthesizer.py` | REUSABLE_FROZEN_FOUNDATION | Experiment-specific pre-outcome criteria and independent validity evidence still missing; no real strategy strength is established |

## Scope gate

Do not reuse prospective V2.8.4/V2.8.12 outcome data or Fold3/Fold4 in any demo, product slice, ranking or backtest. No fabricated real current signals. A fail-closed, synthetic demonstration is engineering validation, not a completed real-security Decision Case.

## Next executable user-value step

The real historical identity-bound no-action example is verified and the general strength mapping already exists. The **only decisive scientific blocker** to a BUY-supporting strategy is an independently verified, predeclared candidate rule with reliable decision-time vintages, realistic post-cost execution and a genuinely unobserved evaluation. Source-bound 2026-Q3 issuer reviews and the frozen 122-issuer experiment are useful research, but do not promote an action. Reuse current validation, decision and watchlist modules. Do not add another monitoring workflow or evidence-strength framework.

## 2026-10-27 checkpoint 2: verified full historical PIT cross-section

GitHub Actions [#40484949348](https://github.com/Justalittlebittt/AI-Core-EVID/actions/runs/40484949348) verified the new full-PIT as-of option in scripts/v29_pinned_historical_rank.py against the pinned AlphaDojo dataset revision and the independently hash-checked V2.8.1 PIT membership ledger.

- As-of date: 2026-09-09, not current trading data.
- PIT-active identities: 5,217; securities ranked: 5,198; excluded: 19 (11 without as-of bar and 8 lacking the required 21 bars).
- All ranks are based on unpromoted historical 20-session close returns; no current strategy, predictive validity, independently certified adjustment semantics, or live-buy authority is claimed.
- A real-identity historical Decision Case was produced for SZSE:300862. Its action result is NO_ACTION_INSUFFICIENT_EVIDENCE. Its risk inputs are explicitly **synthetic demonstration fields**, not user holdings.
- The Actions run provides complete ranking and example decision JSON as a 14-day downloadable artifact; the scripts and pinned hashes make this reproducible beyond artifact expiry.
- Actual completion: full historical descriptive candidate pool and fail-closed case. Not completed: scientifically admissible current candidate-selection rule, current data feed, real human-specified risk/position inputs and any authorized BUY decision.

No frozen prospective evidence, Fold3/Fold4, scientific threshold, sample or authorization was altered.

## 2026-10-27 follow-up: independent close-location exploratory test

- Original preregistration: `research/EXPLORATORY_CLOSE_LOCATION_V1.json`, committed first at `a89632c1f0af3e55aabf50bcff8620396ad628f1`.
- Full offline and pinned-data Actions result: [#40492636735](https://github.com/Justalittlebittt/AI-Core-EVID/actions/runs/40492636735), after correcting a synthetic-only coverage assertion.
- 410 evaluated signal dates, 210,901 selected security-date events, 210,408 resolved outcomes (99.7662%).
- Mean selected-net minus same-day eligible A-share equal-weight gross five-session return: **-0.52237 percentage points**; 2025 = -0.59084 pp, 2026 nonpristine chronological = -0.42274 pp. All seven quarters negative; preregistered 20-day block-bootstrap fifth percentile = -0.61196 pp.
- Terminal decision: **NOT SUPPORTED**. Permanent record: `research/CLOSE_LOCATION_V1_RESULT.md`; Actions artifact `exploratory-close-location-v1` contains complete daily results.
- This does not validate a stock predictor. Do not reverse the signal, retune deciles or revisit the pre-registered 2025–2026 sample as untouched OOS.
- Priority: avoid serial retrospective factor roulette on previously viewed windows. Preserve present no-action and user-supplied-position monitoring capabilities, and design any future predictive study around an independently frozen, genuinely unobserved prospective sample and economically realistic execution assumptions. Do not add additional monitoring scaffolding merely to record failed retrospective hypotheses.

## 2026-11-01: real-issuer research reviews without synthetic risk placeholders

The FY2024 as-disclosed integration case is a valid *engineering test* but takes synthetic risk inputs from the Decision Packet demo. For the two already researched 2026-Q3 issuers, a separate read-only research review now exists:

```bash
python scripts/v29_current_issuer_research_review.py
```

This reads the existing `research/V2.9_ISSUER_VALUATION_SENSITIVITY_20261030.json` and outputs the real source-bound 2026-10-29 quoted prices and 2026-10-30 research context for `SZSE:300408` and `SSE:688002`. It preserves exact input SHA256 and cited public research/quote URLs. **It is not a V2.9 Decision Packet**: no hypothetical risk inputs are manufactured; the Discipline Engine is not invoked; contemplated trade and stop/take-profit/position fields remain `null`, and BUY/ADD remain unauthorized. This is a practical honest candidate-review deliverable, not an empirical alpha or a current-day quote, and does not revise any frozen evidence or risk rules.

The next scientific bottleneck remains future cost-aware independent validation of an actually predictive rule. Once a qualifying strategy exists, an intended trade requires *real human-specified risk parameters* in the existing V2.9 packet, not these research-only records.

## 2026-11-02 subtractive mainline execution decision

This section records priorities **without introducing a new gate, workflow, classifier, strategy or trading authority**.

1. **REUSE:** Keep `v290_strategy_validity_evaluator.py`, `v291_portfolio_path_evaluator.py`, `v294_evidence_strength_synthesizer.py`, `v29_decision_packet_adapter.py`, `v29_discipline_engine.py`, and existing `v29_daily_review.py`. Use `v29_current_issuer_research_review.py` for the two source-bound real issuers without inventing risk fields.
2. **PROTECT:** Preserve the existing 122-name prospective experiment and its 2026-10-30 freeze (`research/V2.9_GROWTH_122_FORWARD_EVALUATION_PROTOCOL.json`). Its fixed 2026-11-02 entry-session close acquisition is scheduled after that day's market close; **run status, price capture and outcome validity must be confirmed from actual evidence**, not forecast. The 20-session episode is descriptive even if positive and cannot establish a repeatable BUY-eligible rule on its own. Independently preserve V2.8.12's blind E accumulation and its unchanged information gate.
3. **DO NOT REOPEN:** V2.8.1's nine nonpromoted price factors, V2.8.7–V2.8.10 rejected setup shapes, V2.8.12R descriptive-only E events, `research/OPENING_GAP_V1_RESULT.md`, `research/CLOSE_LOCATION_V1_RESULT.md`, and the 2025 growth-quality nonpromotion verdict are closed as originally tested. No parameter reversal or rescue on inspected returns.
4. **DEFER UNLESS ESSENTIAL:** The one-off frozen-256 original-source workflow's 2026-11-01 push capture was cancelled, so complete persisted 256-row source evidence is **not verified**. Its expansion does not itself certify 2023/24 publication-time PIT or alpha. Do not rerun it solely to improve historical completeness: first show which specific new, separately preregistered strategy test cannot proceed without those sources. Preserve existing 24-row research and one-off artifacts.
5. **NEXT DELIVERABLE:** One clearly specified, *prospectively assessable* real candidate-selection rule on an independently sourced future cohort, defining when data become available, selection/universe, costs, realistic execution, matched comparison and action frequency **before examining qualifying outcomes**. Reuse the existing engines to evaluate that cohort and produce real-security source-bound research cases; produce a full BUY/ADD Decision Packet only if the strategy genuinely qualifies and actual human risk inputs exist. Until then, report `INSUFFICIENT`/NO_ACTION and allow existing position-risk review.

Do not spend Fold3/Fold4, relax frozen E-layer gates, start V2.8.13, or invent current-day prices/positions to accelerate this plan.


### 2026-11-02 source-risk selection reconstruction (pre-outcome)

The original 2026-10-30 financial and F10 ZIP archives were independently reloaded with all preserved source-page SHA256 receipts checked. The frozen selection waterfall was reproduced exactly:

- **310** initial A-tier source-matched financial observations.
- **210** with none of six specific source-risk flags (84 margin-decline flags; 6 missing margin; 11 nonrecurring-share >50%; 6 ST-name warnings; 1 nonpositive cumulative deducted profit; 2 nonpositive standalone Q3 deducted profit; overlaps mean these are *not additive counts*).
- **122** of the 210 that additionally have Q3 YTD revenue growth YoY above H1 YTD and positive standalone Q3 deducted profit; **88** of the clean 210 were not selected.
- **100** of the original 310 were excluded by one or more specific source-risk flags; **49** of those 100 would pass the two simple numeric conditions but are still excluded from the actual frozen 122 sample.

Exact pre-outcome identities and risk-flag labels (without refetching later vendor revisions) are preserved in `research/V2.9_GROWTH_310_PREOUTCOME_SOURCE_RISK_FLAGS_20261102.csv`. All **310** records, **122** selected identities and **210** clean-stage memberships were reconciled against the previously saved source frame, with no price or return input.

**Interpretation correction:** the registered 122-versus-188 contrast evaluates the *entire original multi-stage selection policy*, not the isolated effect of revenue acceleration, of deducted profit, or of accounting-risk flags. It also does not sector/size-match the groups. Preserve the already-frozen comparison contract and do not reinterpret a one-period positive result as alpha or a live BUY authorization. The single-purpose offline evaluator `scripts/v29_growth_310_conditional_result.py` and five synthetic-only regression cases (`scripts/test_v29_growth_310_conditional_result.py`) are now committed. The existing `decision-mainline-regression.yml` runs these tests on relevant future pull requests; **no new workflow was created**. The real same-vendor/same-exit-vintage 310-issuer price-source file still does not exist, so NO authentic conditional return has been computed. Only after the parent study's 20th exchange session is verified closed and its `OUTCOMES_122.json` is available, run `python scripts/v29_growth_310_conditional_result.py --prices /private/310-same-vintage-prices.json` with a full 310-ID provenance-bound input. The CLI fails closed before maturity and never treats missing/untradeable names as zero-return or drops them. This comparison is a descriptive tool, not a new strategy or buy signal.

## 2026-11-02: one bounded pre-outcome conditional control, no new pipeline

The original 2026-10-30 source artifacts were retrieved and hash-checked before the 2026-11-02 entry-session market close. Exactly **310** pre-existing A-tier issuer identities reconciled with original F10 source rows; the frozen **122** are a strict subset, leaving **188** exact nonselected identities. To avoid an unfalsifiable broad-index-only interpretation, a **separate, supplementary** descriptive 122-versus-188 same-window comparison was predeclared and its minimal financial source frame preserved:

- `research/V2.9_GROWTH_310_CONDITIONAL_CONTROL_PREOUTCOME_20261102.json` — all fixed 310 issuer IDs, origin ZIP/hash, selected-122 authority, complement-188 hash, missingness and 20-session comparison semantics.
- `research/V2.9_GROWTH_310_PREOUTCOME_FINANCIAL_FRAME_20261102.csv` — 310 pre-outcome financial observations, marked SELECTED_122 or COMPARATOR_188; no future return, trade, BUY eligibility or portfolio exposure.

This does **not** modify the already frozen 122 experiment's sample, primary CSI300 TR metric, entry/exit dates, cost model, outcome embargo or execution code. The contrast isolates the descriptive *combined selection policy relative to the previously observed A-tier pool*, not a causal effect of any single accounting condition; neither arm is sector/size matched, and one market episode cannot validate a repeatable strategy. No immediate quote collection, new monitoring or independent BUY signal is justified by this artifact. Examine fixed 20-session outcomes only when legally/methodologically mature, preserve all 310 identities and report missingness without substitutions.


## 2026-11-02: lot-size replication feasibility, not an investable 122-stock result

A bounded **pre-entry, read-only** feasibility calculation reuses the original, immutable `research/V2.9_FORWARD_122_PREENTRY_SOURCE_FEASIBILITY_20261031.json` (2026-10-30 closing references; 122/122 source pairs verified) and the original 122-ID manifest. These are **not** 2026-11-02 trade fills or new forward outcome evidence.

- Exchange rules used: Shanghai/Shenzhen Main Board and ChiNext auction buys require multiples of **100 shares**; STAR Market (`SSE:688*`) auction buys require at least **200 shares** per order (additional shares after 200 can increment by one). References: https://www.sse.com.cn/lawandrules/sselawsrules2025/fund/trading/c/c_20260424_10817739.shtml ; https://edu.sse.com.cn/tib/ ; https://investor.szse.cn/institute/rules/t20230706_601604.html .
- Applying exact two-decimal archived closing prices to **102 ordinary A shares × 100 shares** and **20 STAR Market A shares × 200 shares** produces a total minimum-one-order notional of **RMB 794,397** (**RMB 405,873** ordinary; **RMB 388,524** STAR), before commissions, taxes, price movements and any permission or fill constraints. All 122 source identities match the sealed original manifest; this is an indicative fixed-date calculation, not proof all stocks can be bought.
- In that *minimum-order* basket, STAR Market stocks absorb **48.9080%** of stock notional despite only **16.3934%** of the names; the 10 largest minimum-order positions are **42.9603%** versus **8.1967%** under nominal 122-name equal weighting. The maximum minimum order is `SSE:688025`: 200 × RMB 328.66 = **RMB 65,732**, or **8.2745%** of the minimum-order basket versus the hypothetical equal-stock target **0.8197%**.
- **Necessary, not sufficient, equal-weight capital bound:** allocating at least RMB 65,732 to *every one* of the 122 positions requires at least **RMB 8,019,304** stock notional even before integer share increments, transaction fees and liquidity; exact equal weighting may require more or be arithmetically impossible at a fixed notional. For an illustrative RMB 1,000,000 account, the minimum-order basket alone consumes RMB 794,397 and leaves RMB 205,603 unallocated; that arrangement does **not** replicate the frozen equal-weight study.
- **Decision:** Keep the original frozen 122 mean-return experiment scientifically unchanged. Its equal-weight hypothetical stock-return average must **not** be presented as a feasible small-account portfolio result. Any future real BUY-supporting policy requires separate evidence for a *smaller capital- and lot-aware portfolio*, contemporaneous tradeable price, eligible account permissions, human risk limits, realistic commissions/slippage, and an independently validated selection advantage. No new strategy or BUY authority is created by this feasibility result.


## 2026-11-02 post-registration, read-only quality review of frozen eight names

The eight-name exploratory subset was **sealed at 2026-11-02 14:52:20 Beijing** (commit `d61be865`), *before* the 15:00 market close. **The findings in this section were analyzed afterward**, using only issuer 2026-Q3 filings dated **2026-10-17 through 2026-10-28**, already public before selection. This is post-registration **descriptive source verification**, NOT a predeclared factor, rule amendment, selection override, or evidence of future returns.

Cash-flow quality diagnostic: operating cash flow from **2026 January–September divided by 2026 January–September parent-attributable net profit**. All input magnitudes are taken from each linked Q3 filing; this ratio is **not** earnings quality certification, may be non-comparable across business structures and must not modify the eight IDs.

| Frozen issuer | Q3 issuer-report link | Operating cash flow / parent profit (9M) | Specific source qualification |
|---|---|---:|---|
| `SZSE:300199` 翰宇药业 | [2026-Q3](https://money.finance.sina.com.cn/corp/view/vCB_AllBulletinDetail.php?id=12663255&stockid=300199) | 86.65% | Research-driven pharmaceutical growth; high reported profit growth is not price alpha |
| `SZSE:002636` 金安国纪 | [2026-Q3](https://money.finance.sina.com.cn/corp/view/vCB_AllBulletinDetail.php?id=12664521&stockid=002636) | 46.73% | Copper-clad laminate, exposed to electronics/PCB materials cycle |
| `SZSE:301536` 星宸科技 | [2026-Q3](https://vip.stock.finance.sina.com.cn/corp/view/vCB_AllBulletinDetail.php?id=12660759&stockid=301536) | 26.98% | Operating cash flow far below accounting profit; inventory/working-capital growth warrants review |
| `SZSE:000408` 藏格矿业 | [2026-Q3](https://money.finance.sina.com.cn/corp/view/vCB_AllBulletinDetail.php?id=12646857&stockid=000408) | 28.67% | **RMB 4.708bn** share of Julong Copper equity-method earnings, **77.06% of parent profit**; disclosed RMB 4.617bn associated dividends may appear outside operating cash flow; do NOT classify the associate earnings automatically as nonrecurring |
| `SZSE:002463` 沪电股份 | [2026-Q3](https://vip.stock.finance.sina.com.cn/corp/view/vCB_AllBulletinDetail.php?id=12664696&stockid=002463) | 48.09% | Operating cash flow **-6.61% YoY** despite revenue +71.88% / parent profit +106.87%; receivables/inventory expanded |
| `SSE:603256` 宏和科技 | [2026-Q3](https://money.finance.sina.com.cn/corp/view/vCB_AllBulletinDetail.php?id=12654290&stockid=603256) | 86.69% | Electronic glass cloth; 126.41% asset increase includes new share issuance and borrowings, complicating comparisons |
| `SZSE:002552` 宝鼎科技 | [2026-Q3](https://money.finance.sina.com.cn/corp/view/vCB_AllBulletinDetail.php?id=12665376&stockid=002552) | 35.11% | Copper foil / electronic materials plus gold mining exposure; accounting growth does not determine executable investment merit |
| `SZSE:300223` 北京君正 | [2026-Q3](https://money.finance.sina.com.cn/corp/view/vCB_AllBulletinDetail.php?id=12667502&stockid=300223) | 72.48% | Semiconductor-memory price cycle and demand are correlated with other electronics exposures |

**Read-only aggregate:** median of these eight company ratios is **47.41%**, with **5/8 below 50%**. This is *not* a normalized factor score; parent profit and operating cash flow are financially different measures (notably equity-method associates). At least five names (`002636`, `301536`, `002463`, `603256`, `300223`) share semiconductor/PCB/electronics supply-chain sensitivities; `002552` has mixed copper-foil and mining activities. The narrow eight-security basket is **not** proven sector diversified and risks correlated drawdowns. No same-window portfolio outcomes or return data were read for this diagnostic.

**Non-negotiable disposition:** retain precisely the already committed eight identities and existing 122/188 cohorts, 20-session horizon, source observation and 30bp expense. These after-freeze diagnostics are interpretive only and cannot become retroactive exclusion/reranking/position-sizing inputs, a rescued historical factor, or permission to BUY. Independent repeated after-cost alpha and real capital/stop/permission/quote checks remain required.

## 2026-11-03 historical 256 evidence reconciliation

Read-only cross-file check; **not** a return backtest or PIT/OOS promotion.

- Frozen FY2022 and FY2023 issuer-year source frames: **128 + 128 = 256** (distinct cohort-year observations). Source: `evidence/v29_original_2023_2024_reports_256/HISTORICAL_256_OFFICIAL_DISCOVERY.json`.
- Unique official annual-report metadata: **123 + 127 = 250/256**. 2026 retrospective vendor records: **124 + 127 = 251/256**. Official report/date plus all four finite retrospective financial values: **118 + 126 = 244/256**. Source: `research/v29_prior_financial_source_256/FINANCIAL_256_VENDOR_COVERAGE.json`, matched by cohort year and security identity to official reports.
- These 244 retrospective vendor records were **all updated after the original report announcement day**; none of their vendor values is independently certified to be an original 2023/2024 vendor vintage.
- **Avoid the false zero count:** `research/v29_original_table_24_20261031/FIXED_24_ORIGINAL_YEAR_TABLE_FIELDS.json` already contains an independent 24-case original-PDF current-fiscal-year table audit. It overlaps the historical 256 exactly and has **15/24 original reports with all four table fields extracted**. All 15 overlap the 244 preliminary candidates. The remaining **229/244** do not have equivalent four-field original-PDF certification in these audited receipts.
- **Not a 15-observation return study:** the 15 original source records still require valid trading-session-aligned, corporate-action-aware entry/exit and matched benchmark evidence before any historical return comparison. 2026-retrieved PDF bytes also do not establish a release-date binary seal.
- No whole-256 historical post-filing 20-session matched-price result was verified in this audit. The separate **two-issuer FY2024-to-2025 descriptive price case** is not a substitute for the frozen 256 cohorts (`scripts/v29_2025_filing_to_return_case.py`).
- Source-coverage and original-table work can be reused; **do not reacquire or recalculate the completed 15 cases**, do not drop the other 241 identities, and do not call retrospectively assembled 2023/2024 samples pristine OOS.
- **Current admission:** historical independent alpha **NOT VALIDATED**; live BUY **NOT AUTHORIZED**.

## 2026-11-03 historical original15 observed outcomes and ST selection audit

**Source-authenticated descriptive audit only, not validated alpha or paper fills.**
- Read immutable original-year-field 15/24 authority, research 256 cohort denominator, and live repository receipts `research/v29_historical_original15_price_pair/PRICE_PAIR_COVERAGE_15.json` and `RAW_15_MARKET_AND_CALENDAR.json`, archived by commit `28d77d1613c4`. The raw capture receipt identifies SHA256 `bfa0747f79daea3a39ff9354fcacd73fb19962bc6ec4158faf25a42f3d8e2166`.
- **15/15** preselected issuer-years have numeric positive unadjusted and forward-adjusted first-post-announcement and 20th-session close *endpoints*. **13/15** passed the script's stricter entry/exit non-ST filter; the other **two have price observations, not missing price data**. All 15 endpoint records show `tradestatus=1` and positive reported volume; neither price observability nor positive volume guarantees an executable close fill.
- `SZSE:002177` (FY2022) was ST on both 2023-05-04 entry and 2023-05-31 exit, but quotes were present (price-only sensitivity, adjusted minus 30bp: **+0.5310%**). `SZSE:000070` (FY2023) was non-ST on 2024-04-29 entry, then ST by 2024-05-29 exit; its price-only sensitivity is **-44.4032%** after assumed 30bp. **Treating ST at exit as necessarily untradeable and excluding the result introduces outcome-dependent selection risk**; do not relabel ST as suspension.
- The 13 filter-passing cases: descriptive *later-vintage adjusted* equal-observation average **+5.3559%** net of 30bp, median **-0.5621%**, **6 positive / 7 negative**. Excluding largest winning observation `SSE:688416` (+54.5501% net) reduces mean to **+1.2563%** for 12. Excluding second-largest winning observation `SSE:600088` (+20.3633% net) yields **-0.4806%** mean for 11.
- **Price-only sensitivity for all fixed 15 including both ST-flagged quotes**: mean **+1.7169%** and median **-0.5621%** after uniform 30bp cost. This is neither a filled/tradable portfolio nor an allowed alteration of the strict 13-case cohort; it transparently exposes excluded outcomes.
- No same-session historical matched benchmark (price or total-return) is included in this 15-name receipt. No original historical-time price-vintage seal, corporate-action-inclusive *economic* total return guarantee, tradeability at exchange price limits, profit-taking/stop execution, or independent unseen OOS cohort. These results **do not establish signal efficacy**. The 15 source-table-complete cases were found retrospectively in 2026 after 2023/2024 outcomes existed.
- **Decision:** DO NOT promote a BUY factor or expand historical sampling on the basis of the positive 13-case mean. Keep archived 15-case evidence untouched; retain the 2 flagged rows as mandatory outcome sensitivities; prioritize authentic 2026 prospective study and its original H00300 baseline over expanding defensive plumbing.

## 2026-11-03 Historical original15 CSI300 PRICE benchmark completion

**Complete retrospective historical market comparison, NOT alpha admission:**

- Existing original-15 GitHub job archived `research/v29_historical_original15_price_pair/index_comparator/BENCHMARK_MATCHED_15.json` and `RAW_CSI300_PRICE_INDEX_2023_2024.json` in commit `be2170e63665`. Coverage **15/15** stock-index date-matched pairs with frozen 15-source population. Index = retrospective BaoStock `sh.000300` **PRICE**, NOT H00300 total return.
- Equal-observation stock adjusted-close return minus assumed 30bps, *minus same-window CSI300 price return*: full **15** mean **+2.9457 percentage points**, median **+0.3748pp**, **8 positive / 7 negative**. Original non-ST-at-entry-and-exit **13** mean **+6.3094pp**, median **+0.3748pp**, **7 positive / 6 negative**.
- FY2022 source group **7** mean **+13.2128pp**; FY2023 source group **8** mean **-6.0380pp**. In the non-ST 13, excluding the largest excess-return case reduces mean from **+6.3094pp** to **+1.8102pp**; excluding top two produces **-0.1584pp** (11 cases).
- **Study-population error to avoid:** the fifteen cases were selected because original-report PDF table fields were independently extractable, *not* by the predeclared 2026 financial-growth selection criterion. These figures cannot test or promote the growth signal, regardless of sign. The 2023/2024 outcomes existed long before the 2026 retrospective study. ST-at-exit filtering introduces survivorship/selection risk, including the documented -44.4% price sensitivity for SZSE:000070.
- **Conclusion:** historical *source and market coverage* of the original-15 pilot is complete; no more re-query for this comparison is necessary. Neither full economic total return, original-time PIT quotes, trade fills, benchmark TR, nor independent OOS alpha was validated. Trading remains **NOT AUTHORIZED**. Focus on the unchanged prospective 2026 frozen cohort instead.

## 2026-11-04 clean-88 supplementary comparison, after entry but before outcome

2026-11-04 **post-entry, pre-maturity** descriptive clarification, not a revision to the originally frozen 2026-11-02 trial. The original, primary `122 vs 188` conditional comparison remains unchanged. The full 188 nonselected names include **88 original no-specified-risk-flag names** and **100 names with source-risk flags**. Consequently, a positive 122-vs-188 difference would not identify the specific contribution of the revenue-acceleration + standalone deducted-profit selection rule.

Reuse the **same original 310-ID source-risk flag CSV**, and only the **same original 310 price observations**, to additionally report `122 selected vs clean nonselected 88` as a secondary observational contrast. There is no additional network request, user intervention, future-source lookup, extra schedule, candidate identity change, risk threshold change, trading permission, or shift in the original `122 vs 188` primary statistic. Incomplete 310 source data cause both comparison metrics to remain null; preserve all original sample identities.

Original pre-outcome fixed assets: `research/V2.9_GROWTH_310_PREOUTCOME_SOURCE_RISK_FLAGS_20261102.csv`, `research/V2.9_GROWTH_310_CONDITIONAL_CONTROL_PREOUTCOME_20261102.json`. Evaluator: `scripts/v29_growth_310_conditional_result.py`. Synthetic tests in `scripts/test_v29_growth_310_conditional_result.py` were **confirmed PASS** via GitHub Actions run [41766381166](https://github.com/Justalittlebittt/AI-Core-EVID/actions/runs/41766381166).

This secondary contrast was specified **after the Nov 2 entry date**, though before the still unobserved Nov 27 twenty-session exit. Therefore it is neither the primary pre-entry preregistration nor a pristine replication; no alpha or BUY admission is permitted from this supplementary metric.
