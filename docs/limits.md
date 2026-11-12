# Limits and plans

Every number on this page comes from the server's `plans.yaml`, which the server reads again when it changes. The live values are always at `GET /v1/plans`, and your own at `GET /v1/me`. Every result is paper trading and real fills may differ.

## Plans

<!-- plans:start -->
| Plan | Bots | Calls per minute | Market data delay | Tracked mints | WebSocket | Price channels | Replay hours per month | Leaderboard | Arena seed |
|---|---|---|---|---|---|---|---|---|---|
| free | 1 | 30 | 30 s | 5 | no | 0 | 0 | no | no |
| trainee | 3 | 120 | 0 | 20 | yes | 10 | 5 | no | no |
| pro | 10 | 600 | 0 | 100 | yes | 50 | 20 | yes | no |
| desk | 50 | 2,000 | 0 | 300 | yes, priority | 200 | 100 | yes | yes |
<!-- plans:end -->

- **Bots** are sub-accounts on one key. Each has its own paper book: 10 SOL to start, its own positions, fills and decisions. If a plan change leaves more bots than the plan allows, the extra bots become read-only.
- **Tracked mints** is how many tokens your key can ask the server to start tracking (`GET /v1/tokens/{mint}` on a token the collector does not follow yet answers `202`). Tokens the collector already follows do not count.
- **Price channels** is how many `prices:{mint}` WebSocket channels one key can hold, counted over all its open connections.
- **Leaderboard**: while the token integration is off, every plan can opt a bot in to the public leaderboard. When it is on, new entries need pro or desk; bots already listed stay for the season.
- Until ladder step 4 opens (see below), every key runs on the free limits, whatever plan it holds.

## Rate limits

Each key has one token bucket. Its size is the plan's calls per minute and it refills continuously (free: one call every 2 seconds, up to 30 in a burst).

Every response carries:

| Header | Meaning |
|---|---|
| `X-RateLimit-Limit` | Calls per minute on your plan |
| `X-RateLimit-Remaining` | Calls left in the bucket right now |
| `X-Plan` | The plan this request ran on |
| `X-Data-Delay-Sec` | Market data delay applied to read endpoints on your plan |
| `X-Replay-Clock` | Only inside a replay session: the session clock (unix seconds) |

Past the limit the server answers `429` with `Retry-After` (whole seconds) and `retry_after_sec` in the body. Wait that long and retry; the SDKs do this for you, with a little random jitter so many bots do not retry at the same instant. A refused call does nothing on the server, so retrying it is always safe.

What counts as a call: every REST request with a key, every WebSocket client message except `pong`, and every MCP tool call (a live `place_order` that waits for its fill counts two). Opening an MCP session and listing its tools do not count.

## Market data delay

The free plan sees market data 30 seconds late on the read endpoints: `GET /v1/tokens/new`, `GET /v1/tokens/{mint}`, `GET /v1/tokens/{mint}/snapshots` and the quotes (`GET /v1/quote`, the compat quote, MCP `get_quote`). An order's answer leaves the live accepted price out of `expected` on the free plan. Fills are different: **every order on every plan is filled on the same live data**, so a free bot is never filled at a worse moment than a paid one. Paid plans see the read endpoints without delay. Replay sessions have no delay: they run on their own past clock.

## Orders

| Rule | Value |
|---|---|
| Minimum order | 0.01 SOL (`MIN_TRADE` below it) |
| `slippage_bps` | 1 to 5,000 (default 300) |
| `priority_fee_lamports` | 0 to 50,000,000, charged as a cost on top of the transaction cost |
| `client_order_id` | up to 64 characters of `A-Z a-z 0-9 _ . : -`; a repeat returns the first order |
| `expires_in_sec` (limit orders) | 10 seconds to 7 days |
| Confirmation | about 1.2 s after acceptance, at a fresh quote |

The full fill rules (latency penalty, re-quote at confirmation, failed fills, fees, rugs while holding) are in the [fill model](fill-model.md) and at `GET /v1/fill-model`.

## Bots and resets

A bot can be reset to 10 paper SOL once every 24 hours (`POST /v1/bots/{bot}/reset`). A reset bot leaves the current season's leaderboard, because its record no longer runs from the start of the season. Leaderboard rows need at least 5 fills, a maximum drawdown of 50% or less and no reset in the period.

## Keys

- One free key per Telegram account, from `/key` in the Telegram bot. `/rotate` replaces it on the same account (bots and books stay) and the old key stops working at once. `/revoke` turns it off.
- Operator invite codes grant the plan written on the invite (`POST /v1/keys`).
- At most 3 new keys per network per 24 hours.
- The key is shown once. The server stores only a salted hash and the last 4 characters.
- **Never send a private key or seed phrase.** A request that looks like one is refused with `400 SECRET_REJECTED` and nothing in it is stored or logged.

## Replay and fuel

Replay sessions are billed in **market time**: the time that passes on the session clock, not the wall clock. A one-hour window advanced in 10 seconds uses one hour. Each plan has monthly replay hours (free has none); past them, replay uses fuel. Claim checks use fuel too.

<!-- fuel:start -->
| Item | Fuel (US cents) |
|---|---|
| Replay, per hour of market time past the plan's monthly hours | 50 |
| Claim check, per check | 20 |
<!-- fuel:end -->

Without enough fuel the server answers `402 FUEL_REQUIRED` with the amount needed, your balance and how to top up. Fuel comes from an operator grant; top-ups in the project token or USDC open only when the token integration is switched on. Replay `speed` is at most 60 times real time, and one `advance` call moves at most 6 hours. A window without recorded data answers `404 NO_DATA` with the range that exists.

## WebSocket

`/v1/ws` needs the trainee plan or higher and opens at ladder step 3. Authenticate with the first message `{"op":"auth","key":"dr_..."}` within 10 seconds; a key in the URL is refused. The server pings every 20 seconds and closes a connection that stays silent for 60 seconds. Every data frame has a `seq`; after a reconnect, `{"op":"resume","since_seq":N}` sends what you missed from the last 5 minutes (up to 20,000 frames per key), in order.

| Close code | Meaning | Reconnect? |
|---|---|---|
| 4001 | Unauthorized | No, fix the key |
| 4003 | Plan limit or not open yet | No |
| 4400 | Secret rejected | No |
| 4408 | Heartbeat or auth timeout | Yes |
| 4429 | Rate limited at auth | Yes, after a pause |
| 1009 | Message too big | Yes |
| 1013 | Too slow to keep up | Yes, then resume |

## Feature ladder

Every feature is built before launch and opened in five steps, so the first hours have a small surface. A call to a feature that is not open answers `403 NOT_YET` with `opens_at`. Live status: `GET /v1/ladder` and the [ladder page](/docs/ladder).

| Step | Opens | Features |
|---|---|---|
| 1 | launch (T) | API keys and bots, market data, orders and fills |
| 2 | T | SDKs, examples and docs, Telegram bot, operator console |
| 3 | T + 1 hour | WebSocket, leaderboard and share cards, public board |
| 4 | T + 2 hours | Plan upgrades and fuel, replay sessions, claim checks |
| 5 | T + 3 hours | Compatibility layer, bot arena season 1, MCP server and skill.md |

Before step 4 every key runs on the free limits. Leaderboard opt-ins are accepted from step 1 and shown from step 3, so the board starts with an hour of records.
