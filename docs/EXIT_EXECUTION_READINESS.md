# Exit decision vs. sell-order readiness

**Exit trigger is not execution.** Reuse existing `v29_position_watchlist.py` output first. New `scripts/v29_exit_execution_readiness.py` consumes this output and an optional **private brokerage-position snapshot** with `security_id`, `as_of` (offset-aware), `sellable_quantity` (integer), and `trading_status` (`TRADING`, `SUSPENDED`, `UNKNOWN`).

```bash
python scripts/v29_position_watchlist.py --positions /private/positions.json --quotes /private/quotes.json --at '2026-10-26T15:30:00+08:00' > /private/watchlist-result.json
python scripts/v29_exit_execution_readiness.py --watchlist /private/watchlist-result.json --execution-context /private/execution-context.json
```

The second program **does not override** the first program's V2.9 `EXIT_REQUIRED` decision. Even on a suspended stock or zero broker-reported sellable shares (e.g. A-share T+1), the exit remains required while the execution flag reports blocked or unknown. The program will **not** derive T+1 availability from entry date, a generic quote, or total quantity: broker/account-specific sellable shares must be supplied. A full sellable quantity plus `TRADING` yields **order possibly submittable**, not proof of market availability, price limits, order acceptance or actual fill. A previous-day brokerage status is not usable for today's order readiness. Missing status yields UNKNOWN.

**Scope:** read-only; no automatic quote fetch here, no brokerage integration, no order creation, no secret/portfolio data committed to GitHub. This deliberately does not implement independent Chinese exchange trading-calendar and suspension verification or verify broker provenance. For reliable production execution, use account-specific broker sellable balances, authentic suspension/session status and verified trade confirmations rather than interpreting a stock quote as proof of tradability.
