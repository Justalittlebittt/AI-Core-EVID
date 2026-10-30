# V2.9 A-share growth candidates: real financial-data capture (research only)

This is the first real-source candidate discovery input for the Decision-first mainline, not a new predictor, strategy or monitoring platform. It captures one quarter's public Eastmoney financial report, keeps the exact raw paginated responses locally, then lists issuers with positive reported revenue, profit and two corresponding YoY growth rates. All candidates are **RESEARCH_CANDIDATE_ONLY / NOT_AUTHORIZED** for BUY/ADD.

## Local run

Use a period that has actually ended and been publicly reported, such as 2026-09-30:

    python scripts/v29_growth_candidate_snapshot.py \
      --report-date 2026-09-30 \
      --raw-dir /private/growth-pages-20261030 \
      --output /private/growth-candidates-20261030.json

Provider: publicly reachable, unofficial Eastmoney data center, report RPT_LICO_FN_CPD. Availability and column stability are not guaranteed; offline CI does not test live connectivity. The tool fails on incomplete/unstable pagination and cannot silently overwrite a previous capture. Its report-date filter is fiscal period, **not** the date investors learned the data.

A candidate includes reported revenue, attributable net profit, growth percentages, fiscal date, vendor notice date, ROE and cash-flow-per-share review flags. Sorting is by reported revenue growth for human review, *not* forecast return. Companies without vendor notice date or numeric fields are excluded and counted; future notices abort the capture.

**Limitations (important):**
- The source is an aggregated third-party reporting endpoint. Report revisions, historical backfills, completeness, public release time, corporate identities and official filing sources are NOT independently authenticated.
- The exact captured bytes and hashes fix the collected vintage; later requerying the vendor for an older reporting period must never be called a true historical PIT replay. Verify against original exchange filings before making research claims.
- Values may represent year-to-date periods and comparability may change; positive reported YoY growth does not prove sustainable organic growth. Negative/unknown CFO or ROE is flagged, not filled with fictional values. Valuation, receivables, one-offs, listing status and liquidity remain unassessed.
- The screening rule uses natural sign comparisons only. It is NOT empirically promoted, has NO verified alpha, OOS result or trading authority.
- Do not import frozen V2.8.4/V2.8.12, Fold3/Fold4 or unpublished outcomes. Do not publish user holdings in this public repository.

## Next product step

Review provider availability, coverage, notice-date provenance and completeness on an actual new capture. Add independent filing verification and as-of market prices before claiming a point-in-time investable candidate pool. Predeclare a separate economic hypothesis, frozen observation protocol and tradable benchmark **before qualifying future outcomes**; reuse the existing V2.9 Validity and Discipline engines, not another framework.

Offline unit tests:

    python -m unittest discover -s scripts -p 'test_v29_growth_candidate_snapshot.py' -v


## Two-period financial research review

Use the existing public report capture to compare the 2026-09-30 and 2026-06-30 cumulative reporting periods in one real, captured-current-vintage run:

    python scripts/v29_growth_persistence_review.py \
      --latest-period 2026-09-30 \
      --prior-period 2026-06-30 \
      --notice-before 2026-10-30 \
      --raw-dir /private/finance-compare-20261030 \
      --output /private/finance-review-20261030.json \
      --queue-limit 20

The command saves **both** periods' raw pages and source snapshots, with no overwrite. Its full report preserves every latest-period research candidate; the small review queue is for manual review, grouped without any speculative alpha score:

- A: revenue, parent profit and both reported YoY rates positive in both period snapshots; no current/prior CFO or ROE flags, name mismatch, or lower cumulative parent-profit margin.
- B: the same two-period growth observation, but one or more of those review flags.
- C: growth positive at the latest period but the prior-period **positive candidate observation is absent**. This does not establish prior decline, only absence from an already-filtered table.

Within each tier, items are ordered by canonical security ID, not by return potential. Both reports are **year-to-date cumulative** accounting periods, so these comparisons are not statistically independent observations of quarterly growth. A negative/unknown cash-flow-per-share figure is a review flag, not an automatically valid exclusion of an industry/business model. Do not interpret a positive two-period signal as validated alpha or a present BUY.

Data availability caveats: the third-party provider may revise historical records, and a contemporaneous re-fetch of older reports is not true historical PIT as-of evidence. The two captures are bound to their *actual collection times*, not the original announcement release timestamps. Validate original exchange filings, quarter-level accounting changes, valuations and independently dated market conditions before any strategy validity work. This output must remain RESEARCH ONLY.

Offline regression:

    python -m unittest discover -s scripts -p 'test_v29_growth_persistence_review.py' -v

Live vendor diagnosis (2026-10-30): the API caps pagination at 500 rows even for larger page-size requests. During same-day Q3 publication, page-count metadata changed across requests and the collector correctly aborted. A shared *exclusive* notice-date cutoff (e.g. `2026-10-30`) excludes announcements dated on the still-publishing current day, reducing moving-page exposure; it does NOT independently certify true PIT availability or guarantee against source revisions. Missing/changed pagination still stops collection rather than releasing a partial candidate pool.


