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
