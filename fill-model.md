# The fill model

Simvex fills paper orders against the real market: real pairs, real quotes, real rugs. The model below is public,
versioned and deterministic. `GET /v1/fill-model` returns the same parameters with the version string
(`fm-2026.11.2`). Any change to a number here is a new version and an announcement.

> Paper trading result. Real fills may differ. Nothing here is a promise of profit.

## Parameters

| Parameter | Value | Where it applies |
|---|---|---|
| `quote_max_age_sec` | 3 s | rule 1 |
| `confirm_sec` | 1.2 s | rule 2 |
| `latency_penalty_bps` | 100 bps (1 %) | rule 5 |
| dex fee | bonding curve 125 bps; AMMs 25 to 30 bps (inside the quote) | rule 5 |
| Token-2022 transfer fee | the mint's `transferFeeConfig.newer_bps` | rule 5 |
| `tx_cost_sol` | 0.0001 SOL per attempt | rule 6 |
| `priority_fee_lamports` | your order's value, 0 to 50,000,000 | rule 6 |
| `min_trade_sol` | 0.01 SOL | rule 7 |
| rug while holding | price -90 % from entry, or liquidity <= 20 % of its recent peak | rule 8 |
| liquidity pulled before confirmation | liquidity <= 20 % of its recent peak, or no quote at all | rule 4 |

## Quotes

Every fill starts from a quote. Where it comes from is always in the response (`quote_source`):

- `curve`: tokens still on the bonding curve are priced exactly from the curve account (constant product on the
  virtual reserves). The curve fee is 1.25 % applied on top of the net SOL (`net = sol_in / 1.0125`), which was
  calibrated on 2026-11-05 against real aggregator quotes on six live curves (agreement within 1 bps). The curve's own price impact is computed locally.
- `aggregator`: graduated and AMM tokens are quoted by an external aggregator.
  Quotes are cached for 2 s per (mint, side, amount bucket; buckets are 19 % wide) and the whole server is capped at
  `QUOTE_RPS` calls per second (0.25, half of the measured keyless limit of 0.5 rps).
- `local_cpmm`: when the cap is closed, the aggregator fails or answers 429, the quote is a constant product on the
  latest snapshot (price and SOL-side liquidity from the data sources) with the dex fee. It is also the only source
  for a position marked `LIQ_PULLED` (rule 8).

Inside a replay session every quote is `curve` or `local_cpmm` on the recorded snapshot at the session clock.

## The eight rules

1. **Quote age.** At acceptance, a quote older than 3 s is fetched again (a curve token re-reads its account over
   RPC). If no quote can be had: `QUOTE_UNAVAILABLE`; if the fresh one is still older than 3 s: `QUOTE_STALE`.
   A replay quote is fresh arithmetic on the recorded snapshot, so its age is reported in `quote_age_ms`, not
   rejected. A live `local_cpmm` fallback (aggregator capped or down) may fill only on a snapshot at most 15 s old
   (`FILL_SNAPSHOT_MAX_AGE_SEC`); older is `QUOTE_STALE` at acceptance, and at confirmation the order fails
   `QUOTE_STALE` with principal and costs returned. Fills have their own aggregator budget, separate from the public
   quote endpoints.
   Before the quote the order must pass `MIN_TRADE` and `BALANCE_LOW` (cash >= amount + tx cost + priority fee).
   If the quote's price impact in bps is above your `slippage_bps`: `SLIPPAGE_HIGH`, nothing is reserved.
2. **Confirmation.** An accepted market order is `pending` for 1.2 s. Principal, tx cost and priority fee are
   reserved from cash (a sell reserves the tokens). At `t = min(confirm_ts, now)` the engine takes a **fresh quote at
   confirmation time** (the 2 s cache is bypassed) and never reads data after `t`. In a replay the market enforces
   this with a lookahead guard (`400 LOOKAHEAD`); live, a settle that runs more than 2 s late prices on the snapshot
   known at `t` instead of asking the aggregator for a later price.
3. **Slippage at confirmation.** Expected price = the accepted quote after penalties. If the confirmation price is
   worse by more than `slippage_bps`: `FILL_FAILED_SLIPPAGE`. The principal comes back; the tx cost and the priority
   fee stay charged (a failed transaction still paid its fees).
4. **Liquidity pulled.** If between acceptance and `t` a snapshot shows liquidity at or below 20 % of its recent
   peak, the pair vanished, or no quote exists at `t`: `FILL_FAILED_LIQ`. Principal, tx cost and priority fee all
   come back (the transaction never landed). Curve tokens have no LP to pull; their liquidity is the virtual SOL.
