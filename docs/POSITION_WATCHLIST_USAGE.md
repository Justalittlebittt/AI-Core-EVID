# Repeatable private position watchlist

This is a **read-only input/output CLI**, not a brokerage connector, scheduled watcher, live quote service, or recommendation to hold. It reuses `scripts/v29_position_exit_review.py` and the frozen V2.9 discipline engine.

Keep real positions and prices in **local private files, not the public GitHub repo**. Both JSON inputs are arrays. Required position fields are `security_id`, `quantity`, `entry_price`, `stop_price`, `take_profit_price`, `position_fraction`, `position_limit`, `risk_budget_used`, `risk_budget_limit`, `invalidation_triggered`. Prices are a separate supplied snapshot with `security_id`, `as_of` (ISO8601 with offset), `close`, `source` (`USER_SUPPLIED` or `VERIFIED_IMPORT`). `VERIFIED_IMPORT` is a label from the supplying process, **not a fact the watchlist verifies**.

Run:

```bash
python scripts/v29_position_watchlist.py --positions /private/positions.json --quotes /private/quotes.json --at '2026-10-26T15:30:00+08:00' --max-quote-age-hours 72
```

The `--at` timestamp is caller-supplied, not system time; no automatic current-time checks or fetches occur. A missing/stale quote returns unknown price-based triggers, not an invented safe status. Independent invalidation remains an exit trigger. No stop/target revision is accepted through this watchlist. `NO_PRECOMMITTED_EXIT_TRIGGER` means only that the **EXIT** action is permitted in the V2.9 engine; it is **not** evidence that holding or buying is recommended.

This MVP does not yet verify provider provenance, exchange trading calendar, executable fills, trading halts, T+1 availability, automatic quotes, or historical position change persistence. Treat market-source trust and trading availability as separate product work. Do not commit a personal positions file to this public repository.
