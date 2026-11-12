// Unit tests with a mock fetch and a fake WebSocket. No server needed: npm test
import assert from "node:assert/strict";
import { test } from "node:test";

import { Client, NotFound, OrderRejected, PlanLimit, RateLimited, ServerError, SimvexError, Stream, wsUrl } from "../dist/index.js";

const KEY = "dr_" + "a".repeat(43);

function json(status, body, headers = {}) {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json", ...headers } });
}

function mk(handler, opts = {}) {
  const calls = [];
  const sleeps = [];
  const c = new Client({
    apiKey: KEY, baseUrl: "http://test",
    fetch: async (url, init) => { calls.push({ url: new URL(url), init }); return handler(calls.length, url, init); },
    sleep: async (ms) => { sleeps.push(ms); },
    ...opts,
  });
  return { c, calls, sleeps };
}

test("auth header, public endpoints without it, key never serialized", async () => {
  const { c, calls } = mk(() => json(200, { ok: true }));
  await c.me();
  assert.equal(calls[0].init.headers.Authorization, `Bearer ${KEY}`);
  assert.equal(calls[0].url.pathname, "/v1/me");
  await c.ladder();
  assert.equal(calls[1].init.headers.Authorization, undefined);
  assert.ok(!JSON.stringify(c).includes(KEY));
});

test("refuses a value that is not a dr_ key", () => {
  assert.throws(() => new Client({ apiKey: "4wBqpZM9xaSheZzJSMawUKKwhdpChKbZ5eu5ky4Vigw9", fetch: async () => json(200, {}) }));
});

test("429 waits Retry-After plus jitter, then succeeds", async () => {
  const { c, sleeps } = mk((n) => (n < 3 ? json(429, { code: "RATE_LIMITED", retry_after_sec: 2 }, { "Retry-After": "2" }) : json(200, { v: 1 })));
  assert.deepEqual(await c.me(), { v: 1 });
  assert.equal(sleeps.length, 2);
  for (const s of sleeps) assert.ok(s >= 2000 && s <= 2600, String(s));
});

test("429 past the retries raises RateLimited with code and retryAfter", async () => {
  const { c } = mk(() => json(429, { code: "RATE_LIMITED", hint: "wait" }, { "Retry-After": "3" }), { retry: { maxRetries: 1 } });
  await assert.rejects(c.me(), (e) => e instanceof RateLimited && e.code === "RATE_LIMITED" && e.retryAfter === 3 && e.hint === "wait");
});

test("5xx retried for GET, not for a POST without client_order_id", async () => {
  const n = { GET: 0, POST: 0 };
  const { c } = mk((_, __, init) => { n[init.method]++; return json(503, { code: "INTERNAL" }); }, { retry: { maxRetries: 2 } });
  await assert.rejects(c.me(), ServerError);
  await assert.rejects(c.createBot("b2"), ServerError);
  assert.deepEqual(n, { GET: 3, POST: 1 });
});

test("placeOrder generates client_order_id and is retried with the same id", async () => {
  const { c, calls } = mk((n) => (n === 1 ? json(502, {}) : json(201, { order_id: "o1", status: "pending" })));
  const o = await c.placeOrder({ mint: "M".repeat(32), side: "buy", amount: 0.1 });
  assert.equal(o.order_id, "o1");
  const a = JSON.parse(calls[0].init.body);
  const b = JSON.parse(calls[1].init.body);
  assert.ok(a.client_order_id.startsWith("sdk-"));
  assert.equal(a.client_order_id, b.client_order_id);
  assert.equal(a.type, "market");
  assert.equal(a.amount_unit, "sol");
});

test("network errors: retried for GET, then NETWORK", async () => {
  const { c, sleeps } = mk(() => { throw new TypeError("fetch failed"); }, { retry: { maxRetries: 1 } });
  await assert.rejects(c.me(), (e) => e instanceof SimvexError && e.code === "NETWORK");
  assert.equal(sleeps.length, 1);
});

test("paces when X-RateLimit-Remaining is 0", async () => {
  const { c, sleeps } = mk(() => json(200, {}, { "X-RateLimit-Limit": "30", "X-RateLimit-Remaining": "0", "X-Plan": "free", "X-Data-Delay-Sec": "30" }));
  await c.me();
  await c.me();
  assert.equal(c.rate.limit, 30);
  assert.equal(c.rate.plan, "free");
  assert.equal(c.rate.dataDelaySec, 30);
  assert.ok(sleeps[0] > 1500 && sleeps[0] <= 2000, String(sleeps[0]));
});

test("typed errors keep code, status, hint and body", async () => {
  for (const [status, code, Cls] of [[403, "PLAN_LIMIT", PlanLimit], [409, "FILL_FAILED_LIQ", OrderRejected], [404, "NO_DATA", NotFound]]) {
    const { c } = mk(() => json(status, { code, hint: "h", available: { from: 1 } }));
    await assert.rejects(c.me(), (e) => e instanceof Cls && e.code === code && e.status === status && e.hint === "h" && e.body.available.from === 1);
  }
});