5. **Fill price.** Buy: `tokens = quote_out x (1 - 0.01) x (1 - transfer_fee)`. Sell: the transfer fee comes off
   the tokens first, then `sol = quote_out x (1 - 0.01)`. The dex fee is already inside the quote (curve 125 bps,
   AMM 25 to 30 bps). The fill row stores the realised price and the quote source.
6. **Costs.** `tx_cost_sol` (0.0001) plus your `priority_fee_lamports` are charged per attempt: on a fill and on a
   slippage failure. Both are returned only on a liquidity failure. A sell reserves them from cash at acceptance, as
   much as the cash covers; the rest comes off the proceeds of a fill, and a failed sell is charged only what was
   reserved, so cash never goes below 0. A `pct` buy of 100 % spends what is left after the costs.
7. **Minimum order.** 0.01 SOL. Buys by their SOL amount; sells by their SOL value at the latest price, except a
   100 % exit, which is always allowed so a dust position can be closed.
8. **Rug while holding.** On every snapshot, a position whose price fell 90 % from entry, whose liquidity is at or
   below 20 % of its peak, or whose pair reports liquidity pulled, is marked `liq_pulled` (decision `LIQ_PULLED`).
   From then on sells are priced only against the remaining liquidity (`local_cpmm` on the latest snapshot) and the
   slippage check is waived: you get what is left, which may be close to nothing.

## Order types

- `market`: rules 1 to 7 at once.
- `limit`: `open` until the snapshot price crosses `limit_price_sol` (buy at or below, sell at or above), then it
  becomes a market execution at that moment with the order's `slippage_bps`. Nothing is reserved while open; an
  execution can still fail `BALANCE_LOW`. `expires_in_sec` turns it `expired`. Only open orders can be cancelled.
- `tp_sl`: attaches to your open position in `mint`; a sell of `amount` (default 100 %) when `tp_pct` (price change
  from entry), `sl_pct` (drop from entry) or `trail_pct` (drop from the peak after a new high) hits, or when the pair's
  liquidity is pulled (`EXIT_LIQ_PULLED`). Cancelled when the position closes.

## Amounts

`amount_unit`: `sol` (SOL in for a buy; SOL value for a sell), `token` (tokens; for a buy converted at the latest
price), `pct` (buy: percent of cash; sell: percent of the position).

## What the engine writes

- `orders`: `status` in `pending | open | filled | failed | rejected | cancelled | expired`, `code`, `expected`
  (the accepted quote and reserved costs), `result` (what happened at confirmation).
- `fills`: SOL, tokens, realised price, tx cost, priority fee, quote source.
- `positions`: tokens, cost basis, entry and peak price, `liq_pulled`.
- `decisions`: every accept, skip, trigger, fail, fill and mark with a reason code and an English
  sentence. `GET /v1/bots/{bot}/decisions`.
- `equity`: one point per minute for every bot with a position or an order in the last 24 h.

## Idempotency and fairness

Same `client_order_id` on the same bot and book returns the first order unchanged: one fill, same response, also
when the two requests arrive at the same time. Market executions on the same bot, book and mint are accepted one at a
time, and a sell takes its tokens with a compare-and-set after the quote, so two exits (two requests, or a request and
a `tp_sl` trigger) can never sell the same tokens twice: the second gets `POSITION_LOW`.
The free plan's 30 s data delay applies to query endpoints, the quotes included (`/v1/quote`, the compat quote, MCP
`get_quote`: priced on the snapshot of 30 s ago); fills use the same real-time data for every plan, and a free
order's answer leaves the live accepted quote out of `expected`.

## Reason codes

`ORDER_ACCEPTED`, `ORDER_OPEN`, `FILL_OK`, `FILL_FAILED_SLIPPAGE`, `FILL_FAILED_LIQ`, `QUOTE_UNAVAILABLE`,
`QUOTE_STALE`, `SLIPPAGE_HIGH`, `BALANCE_LOW`, `POSITION_LOW`, `MIN_TRADE`, `RUG_BLOCKED`, `LIQ_PULLED`,
`LIMIT_TRIGGERED`, `TP_HIT`, `SL_HIT`, `TRAIL_HIT`, `EXIT_LIQ_PULLED`, `ORDER_CANCELLED`, `ORDER_EXPIRED`,
`NOT_TRACKED`, plus the rug-check codes (`MINT_AUTH_ACTIVE`, `TOP10_CONCENTRATION`, `LIQ_TOO_LOW`, ...).
