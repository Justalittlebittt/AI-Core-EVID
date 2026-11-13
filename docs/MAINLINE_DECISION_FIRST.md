# Decision-first mainline — operating model V1

**Status:** Active development direction for new work upon merge; does not change frozen scientific contracts, historic evidence, or grant trading authority.

## One objective

Deliver a reproducible, point-in-time A-share decision-support loop: **candidate selection → evidence validation → action eligibility → position monitoring / disciplined exit → outcome feedback**. Optimize for preventing avoidable, emotion-driven investment errors; no guaranteed forecasts, autonomous trading, or return-maximization claim.

## What is a usable output?

One human-readable and machine-readable **Decision Case** for one security and an evaluation timestamp, with:
- security identity and timestamp; inputs' source, data vintage, missingness, and hashes;
- how the candidate was generated and the predeclared strategy/version;
- evidence strength and the underlying independently verified validity result, or `INSUFFICIENT` if not proven;
- contemplated action BUY/ADD/HOLD/REDUCE/EXIT, human-supplied risk fields, explicit eligibility outcome and reasons;
- precommitted invalidation, stop-loss, take-profit, review cadence, next permitted decision; uncertainty and no-action are acceptable;
- subsequent realized trade/observation separated from earlier decision-time evidence.

No recommendation is published without a traceable case; no BUY/ADD eligibility may be inferred just from an attractive candidate or synthetic test.

## Product lanes and ownership

| Lane | Meaning | Required output | Priority |
|---|---|---|---|
| A. Candidate and decision | Produce PIT-eligible A-share candidates, evaluate evidence, evaluate human-specified risk/action, track exits | One end-to-end auditable Decision Case | **P0 mainline** |
| B. Frozen prospective E-layer | Preserve V2.8.4 schedule, append-only receipts and V2.8.12 frozen gate | Independent observation evidence | Protected parallel lane; **not prerequisite** to unrelated A-lane implementation |
| C. Platform operations | Maintain runner, read-only failure discovery and necessary evidence access | Failure diagnosis only when it threatens A or B | On-demand support, not a product roadmap |

Research eligibility and risk gates remain binding. Product implementation may use *separately identified* public historical datasets and isolated fixtures, but may not borrow frozen prospective outcomes, Fold3/Fold4, or represent illustrative candidate rankings as statistically validated.

## Retain, reuse, retire

**Retain without rewriting:** `evidence/V2.9_GOVERNANCE_KERNEL.json`, existing V2.8.12/12R frozen contracts and evidence, historical provenance and pre-registration, fail-closed risk and discipline invariants.

**Reuse:** event-level and portfolio-path validity evaluators, Decision Packet adapter and Discipline Engine, existing evidence reader where suitable. Audit interfaces before invoking; never presume an implementation is a complete automated screen.

**Stop expanding:** new layers of diagnostic workflows, receipt chains, monitoring PRs, and operational contracts absent a demonstrated system-critical failure or a directly blocking Decision Case. Preserve deployed monitoring, avoid deleting historic receipts. No independent monitoring feature is allowed to outrank the mainline solely because it is easier to test.

## Only four delivery checkpoints

