# AI Core EVID — Current State: V2.7.30

AI Core EVID is an A-share evidence/PIT research pipeline with fail-closed governance.

## Frozen current state

- Official Mother Pool: **5221 / 5221 — EXACT_PASS**
- Security → Issuer PIT Map: **5221 / 5221 — EXACT_PASS**
- Primary Filing Locator Inventory: **5221 / 5221 — EXACT_PASS**
- Selector ambiguity: **0**
- Evidence Materialization Contract: **VALIDATED_PASS**
- Historical 2026-09-17 prospective certification: **BLOCKED_FIRST_OBSERVED_AFTER_PIT**
- Certified V2 Universe: **BLOCKED**
- First60: **BLOCKED**
- S4/S5/S6: **BLOCKED**
- LIVE: **BLOCKED**

## Current evidence architecture

```text
SSE/SZSE Official Mother Pool
        ↓
Security → Issuer PIT Map
        ↓
CNInfo Unified Official Filing Catalog
        ↓
Primary Locator Inventory
        ↓
On-demand Evidence Materialization
        ↓
raw PDF bytes + SHA256
        ↓
content-addressed cache / reuse
```

The full-market inventory does **not** pre-download 5221 PDFs. PDF bytes are materialized only when a downstream Evidence Bundle actually consumes that security.

## Materialization contract

V2.7.30 validated four representative securities across SSE Main, STAR, SZSE Main and ChiNext.

- First pass: 4 official PDFs fetched and validated.
- Second identical pass: 4 cache hits, **0 network fetches**.
- Cache objects are keyed by SHA256 of raw PDF bytes.
- Locator identity, PIT date, PDF header and cache hash are fail-closed.
- Raw PDF bytes are not required to be committed into Git history.

The validated transport uses Playwright APIRequestContext without installing a browser binary.

## Workflow policy

Heavy capture/probe/materialization workflows are **manual-only** after validation. Normal pushes must not automatically launch expensive external-source jobs.

Workflow completion alone is never authorization. Downstream authorization must come from the corresponding frozen receipt / Final Record.

## Temporal boundary

The 2026-09-17 universe and filing inventory were reconstructed after that PIT date. They remain valid for diagnostic/backtest architecture verification, but must not be relabeled as evidence prospectively observed on 2026-09-17.

## Next stage

**V2.7.31 — Forward Evidence Epoch + Certified Universe Bootstrap**

The next stage establishes a real forward observation epoch so future evidence can be certified without historical backfill ambiguity.
