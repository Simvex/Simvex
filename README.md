# simvex-client (Python)

Python client for the Simvex paper-trading API for Solana trading bots. MIT licensed. Depends only on `httpx`; the WebSocket stream adds `websockets` through the `ws` extra.

> **Your bot needs an API key (`dr_...`), never a private key or seed phrase.** The client refuses any key that does not start with `dr_`. Every result is paper trading and real fills may differ.

## Install

```bash
pip install ./sdk/python            # from the repo
pip install "./sdk/python[ws]"      # with the WebSocket stream
```

## Use

```python
from simvex_client import Client, OrderRejected

c = Client()   # SIMVEX_API_KEY and SIMVEX_BASE_URL from the environment (default http://127.0.0.1:8410)

tokens = c.tokens_new(limit=10)["tokens"]
report = c.token(tokens[0]["mint"])                 # full rug report: rug_reports.loose / normal / strict
quote = c.quote(tokens[0]["mint"], "buy", 0.1)      # out_amount, price_impact_pct, quote_source, quote_age_ms

try:
    o = c.place_order(mint=tokens[0]["mint"], side="buy", amount=0.1, slippage_bps=300)
    done = c.wait_for_order(o["order_id"])          # server long poll; market orders confirm in about 1.2 s
    print(done["status"], done["code"])
except OrderRejected as e:
    print(e.code, e.hint)

c.place_order(mint=tokens[0]["mint"], side="sell", type="tp_sl", amount=100, amount_unit="pct",
              tp_pct=40, sl_pct=20, trail_pct=15)
print(c.positions(), c.fills(limit=10), c.decisions(limit=10))
```

Async, with the same methods:

```python
from simvex_client import AsyncClient

async with AsyncClient() as c:
    me = await c.me()
```

## What the client does for you

- **Rate limits.** Reads `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-Plan` and `X-Data-Delay-Sec` into `c.rate`. When the bucket is empty it waits for one token before the next call. A `429` is retried after `Retry-After` plus up to 25% random jitter (`RetryPolicy`, 3 retries by default).
- **Safe retries.** Network errors and `5xx` are retried with exponential backoff and jitter only for idempotent requests: `GET`, `PUT`, `DELETE`, and orders. Every `place_order` carries a `client_order_id` (generated when you give none), so a retried order returns the first one instead of placing a second.
- **Typed errors.** Every API error raises a `SimvexError` subclass with `.code`, `.status`, `.hint`, `.body` and `.retry_after`: `Unauthorized`, `NotYet` (`.opens_at`), `PlanLimit`, `RateLimited`, `FuelRequired`, `SecretRejected`, `NotFound` (also `NO_DATA`), `Lookahead`, `Conflict`, `InvalidRequest`, `OrderRejected` (quote, balance, size, fill failures, `RUG_BLOCKED`), `ServerError`, `NetworkError`.
- **Replay.** `c.replay(start_ts, end_ts, speed=0)` creates a session and returns a helper whose `.client` sends `X-Replay-Session` on every call; `.advance(sec)` moves the clock. `c.in_replay(session_id)` binds an existing session. Your bot code does not change.
- **WebSocket.** `c.stream(channels)` authenticates with the first message (never in the URL), answers pings, reconnects with backoff and jitter and sends `resume` from the last `seq`, dropping duplicates. A `resumed` frame with `complete: false` is always yielded so you can resync over REST.

```python
async with c.stream(["orders", "fills", "tokens.new", "prices:<MINT>"]) as s:
    async for ev in s:
        print(ev["seq"], ev["channel"], ev["data"])
```

## Endpoints

| Area | Methods |
|---|---|
| Meta | `health`, `ladder`, `plans`, `status`, `fill_model` |
| Keys and bots | `me`, `redeem_invite`, `bots`, `create_bot`, `bot`, `reset_bot`, `bot_settings`, `leaderboard_opt_in` |
| Market data | `tokens_new`, `token`, `snapshots`, `quote` |
| Orders | `place_order`, `order`, `orders`, `cancel_order`, `wait_for_order`, `positions`, `fills`, `equity`, `decisions` |
| Replay and claims | `replay_range`, `create_replay`, `replay`, `in_replay`, `replays`, `replay_session`, `advance_replay`, `finish_replay`, `check_claim`, `claim` |
| Board and arena | `board`, `leaderboard`, `bot_card` (PNG bytes), `arena`, `arena_season`, `arena_enter`, `arena_entries` |
| Compat layer | `compat_quote`, `compat_trade` (see the compat spec) |
| Anything else | `request(method, path, params=..., json=...)` with the same retries and errors |

## Tests

```bash
pytest sdk/python/tests            # unit tests, no server
pytest tests/test_m8_sdk.py        # against the Simvex app in process (repo checkout)
```

## Before going live

A paper result is a test, not a forecast. Use a fresh wallet that holds only what you can lose and never paste a private key or seed phrase anywhere. See the quickstart's "Before going live".

Paper trading result. Real fills may differ.