test("replay helper binds X-Replay-Session on its client only", async () => {
  const { c, calls } = mk((_, url) => {
    const p = new URL(url).pathname;
    if (p === "/v1/replays") return json(201, { session_id: "rs_1", clock_ts: 100 });
    if (p.endsWith("/advance")) return json(200, { session_id: "rs_1", clock_ts: 160 });
    return json(200, { positions: [] });
  });
  const rp = await c.replay(100, 200);
  await rp.client.positions();
  assert.equal(calls[1].init.headers["X-Replay-Session"], "rs_1");
  await rp.advance(60);
  assert.equal(rp.clock, 160);
  assert.equal(calls[2].init.headers["X-Replay-Session"], undefined);
  await c.positions();
  assert.equal(calls[3].init.headers["X-Replay-Session"], undefined);
});

test("compat trade sends X-Dryrun-Bot", async () => {
  const { c, calls } = mk(() => json(200, {}));
  await c.compatTrade({ action: "buy", mint: "M".repeat(32), amount: 0.1, denominatedInSol: "true" }, { bot: "b1" });
  assert.equal(calls[0].init.headers["X-Dryrun-Bot"], "b1");
  assert.equal(calls[0].url.pathname, "/compat/trade/api/trade");
});

test("wsUrl", () => {
  assert.equal(wsUrl("https://api.example.test"), "wss://api.example.test/v1/ws");
  assert.equal(wsUrl("http://127.0.0.1:8410/"), "ws://127.0.0.1:8410/v1/ws");
});

// A scripted /v1/ws server per connection.
function fakeWsFactory(scripts) {
  const made = [];
  class FakeWs {
    constructor(url) {
      this.url = url;
      this.sent = [];
      this.script = scripts[made.length] ?? [];
      made.push(this);
      setTimeout(() => this.onopen?.(), 1);
    }
    emit(obj) { setTimeout(() => this.onmessage?.({ data: JSON.stringify(obj) }), 1); }
    send(text) {
      const m = JSON.parse(text);
      this.sent.push(m);
      if (m.op === "auth") this.emit({ op: "auth", ok: true, stream: "st1", seq: 5 });
      if (m.op === "subscribe") {
        this.emit({ op: "subscribed", channels: m.channels, seq: 5 });
        let d = 2;
        for (const step of this.script) {
          setTimeout(() => (step === "drop" ? this.onclose?.({ code: 1006 }) : this.onmessage?.({ data: JSON.stringify(step) })), d);
          d += 2;
        }
      }
      if (m.op === "resume") {
        let d = 2;
        for (const step of this.script) { setTimeout(() => this.onmessage?.({ data: JSON.stringify(step) }), d); d += 2; }
      }
    }
    close() {}
  }
  return { FakeWs, made };
}

test("stream: auth first, pong, reconnect with resume from last seq, duplicates dropped", async () => {
  const ev = (seq) => ({ op: "event", seq, channel: "orders", data: { n: seq } });
  const { FakeWs, made } = fakeWsFactory([[ev(6), { op: "ping", seq: 6 }, ev(7), "drop"], [ev(7), ev(8), { op: "resumed", complete: true }]]);
  const s = new Stream({ apiKey: KEY, baseUrl: "http://test", channels: ["orders"], WebSocket: FakeWs, maxReconnects: 3 });
  await s.open();
  const got = [];
  for await (const f of s) {
    got.push(f.seq);
    if (got.length === 3) break;
  }
  assert.deepEqual(got, [6, 7, 8]);
  assert.deepEqual(made[0].sent[0], { op: "auth", key: KEY });
  assert.equal(made[0].sent[1].op, "subscribe");
  assert.ok(made[0].sent.some((m) => m.op === "pong"));
  const resume = made[1].sent.find((m) => m.op === "resume");
  assert.equal(resume.since_seq, 7);
  assert.deepEqual(resume.channels, ["orders"]);
  assert.equal(resume.stream, "st1");
  assert.equal(s.reconnects, 1);
});

test("stream: unauthorized close is not retried", async () => {
  class BadWs {
    constructor() { setTimeout(() => this.onopen?.(), 1); }
    send() {
      setTimeout(() => this.onmessage?.({ data: JSON.stringify({ op: "error", code: "UNAUTHORIZED", message_en: "no" }) }), 1);
      setTimeout(() => this.onclose?.({ code: 4001 }), 2);
    }
    close() {}
  }
  const s = new Stream({ apiKey: KEY, baseUrl: "http://test", channels: ["orders"], WebSocket: BadWs });
  await assert.rejects(s.open(), (e) => e.code === "UNAUTHORIZED");
});
