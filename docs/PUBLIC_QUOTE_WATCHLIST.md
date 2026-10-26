# Public quote adapter (optional, read-only)

`scripts/v29_public_quote_watchlist.py` can retrieve public A-share quotes for an **existing private positions JSON** and feed them into the already validated `v29_position_watchlist` / `v29_position_exit_review` / V2.9 discipline engine. No accounts, positions, or orders are sent to a broker. Only listed stock symbols are queried from a third-party quote endpoint.

Example (use local/private files; never put real positions into this public repo):

```bash
python scripts/v29_public_quote_watchlist.py \
  --positions /private/positions.json \
  --at '2026-10-26T14:30:00+08:00' \
  --expected-session 2026-10-26 \
  --max-quote-age-hours 1
```

The *user supplies* both the evaluation instant and the **expected known A-share trading session**; the program does not guess market holidays. A stale, future, previous-session or missing quote produces `MISSING`/`STALE` and does **not** clear a stop trigger. Independent precommitted invalidation remains binding without prices.

**Source:** unofficial and undocumented Tencent Finance `https://qt.gtimg.cn/q=...`, GBK tilde-separated response, format as publicly described. Field positions and access can change; parsers must fail closed. `VERIFIED_IMPORT` is a transport label, **not independent official market-data certification**. The displayed `close` value is the provider's most recent indicated price, *not necessarily a completed-session close, executable sale price, or tradeable market*. Neither trading suspension nor T+1 shares-available-for-sale are established. Quotes are **not** point-in-time research evidence, and must never be imported into frozen E-layer research.

Provider smoke inside existing decision CI is deliberately **non-gating**: a provider outage must not fail offline decision correctness tests. Distinguish offline PASS from public provider status; if real provider cannot be read or validated, state that explicitly. No background scheduled surveillance or alerts are created.