## Valuation and liquidity market context (no alpha rank)

After capturing a complete two-period financial review, attach unofficial *capture-time* market context to the **A** tier (two-period positive and without the existing accounting-review flags):

    python scripts/v29_growth_market_context.py \
      --review-json /private/finance-review-20261030.json \
      --raw-dir /private/finance-quote-batches-20261030 \
      --output /private/finance-market-context-20261030.json \
      --max-age-minutes 90 \
      --queue-limit 20

Quote source: free, undocumented Eastmoney push2 ulist.np/get JSON endpoint, captured in 16-security batches. Public, third-party, non-certified market observations only. Raw quote JSON and per-batch SHA256 hashes are locally persisted; stock IDs must match financial screening. Unmatched/duplicated symbols are rejected; missing/stale/future quotes are marked unknown.

Reported PE field f9 is explicitly labeled vendor ratio, with basis not independently certified: it is NOT assumed to be TTM or a justified valuation. f23 is labeled vendor PB; f6 is cumulative session-to-observation traded amount, not full-session liquidity. Field f124 is the provider Unix quote timestamp, not a broker fill or verified official close. Sector, price and market-cap context are also unverified observations.

Only the prior A-tier research pool is enriched. B/C candidates remain in the original financial report; they are not deemed uninvestable. Within A the output is sorted by canonical security ID, NOT expected return, risk-adjusted return or fair-value score. Every row retains NOT_AUTHORIZED for BUY/ADD. No trading, new monitoring pipeline, frozen threshold changes or Fold3/Fold4 access.

Offline tests:

    python -m unittest discover -s scripts -p 'test_v29_growth_market_context.py' -v

Completing a purchase-decision product still requires original filing reconciliation, correct historical PIT data-vintage semantics, appropriately comparable valuation metrics, balance-sheet and nonrecurring income quality, preregistered OOS net-of-cost evaluation, user risk inputs and V2.9 discipline review. A green ingestion result does not prove those research conditions.

Live batch-capability probe 2026-10-30: Eastmoney accepted requests of 2, 8, and 16 securities, while a 30-security request returned HTTP 502. Use the empirically supported 16-security maximum; any future vendor failure remains a transport failure, not inferred missing stock data.

A quote captured during a trading session is an intraday observation, not the official daily close; source field f6 reflects trading up to the capture time. The market-context report has no industry-relative valuation threshold, so a low or high observed PE never changes BUY eligibility. Missing quotes remain unknown rather than assumed untradeable.


## Raw-financial quality audit of the real A-tier (2026-10-30)

This audits the original source bytes already captured by GitHub Actions run 41010835022. Source artifact: https://github.com/Justalittlebittt/AI-Core-EVID/actions/runs/41010835022/artifacts/12957159001 (14-day retention). Fiscal periods 2026-06-30 and 2026-09-30, mutually exclusive notice cutoff 2026-10-30, both collected on 2026-10-30. The report confirms 310 prior A-tier observations and preserves their original identity; it does **not** promote 310 assets as high-quality or buy-eligible.

Observed source profile for those 310: 309/310 Q3 rows did not supply DEDUCT_BASIC_EPS, 0/310 H1 rows lacked that field; 84/310 had a lower Q3 cumulative reported gross margin versus H1, 6/310 had missing gross margin in at least one period; 6/310 had a stock name beginning ST or *ST; all 310 had positive stand-alone Q3 revenues and parent profit when computed as Q3 cumulative minus H1 cumulative. Outside A, the raw source also contained 2 latest- and 1 prior-period rows with UPDATE_DATE on the excluded 2026-10-30 date. These are not selected A-tier identities; the audit must not falsely block A for unrelated source rows.

The near-total Q3 deduct-EPS missingness prevents drawing a conclusion about nonrecurring earnings quality. A name-based ST check is **only a warning**, not official exchange risk-status verification. A lower cumulative gross margin is a descriptive change, not evidence of a forecast. Q3 YTD minus H1 YTD is a quarter amount only if the provider used mutually compatible cumulative accounting semantics, which still need filing-level validation. Existing A/B/C tiers remain unchanged; missing data never becomes a false PASS or BUY.

Reproduce from the extracted source artifact:

    python scripts/v29_growth_raw_quality_audit.py \
      --review-json /private/extracted/growth-cutoff-report.json \
      --raw-dir /private/extracted/growth-cutoff-raw \
      --output /private/growth-quality-audit-20261030.json

The input review stores the exact raw-page SHA256 hashes. The audit verifies each page hash and issuer organization identity before using the rows, records missing fields without imputation, and aborts only for identity and temporal conflicts relevant to the selected A-tier. This is source/data-quality work, not alpha research, policy threshold change, or live-trading authorization.

    python -m unittest discover -s scripts -p 'test_v29_growth_raw_quality_audit.py' -v
