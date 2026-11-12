# simvex-client (TypeScript)

TypeScript client for the Simvex paper-trading API for Solana trading bots. MIT licensed, ESM, with type definitions. **No runtime dependencies:** it uses the global `fetch` and `WebSocket` (Node 22 or later, and browsers).

> **Your bot needs an API key (`dr_...`), never a private key or seed phrase.** The client refuses any key that does not start with `dr_`. Every result is paper trading and real fills may differ.

## Build

```bash
cd sdk/typescript
npm install          # TypeScript, the only dev dependency
npm run build        # tsc -> dist/
npm run check        # tsc --noEmit
npm test             # build, then node --test (unit tests; live tests too when SIMVEX_BASE_URL and SIMVEX_API_KEY are set)
```

## Use

```ts
import { Client, OrderRejected } from "simvex-client";

const c = new Client(); // apiKey and baseUrl from SIMVEX_API_KEY and SIMVEX_BASE_URL in Node

const { tokens } = await c.tokensNew({ limit: 10 });
const mint = tokens[0].mint;
console.log(await c.quote(mint, "buy", 0.1));

try {
  const order = await c.placeOrder({ mint, side: "buy", amount: 0.1, slippage_bps: 300 });
  const done = await c.waitForOrder(order.order_id); // server long poll
  console.log(done.status, done.code);
} catch (e) {
  if (e instanceof OrderRejected) console.log(e.code, e.hint);
  else throw e;
}

await c.placeOrder({ mint, side: "sell", type: "tp_sl", amount: 100, amount_unit: "pct", tp_pct: 40, sl_pct: 20 });
console.log(await c.positions(), await c.fills({ limit: 10 }));
```

In a browser, pass `apiKey` and `baseUrl` explicitly, and keep the key out of public pages.

## Features

- **Rate limits:** `c.rate` holds the last `X-RateLimit-*`, `X-Plan` and `X-Data-Delay-Sec` values; an empty bucket waits for one token; `429` waits `Retry-After` plus jitter and retries (3 times by default, `retry: {maxRetries}`).
- **Safe retries:** network errors and `5xx` are retried with backoff and jitter only for `GET`, `PUT`, `DELETE` and orders; every order gets a generated `client_order_id`.
- **Typed errors:** `SimvexError` and subclasses (`Unauthorized`, `NotYet`, `PlanLimit`, `RateLimited`, `FuelRequired`, `SecretRejected`, `NotFound`, `Lookahead`, `Conflict`, `InvalidRequest`, `OrderRejected`, `ServerError`, `NetworkError`) with `code`, `status`, `hint`, `body`, `retryAfter`.
- **Replay:** `await c.replay(startTs, endTs)` returns `{ sessionId, client, advance(sec) }`; `client` sends `X-Replay-Session` on every call. `c.inReplay(id)` binds an existing session.
- **WebSocket:** `c.stream(channels)` authenticates with the first message, answers pings, reconnects with backoff and `resume`s from the last `seq`, dropping duplicates.

```ts
const s = c.stream(["orders", "fills", "tokens.new"]);
await s.open();
for await (const ev of s) console.log(ev.seq, ev.channel, ev.data);
```

## Methods

`health`, `ladder`, `plans`, `status`, `fillModel`, `me`, `redeemInvite`, `bots`, `createBot`, `bot`, `resetBot`, `botSettings`, `leaderboardOptIn`, `tokensNew`, `token`, `snapshots`, `quote`, `placeOrder`, `order`, `orders`, `cancelOrder`, `waitForOrder`, `positions`, `fills`, `equity`, `decisions`, `replayRange`, `createReplay`, `replay`, `inReplay`, `replays`, `replaySessionInfo`, `advanceReplay`, `finishReplay`, `checkClaim`, `claim`, `board`, `leaderboard`, `botCard`, `arena`, `arenaSeason`, `arenaEnter`, `arenaEntries`, `compatQuote`, `compatTrade`, `stream`, and `request(method, path, {query, json, headers})` for anything else.

Paper trading result. Real fills may differ.