1. **Inventory integration inputs:** enumerate the actual candidate generator, PIT data adapters, existing validity evaluator, Decision Packet adapter, Discipline Engine, and position/state storage. Mark each as REUSABLE / MISSING / BLOCKED with one concrete repository path or evidence. **Do not invent a candidate engine.**
2. **One end-to-end isolated vertical slice:** from a frozen historical as-of date and openly identified non-Fold3/Fold4 fixtures, create one candidate and fail-closed Decision Case, using existing modules. No future bars at the as-of point. It may correctly conclude INSUFFICIENT. Test leakage, missing data, override failure, stop-loss and issuer identity.
3. **Historical testing and usable watchlist:** on a properly specified historical universe and benchmark, test screening effectiveness, portfolio-path assumptions, costs and risk controls, with OOS boundaries. Establish thresholds before looking at qualifying outcomes. If unavailable or insufficient, report the gap instead of claiming success.
4. **Read-only ongoing decision cadence:** produce current candidate/watchlist decisions from the latest *available* validated snapshot (not necessarily today's incomplete data), plus optional human-entered positions and review/exit triggers. User decides and executes trades. No automatic brokerage connectivity.

At every checkpoint, remove redundant components instead of adding parallel ones. Deliver user-visible decision cases, not only green CI indicators.

## Hard finish criteria and prioritization

The mainline is not done until a user can inspect one real, provenance-bound security Decision Case, reproduce its inputs and logic, and distinguish evidence-backed eligibility from insufficient evidence. A successful monitoring run is **not** mainline completion.

Any proposed engineering task must answer:
1. Which Decision Case field or binding requirement is blocked?
2. Is there an existing component to reuse?
3. Can the blocker be deleted, avoided, or absorbed, instead of creating another service?
4. What one executable test proves it is resolved?

If none of (1)–(4) yields a concrete mainline benefit or frozen-evidence integrity need, **defer**.

## Minimal necessary defensive programming (active engineering rule)

These rules govern new and changed code; they do not amend frozen research contracts or justify blanket removal of existing protections.

1. **Validate once per trust boundary.** Validate incoming data at the boundary that owns its contract. Do not repeatedly check an invariant inside downstream pure logic when the validated value has not changed. Validate again only after a new external input, a transformation that can invalidate the invariant, or a distinct high-consequence boundary.
2. **Do not stack no-op checks or exception wrappers.** Reject duplicate null checks and broad `try/except` chains that merely log-and-rethrow, silently return `None`, or disguise the original failure. Catch exceptions only to perform a defined recovery, translate an error at a genuine boundary, add necessary diagnosis, or guarantee cleanup.
3. **Prefer local, readable code to gratuitous abstractions.** Keep one-off simple logic inline. Extract a function when it materially clarifies a complex responsibility, isolates side effects, enables meaningful tests, or removes substantive duplication. Call count alone is not the criterion.
4. **Require approval for speculative low-impact defenses.** Before adding complicated handling for an unobserved, low-impact edge case, explain the concrete failure mode, expected impact, implementation and maintenance cost, and simpler alternative. Do not quietly add the mechanism. This approval requirement does **not** waive non-negotiable protections for point-in-time leakage, sample identity/integrity, frozen rules, outcome blindness, or trading-risk discipline.
5. **Make new complexity earn its place.** New locks, retries, state machines, compatibility shims, validation gates, and recovery frameworks must name a credible failure mode, the boundary responsible for it, and why a simpler approach is insufficient. Prefer delete, avoid, reuse, or local handling before adding infrastructure.

**Review standard:** classify each proposed removal as redundant, necessary, or unverified; do not remove unverified guards. Tests should focus on observable behavior and scientific invariants rather than counting checks, catches, or lines of code. Do not alter archived/frozen historical modules merely to enforce style.

## Protected boundaries

- No revision of frozen research thresholds, sample definitions, sample windows, or unblinding.
- No Fold3/Fold4 read and no V2.8.13 authorization assertion.
- No rerunning failed controlled observations just to demonstrate progress.
- No automatic trade or fabricated historical outcome.
- Operations failures remain operational unless they threaten scientific integrity under the frozen governance kernel.

This is a **new operational product direction**, not a retroactive amendment to V2.9 scientific governance. It is deliberately one document rather than another stack of gates.

## V3.1 zero-wait evidence boundary — 2026-11-10

**Current operational research verdict:** **NO VERIFIED ALPHA / NO BUY.** The source-bound candidate-to-risk loop is functional (`scripts/v31_unified_eight_decision_gate.py`), but a working Decision Case and an attractive issuer are not evidence of repeatable predictive excess return. Do not call an unpromoted research candidate an executable recommendation.

**Do not restart completed or invalid experiments:**

- The 2025 and 2026 retrospective growth+ROE comparisons were not promoted: `research/v29_2025_growth_quality_nonpromotion/NONPROMOTION_VERDICT.json` and `research/v31_2026_cross_year_growth_roe/RESULT.json`.
- The 2023/24 absolute-low-volatility one-shot did **not** satisfy its predeclared year-by-year and month-share criteria: `research/v31_2023_2024_lowvol_one_shot/RESULT.json`; no threshold or factor-sign reversal.
- The separately preregistered 2023/24 **long-only 20-session short-term reversal** one-shot reusing the already-observed frozen daily archive also failed (20/20 valid months, 2024 mean below zero, 10/20 positive months): `research/v31_2023_2024_short_reversal_one_shot/RESULT.json`. Do not tune, reverse, or relabel that hindsight source as pristine untouched OOS.
- The separate historical E-layer setup discovery selected **no** candidate after three precommitted fold evaluations: `evidence/V2.8.8_SETUP_SHAPE_DISCOVERY_FINAL_RECEIPT.json`. Do not relabel fold-wise IC as live/realizable net alpha.
- Historic FY2022/23 issuer metadata: 245/256 original-announcement/vendor dates match but **251/256** vendor finance records were updated after the original year; **only 15/24** original-report development observations currently have all four figures. Official metadata match does not certify historical financial **values**. Evidence: `research/V2.9_2023_2024_256_SOURCE_LINEAGE_RECONCILIATION.json`, `research/V2.9_ORIGINAL_24_SOURCE_ONLY_DEVELOPMENT_FRAME_20261101.md`.
- Protected V2.8.12 prospective E shadow has **3 filings by 2 issuers**, versus a frozen minimum of 20 events, 12 issuers, 12 signal days, 6 distinct months and max 20% issuer share. Its gate **forbids opening price/return outcomes until readiness and a separate outcome contract**, even when the calendar horizon has passed. Do not consume it or Fold3/Fold4 as a shortcut: `evidence/V2.8.12_PROSPECTIVE_E_EVENT_SHADOW_ACCUMULATION_GATE.json` and `evidence/V2.8.12_CONTINUOUS_PROSPECTIVE_EPOCH_AMENDMENT_1.json`.

**Problem-elimination / minimal-source rule:** A contemporaneously generated (e.g. 2023-dated) PDF **hash receipt** is not a universal hard prerequisite for *exploratory* historical reconstruction; dated, issuer-verified original filings with originally published year-column values, correction/restatement chronology and conservative next-session timing can substantiate reconstruction, with its actual 2026 retrieval timestamp disclosed. However a retrospective 2026 vendor update date, announcement metadata, original PDF downloaded years later or a 15-name PDF subset alone **cannot** certify a full-year historical tradable return backtest or untouched OOS. Do not silently relax any frozen pre-outcome or scientific contract.


## External public-factor data admission — 2026-11-13

**Direct source-selection finding, not a new stock strategy.** Li, Liu, Liu & Wei, *Management Science* 70(8), 5066–5090 (2024), DOI `10.1287/mnsc.2023.4904`, replicate 469 A-share anomalies using mainboard breakpoints and value-weighted high-minus-low quintiles. Their university data page `https://www.gsm.pku.edu.cn/finvc/info/1028/1145.htm` says factor portfolio **monthly quintile return series available through 2023-12** and describes downloadable ZIP attachments. Jansen, Swinkels & Zhou (2021), DOI `10.1016/j.pacfin.2021.101607`, independently document A-share book-to-market and other anomaly returns and turnover/break-even costs. Published **long-short** return spreads and estimated break-even transaction costs **are not** our current account's long-only investable net alpha; neither paper supplies source-proven 2024–2026 per-security original-vintage signals and broker fills.

**Actual source retrieval and correction (2026-11-13):**
- Initial GitHub Actions source probe `43388830357` failed PKU TLS chain validation; `43388968872` accessed only PKU HTML with certificate checks disabled and incorrectly reported no ZIP links because it searched for `.zip` in HTML `href` attributes. **Root cause:** PKU official attachment names end in `.zip` but actual URLs are `/system/_content/download.jsp?urltype=news.DownloadAttachUrl&owner=2010923538&wbfileid=<ID>`. Do not preserve the earlier “ZIP unavailable” inference.
- A corrected probe [run `43392412358`](https://github.com/Justalittlebittt/AI-Core-EVID/actions/runs/43392412358) successfully downloaded and opened **value/growth ZIP (2,662,587 bytes; 68 `.XLSX` members; SHA256 `2da098c6614cb258df56153a107eba8c01513304b0adf30539a3008f19df067b`; `wbfileid=14714960`)** and **momentum ZIP (1,703,221 bytes; 45 `.XLSX` members; SHA256 `2ed689c151597912f61e672b725655eed4ec87e983ecc8d72091445b4e9692f9`; `wbfileid=14714957`)**. The PKU TLS issuer chain **still failed verification** and was bypassed **only for read-only ZIP-structure inspection**. Downloaded bytes and hashes prove deterministic retrieval, not authenticated server provenance or complete contents/dated returns; **do not admit these ZIP-derived values to predictive scoring** without resolving source identity. PKU publisher says data through December 2023, not a contemporary 2026 validation panel.
- Separately [run `43392154480`](https://github.com/Justalittlebittt/AI-Core-EVID/actions/runs/43392154480) **downloaded with valid TLS** five actual original Tsinghua University XLSX files (size, liquidity, value, reversal, volatility). All five were valid XLSX ZIP containers with one worksheet, `Low / High / H-L` columns and ~238–239 rows including header. Source page: `https://xyfintech.pbcsf.tsinghua.edu.cn/info/1011/1112.htm`. Official downloadable `/PDF/` paths and SHA256: size `2019121606043758001.xlsx` `722fb95df227662e11587f647381d74a66f39bd64e18f91b26eb5872df0ed3e5`; liquidity `2019121606045881502.xlsx` `226cb0c911c065915ac4cf49126b43e781da9fba3229ad7821dfc17db9bae04f`; value `2019121606053449103.xlsx` `2b02d5f24d21c3bac704ebeda1f9cd401be76327138fb7a612dad902bbe2b6ed`; reversal `2019121606055920404.xlsx` `3fa911704df68682bf1ee5e0f70410878674d43db7db721f9e5e417d42bfe16a`; volatility `2019121606061872805.xlsx` `c72d9d2db5741b6fd39ba8d0b38ebb0b131c51b97a33986749bca93d41a10a1a`. These are verified public **historical strategy portfolio returns** originally posted in 2019, not 2024–2026 long-only executable alpha or security-level PIT selection.

**Decision:** `EXTERNAL_ACADEMIC_PRIOR_IDENTIFIED / RAW_DATA_NOT_ADMITTED / NO_VALIDATED_LONG_ONLY_ALPHA`. Do not add another turnover, BM, dividend or profitability factor, alter past research windows, or promote a strategy just because literature reports long-short premiums. Reuse the external portfolio library as a **methodological reference** only. A fresh experiment is justified solely if its already available original source supplies **specific security selection rules, trading-time observables, comparable long-only cost/economic benchmark and independent evidence not previously consumed**; otherwise the prior decision-first read-only watchlist remains operational with `NO BUY`. No new cron, market-data platform or PDF scrape is authorized by this audit.

**Independent 2024–2026 security-level data source elimination (2026-11-13):** Public `rootSunc/CNEquity` v0.23.0 (GitHub repo created 2026-06-28; updated 2026-11-06; observed 1,024 stars/114 forks, public issue #59 reporting peak-day announcement-index 100-page truncation) offers free market bars, issuer history and `cne repair financial-originals` supporting Q1/Q2/Q3/Q4. Source review: `src/cnequity/adapters/cninfo/financial_originals.py`, `src/cnequity/storage/repairs/financial_originals.py`, `tests/unit/test_financial_originals.py`, `docs/zh/datasets/{schema,query-guide,catalog}.md`. The parser explicitly accepts unambiguous original issuer financial statement values, keeps original announcement date and **actual modern observation time separately**; its own tests assert that 2026-retrospectively recovered 2016 figures are not `strict` historical observed data. Vendor `eastmoney_backfill` is openly marked `reconstructed` and can carry retrospectively revised values; **it does NOT fix SUE strict-PIT or independent net long-only validation by installing a package**. However dated archived original filings can remain useful for clearly labeled *historical reconstruction*, subject to chronology/coverage and closed-window checks in this mainline. The tool is a conditional **reuse**, not a new always-on dependency.

The public `noblechang/a-share-data` FREE_DATA_v0 release contains a claimed **2010-01-04–2026-09-24** all-A historical snapshot (5,559 securities including delistings; 14,496,343 daily bars) in a ~928 MB raw tar and ~1,001 MB DuckDB (published 2026-09-25). GitHub release metadata showed 1,603 raw-archive and 3,483 DuckDB download **events**, not verified unique users. Repo had 1 star / 0 forks and no independently verified sample-integrity test in this review; release assets were **not downloaded nor source-hash independently checked**. Because the user already has PIT constituent machinery and historical daily-bar evidence, importing ~2 GB of retrospectively assembled data **without a concrete non-duplicated, externally justified stock-selection hypothesis is not a mainline advance**. `Quantactix/ChinaAShareEquityCharacteristics` has calculation code but explicitly omits raw CSMAR datasets, so the code alone is not a free security-level input supply.

**Original-PDF parser reality check, one-time (2026-11-13):** GitHub Actions [run `43396293006`](https://github.com/Justalittlebittt/AI-Core-EVID/actions/runs/43396293006) installed `cnequity==0.23.0` only in a temporary runner, imported upstream `parse_report_pdf(..., quarter=3)` and read two previously independently SHA256-matched official 2023Q3 issuer PDFs, with no prices, strategy scores or new full-market imports. `600519.SH` original PDF `cd3dfa7c07f692a2173639acd08e2153ba80a4e9070a5e189fcf16831050a7d3`: **19 identifiable current-period consolidated fields** including revenue, operating profit, total profit and operating-cashflow; `net_profit` **missing**. `300408.SZ` original PDF `4c5e462c89cd34958dd7c24b28ce98d922eb1b4f0b922dbc205337d3caa2f9ae`: parser explicitly raised `ValueError: periodic report has no unambiguous supported consolidated figures`, so **zero admitted fields**. Hence **1/2 report-level partial recovery, 0/2 net-profit usable**. This is a *small falsification of assumed out-of-box full coverage*, not an all-market error-rate estimate. The CI step deliberately reported per-PDF errors without making workflow failure mean stock-data missing. In addition, any recovered financials are 2026 observations of historical originals rather than contemporaneous strict PIT evidence. **Do not deploy this data lake or reopen the SUE3 branch on this parser evidence.**

**Net decision `NO_NEW_DATA_PLATFORM / NO_NEW_FACTOR_WITHOUT_INDEPENDENT_PRIOR / NO BUY`:** retain original disclosure auto-parser as a potential future replacement for manual quarterly extraction, but **do not activate or bulk-run** it for this closed SUE branch absent an independent research hypothesis and guaranteed analysis denominators. Source and import feasibility are different from demonstrated strategy edge. **No 2026 frozen prospective labels or price outcomes were read in this review.**

## Independent exchange-date factor snapshots — 2026-11-13

**New materially distinct source:** [TradSig public dataset](https://www.tradsig.sh.cn/data/) claims per-trading-day, non-backfilled full-market factor-snapshot Parquet from 2026-08-24, 53 trading sessions through 2026-11-12, under personal/non-commercial research permission and restrictions against bulk replication. Unlike a 2026 reconstruction of 2023 vendor finance, a snapshot actually *recording its own 2026 trade-date production* can supply a separately labelled source-vintage candidate, but self-reported `generated_at` is **not a trusted independent archived-time receipt**. Avoid treating this as authenticated immutable historical evidence or as stock-level outcomes.

**Two-file read-only reality check** in [GitHub Actions #43397326927](https://github.com/Justalittlebittt/AI-Core-EVID/actions/runs/43397326927), with HTTPS certificate validation and actual Parquet parsing (not merely a README claim; no price outcomes or frozen forward cohort accessed):
- `https://www.tradsig.sh.cn/downloads/factors/20260902.parquet`, SHA256 `8436ffd0176ca3f63fb336b13d51ac476b9623407a5897d45f9f6141b8fbd8af`, **5,547 unique securities / 5,547 rows**, 200 marked ST, one `trade_date=2026-09-02`, one data-version value, one self-recorded `generated_at=2026-09-02T10:50:08Z` (18:50 Beijing).
- `https://www.tradsig.sh.cn/downloads/factors/20261015.parquet`, SHA256 `2981b93dd051f1393deac29e59f37b1a6c280fbb3ec36c3eb898144d5ee8d0be`, **5,565 unique securities / 5,565 rows**, 198 marked ST, one `trade_date=2026-10-15`, one data-version value, one self-recorded `generated_at=2026-10-15T09:05:57Z` (17:05 Beijing). Both have per-stock `symbol`, `close`, `circ_mv`, `is_st`, industry, and 13 factor raw exposure/percentile groups; **the returned history was not automatically scored**.

**Decision:** `GO_TWO_DATED_SOURCE_SAMPLES / NO_GO_CURRENT_VALIDATED_ALPHA / NOT_AUTHORIZED`. The 53-session public history is too short to establish a stable 20-session hold strategy across independent regimes; its potential overlapping post-signal labels are not additional independent years or regimes. Data provider's pre-2026-08-24 retrospective walk-forward IC is not independently verified executable post-cost long-only return. Do not buy, tune new factors on the already-seen 2023/24 panel, run a 53-day parameter search, or bulk mirror the third-party dataset. Keep the source as an optional **small, time-labelled diagnostic** that may be compared against existing decision input contracts, not a mandate for a new crawler or another alpha research branch.


## 2026-11-13 external real-fill and forward-seed elimination

**Actual trade-ledger cross-check (not independently broker-authenticated):** Public `quantjuzi/reversal` CSV `结果/实盘成交明细.csv` (blob `2679b8d7bf788006886cdf31061f1848423a2fcb`) was parsed directly: 1,365 transactions, 716 buys / 649 sells, 339 stocks, 2025-10-13–2026-09-30; buys CNY 17,433,152.79, sells 17,467,443.88, commissions 9,216.89, stamp 8,740.86, transfer 86.73, **total explicit fees 18,044.48**, or **10.34bp per average one-side traded notional**. Original broker PDF and cash transfers are private; claimed +66,886.58 total P/L is not independently authenticated. The author explicitly mixes partly discretionary reversal, trend, consecutive-limit-up, IPO and other trades, so actual activity is **not** proof of a directly copyable algorithmic signal. Source: `https://github.com/quantjuzi/reversal`.

**Available forward-published seeds are too sparse for our growth-trend hypothesis:** `nengzechen/quant` commits daily `data/seed_pool_YYYYMMDD.json`. Source-only inspection of 21 distinct Oct-12 through Nov-10 2026 files found 1,990 seed rows, but just **24 `StrongTrend` entries over 5 dates** (Oct-16:9, Oct-21:2, Oct-26:1, Nov-04:5, Nov-05:7). Six dated files were additionally verified against Git commit timestamps, published **intraday**, not before that same day's open. Seeds are not broker-fill instructions; the narrow trend subset has no meaningful independent time-series validity support. No price outcomes were opened. Source: `https://github.com/nengzechen/quant`.

**Predeclared 30bp cost assumption can understate some one-lot trades:** Real 2026 brokerage fee schedules (e.g. `https://www.shgsec.com/main/a/20260814/20948.shtml` and `https://www.xcsc.com/main/a/20260730/1023018024.shtml`) show a possible **CNY 5 minimum commission per side**, 0.05% stamp on sales, and 0.001% transfer fee per side. Under that conditional schedule, a buy-then-sell at unchanged notional `N` incurs **at least `CNY 10 + 0.00052*N`** before spreads/slippage. At the *historical 2026-11-09* vendor one-lot prices archived in `research/v31_20261110_eight_real_closed_session/LATEST_AVAILABLE_VENDOR_CLOSE_20261109.json`, `SZSE:300199` (`N=2,355`) costs **47.66bp**, `SZSE:002552` (`N=3,231`) **36.15bp**, already above 30bp; the other six are **14.89–20.34bp** at that minimum-fee floor. Eight one-lot notionals total CNY 53,060, with CNY 107.59 explicit fees (~20.28bp basket weighted). **30bp requires at least CNY 4,032.26 order notional even with zero slippage** under this hypothetical fee schedule. Individual broker agreements may differ. The frozen 122-return protocol's 30bp rule is **unchanged**; this is a separate sensitivity calculation, not retrospective reranking/sizing or trade authorization.

**Disposition:** External real fills help calibrate cost *scale*, but do not independently validate any tradeable long-only growth-trend alpha. No new alpha evaluation was launched and no protected 2026 prospective labels were opened. `NO VERIFIED ALPHA / NO BUY`. Do not add a fee gate or broker-account workflow before evidence changes.

**Next-work triage:** No additional parameter grids, new factors, historical data-platform rebuild, manual quarterly PDF sweeps, scheduler tuning, or downstream buying components **without a specifically identified, presently available independent evidence source capable of changing the NO BUY decision**. Never wait for a future date to proceed with unrelated ready work; preserve ongoing frozen observations separately and never override their data-access rules. The research branch is **EVIDENCE_BLOCKED_AS_OF_2026_11_10**, not waiting on engineering. The stock research/watchlist entry and account discipline can remain usable as clearly labeled non-trading decision support; user account, stops and official execution cannot be invented.
