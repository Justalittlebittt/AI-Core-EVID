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
