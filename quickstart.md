# Quickstart

Simvex is a paper-trading API for Solana trading bots on the live market: real new pairs, real quotes, real rugs, and a public fill model. Your bot gets an API key, never a private key. Every result is paper trading and real fills may differ.

> **Never send a private key or seed phrase to Simvex.** It needs only your `dr_` API key and never signs a real transaction. Requests that look like they carry a wallet secret are refused with `400 SECRET_REJECTED` and not stored.

This page goes from no key to a first paper fill in curl, Python and TypeScript. For a coding agent, the same steps are in one file at [simvex.xyz/skill.md](https://simvex.xyz/skill.md).

## 1. Get a key

- Send `/key` to the Simvex Telegram bot. You get one free key per Telegram account. It is shown once: save it and delete the message.
- Or redeem an operator invite code:

```bash
curl -s -X POST https://simvex.xyz/v1/keys -H 'content-type: application/json' \
  -d '{"invite_code": "inv_..."}'
```

Put the key in the environment, not in code:

```bash
export SIMVEX_BASE_URL=https://simvex.xyz
export SIMVEX_API_KEY=dr_...
```

## 2. curl

```bash
H="Authorization: Bearer $SIMVEX_API_KEY"

# who am I, which plan, which bots
curl -s $SIMVEX_BASE_URL/v1/me -H "$H"

# newest pairs with a rug summary, then one token's full report
curl -s "$SIMVEX_BASE_URL/v1/tokens/new?limit=5" -H "$H"
curl -s "$SIMVEX_BASE_URL/v1/tokens/<MINT>" -H "$H"

# a paper quote: 0.1 SOL in
curl -s "$SIMVEX_BASE_URL/v1/quote?mint=<MINT>&side=buy&amount=0.1&slippageBps=300" -H "$H"

# a market buy on the default bot (10 paper SOL to start)
curl -s -X POST $SIMVEX_BASE_URL/v1/bots/default/orders -H "$H" -H 'content-type: application/json' \
  -d '{"mint": "<MINT>", "side": "buy", "amount": 0.1, "slippage_bps": 300, "client_order_id": "qs-1"}'

# the order after confirmation (wait holds the answer up to 10 s while it is pending)
curl -s "$SIMVEX_BASE_URL/v1/bots/default/orders/<ORDER_ID>?wait=5" -H "$H"
curl -s $SIMVEX_BASE_URL/v1/bots/default/positions -H "$H"
curl -s $SIMVEX_BASE_URL/v1/bots/default/fills -H "$H"
```

The order ends `filled` (see `result` and the fill) or `failed` with a `code` such as `FILL_FAILED_SLIPPAGE` (the price at confirmation moved past your slippage; principal returned, transaction cost charged) or `FILL_FAILED_LIQ` (liquidity was pulled before confirmation; principal returned). `GET /v1/bots/default/decisions` lists every fill, failure and skip with its reason.

## 3. Python

The Python client is [Simvex/simvex-python](https://github.com/Simvex/simvex-python) (MIT, depends only on `httpx`).

```bash
pip install "git+https://github.com/Simvex/simvex-python"   # add [ws] for the WebSocket stream
```

```python
from simvex_client import Client, OrderRejected

c = Client()  # SIMVEX_API_KEY and SIMVEX_BASE_URL from the environment

print(c.me()["plan"]["name"])
tokens = c.tokens_new(limit=5)["tokens"]
mint = tokens[0]["mint"]
print(c.quote(mint, "buy", 0.1))

try:
    order = c.place_order(mint=mint, side="buy", amount=0.1, slippage_bps=300)
    done = c.wait_for_order(order["order_id"])
    print(done["status"], done.get("code"))
except OrderRejected as e:          # QUOTE_UNAVAILABLE, BALANCE_LOW, MIN_TRADE, ...
    print("refused:", e.code, e.hint)

print(c.positions()["positions"])
print(c.fills(limit=5)["fills"])
```

The client paces itself on `X-RateLimit-Remaining`, retries `429` after `Retry-After` with jitter, retries network errors and `5xx` only when the request is idempotent (every order carries a generated `client_order_id`), and raises typed errors that carry the API `code`.

## 4. TypeScript

The TypeScript client is [Simvex/simvex-js](https://github.com/Simvex/simvex-js) (MIT, no runtime dependency, uses `fetch` and the global `WebSocket`).

```bash
npm install github:Simvex/simvex-js
```

```ts
import { Client, SimvexError } from "simvex-client";

const c = new Client(); // SIMVEX_API_KEY and SIMVEX_BASE_URL from process.env in Node

const { tokens } = await c.tokensNew({ limit: 5 });
const mint = tokens[0].mint;
try {
  const order = await c.placeOrder({ mint, side: "buy", amount: 0.1, slippage_bps: 300 });
  const done = await c.waitForOrder(order.order_id);
  console.log(done.status, done.code, done.disclaimer);
} catch (e) {
  if (e instanceof SimvexError) console.log("refused:", e.code, e.hint);
  else throw e;
}
```

## 5. Replay the past with the same code

Create a session over recorded data, then send `X-Replay-Session` with the same calls. The SDKs bind it for you:

```python
avail = c.replay_range()["available"]          # what is recorded: {"from", "to", ...}
rp = c.replay(start_ts=avail["from"], end_ts=avail["from"] + 3600)
bot = rp.client                                # every call carries X-Replay-Session
tokens = bot.tokens_new(limit=5)["tokens"]
bot.place_order(mint=tokens[0]["mint"], side="buy", amount=0.1)
rp.advance(60)                                 # move the session clock one minute
print(bot.positions())
```

Asking for data after the session clock answers `400 LOOKAHEAD`. Replay time is billed in market time; see [limits](limits.md).

## 6. Stream events

```python
import asyncio
from simvex_client import AsyncClient

async def main():
    async with AsyncClient() as c, c.stream(["orders", "fills", "tokens.new"]) as s:
        async for ev in s:
            print(ev["seq"], ev["channel"], ev["data"])

asyncio.run(main())
```

The WebSocket needs the trainee plan or higher. The stream authenticates with its first message, answers pings, reconnects with backoff and resumes from the last `seq`, so no frame from the last 5 minutes is lost.

## 7. Agents and the compat layer

- **MCP:** a coding agent can use the [MCP server](/docs/mcp) at `/mcp` with the same key.
- **Compat layer:** a bot written against the request formats of the quote and trade APIs listed in the [compat spec](compat-spec.md) runs here by changing only its base URLs to `/compat/quote/v1` and `/compat/trade`.

## 8. Before going live

A paper result is a test, not a forecast. Real fills differ (competing bots, congestion, failed transactions, priority fee auctions). Use a fresh wallet that holds only what you can lose, never paste a private key or seed phrase anywhere, keep the slippage and stop rules you tested, and start with the minimum size.

## Errors

Every error body is `{code, message_en, hint, disclaimer}`; branch on `code`.

| Code | HTTP | Meaning |
|---|---|---|
| `SECRET_REJECTED` | 400 | Looked like a private key or seed phrase. Refused and not stored |
| `UNAUTHORIZED` | 401 | Missing, wrong, rotated or revoked key |
| `PLAN_LIMIT` | 403 | Past a plan limit (bots, tracked mints, WebSocket) |
| `NOT_YET` | 403 | The feature opens later (`opens_at`) |
| `FUEL_REQUIRED` | 402 | Not enough fuel for replay or a claim check |
| `RATE_LIMITED` | 429 | Wait `Retry-After` seconds |
| `QUOTE_UNAVAILABLE`, `QUOTE_STALE`, `SLIPPAGE_HIGH` | 409 | No usable quote right now |
| `BALANCE_LOW`, `MAX_POSITIONS` | 409 | Not enough paper SOL, or too many positions |
| `MIN_TRADE` | 422 | Below 0.01 SOL |
| `FILL_FAILED_SLIPPAGE`, `FILL_FAILED_LIQ` | 409 | Did not fill at confirmation |
| `RUG_BLOCKED` | 409 | Blocked by the bot's `rug_block` setting |
| `LOOKAHEAD` | 400 | Replay asked for data after its clock |
| `NO_DATA` | 404 | No recorded data in that window |
| `NOT_FOUND`, `CONFLICT`, `INVALID_REQUEST` | 404, 409, 422 | Not found, state conflict, bad request |
