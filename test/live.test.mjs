// Against a running server: SIMVEX_BASE_URL and SIMVEX_API_KEY (a trainee-plan key for the WebSocket test).
// `python scripts/run_examples.py` starts a local server, issues the key and runs this suite.
import assert from "node:assert/strict";
import { test } from "node:test";

import { Client, NotFound, OrderRejected, SimvexError, Unauthorized } from "../dist/index.js";

const BASE = process.env.SIMVEX_BASE_URL;
const KEY = process.env.SIMVEX_API_KEY;
const skip = !BASE || !KEY ? "set SIMVEX_BASE_URL and SIMVEX_API_KEY (scripts/run_examples.py does)" : false;
const MINT = "DEBYyudC9EEhLN2Q8bibqczvJWKnWhBV71V7zMPgpump";

test("ladder, me, bots", { skip }, async () => {
  const c = new Client();
  const lad = await c.ladder();
  assert.equal(typeof lad.open_count, "number");
  const me = await c.me();
  assert.ok(me.key.last4 && me.disclaimer);
  assert.ok(c.rate.limit > 0 && c.rate.plan);
  const { bots } = await c.bots();
  assert.ok(bots.some((b) => b.is_default));
});

test("market data and typed order errors", { skip }, async () => {
  const c = new Client();
  const t = await c.tokensNew({ limit: 3 });
  assert.ok(Array.isArray(t.tokens) && "data_delay_sec" in t);
  try {
    const o = await c.placeOrder({ mint: MINT, side: "buy", amount: 0.1 });
    const done = await c.waitForOrder(o.order_id);
    assert.notEqual(done.status, "pending");
  } catch (e) {
    assert.ok(e instanceof OrderRejected || e instanceof NotFound, String(e));
    assert.ok(e.code && e.status >= 400);
  }
  await assert.rejects(c.positions({ bot: "no-such-bot" }), (e) => e instanceof NotFound && e.code === "NOT_FOUND");
});

test("wrong key is Unauthorized", { skip }, async () => {
  const c = new Client({ apiKey: "dr_" + "z".repeat(43) });
  await assert.rejects(c.me(), (e) => e instanceof Unauthorized && e.code === "UNAUTHORIZED");
});

test("websocket: auth first message and subscribe on the real server", { skip }, async () => {
  const c = new Client();
  const s = c.stream(["orders", "tokens.new"]);
  try {
    await s.open();
  } catch (e) {
    // a free key cannot open the WebSocket; that must come back typed
    assert.ok(e instanceof SimvexError && ["PLAN_LIMIT", "NOT_YET"].includes(e.code), String(e));
    return;
  }
  assert.equal(s.authInfo.ok, true);
  assert.equal(typeof s.lastSeq, "number");
  assert.ok(s.streamId);
  await s.close();
});
