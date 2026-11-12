import { fromResponse, NetworkError, SimvexError } from "./errors.js";
import type { Body, ClaimIn, Fill, Order, OrderIn, Quote, ReplaySession, TokensNew } from "./types.js";
import { Stream, type StreamOptions } from "./ws.js";

export const VERSION = "0.1.0";
export const DEFAULT_BASE_URL = "http://127.0.0.1:8410";
export const DISCLAIMER = "Paper trading result. Real fills may differ.";
const REPLAY_HEADER = "X-Replay-Session";
const IDEMPOTENT = new Set(["GET", "HEAD", "OPTIONS", "PUT", "DELETE"]);
const RETRY_STATUSES = new Set([500, 502, 503, 504]);

type Query = Record<string, string | number | boolean | null | undefined>;
type FetchLike = (input: string, init?: RequestInit) => Promise<Response>;

export interface RetryPolicy {
  /** Retries after the first try (default 3). 429 is always retried; 5xx and network errors only when idempotent. */
  maxRetries: number;
  backoffBaseMs: number;
  backoffMaxMs: number;
  /** Up to this fraction of random extra wait (default 0.25). */
  jitter: number;
  maxRetryAfterMs: number;
  /** Wait for one token before the next call when X-RateLimit-Remaining hits 0 (default true). */
  pace: boolean;
}

export const DEFAULT_RETRY: RetryPolicy = {
  maxRetries: 3, backoffBaseMs: 500, backoffMaxMs: 20_000, jitter: 0.25, maxRetryAfterMs: 120_000, pace: true,
};

export interface ClientOptions {
  /** dr_ key. Defaults to process.env.SIMVEX_API_KEY in Node. Never a wallet private key. */
  apiKey?: string;
  /** Defaults to process.env.SIMVEX_BASE_URL, then http://127.0.0.1:8410. */
  baseUrl?: string;
  retry?: Partial<RetryPolicy>;
  /** Bind every call to a replay session (sends X-Replay-Session). */
  replaySession?: string;
  headers?: Record<string, string>;
  timeoutMs?: number;
  /** Custom fetch (tests, proxies). Defaults to globalThis.fetch. */
  fetch?: FetchLike;
  /** Custom sleep (tests). */
  sleep?: (ms: number) => Promise<void>;
}

export interface RateInfo {
  limit?: number;
  remaining?: number;
  plan?: string;
  dataDelaySec?: number;
  replayClock?: number;
}

export interface RequestOptions {
  query?: Query;
  json?: unknown;
  headers?: Record<string, string>;
  auth?: boolean;
  raw?: boolean;
}

function env(name: string): string | undefined {
  const p = (globalThis as { process?: { env?: Record<string, string | undefined> } }).process;
  return p?.env?.[name];
}

function clean(q: Query): Query {
  const out: Query = {};
  for (const [k, v] of Object.entries(q)) if (v !== undefined && v !== null) out[k] = v;
  return out;
}

export function newClientOrderId(): string {
  const c = (globalThis as { crypto?: { randomUUID?: () => string } }).crypto;
  const id = c?.randomUUID ? c.randomUUID().replace(/-/g, "") : Math.random().toString(16).slice(2) + Date.now().toString(16);
  return "sdk-" + id.slice(0, 24);
}

const defaultSleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

/** Every REST endpoint, with rate-limit pacing, retries with jitter and typed errors. */
export class Client {
  readonly baseUrl: string;
  readonly replaySession: string | undefined;
  readonly rate: RateInfo = {};
  readonly #key: string | undefined;
  readonly #retry: RetryPolicy;
  readonly #headers: Record<string, string>;
  readonly #timeoutMs: number;
  readonly #fetch: FetchLike;
  readonly #sleep: (ms: number) => Promise<void>;
  #notBefore = 0;

  constructor(opts: ClientOptions = {}) {
    const key = (opts.apiKey ?? env("SIMVEX_API_KEY"))?.trim();
    if (key !== undefined && key !== "" && !key.startsWith("dr_")) {
      throw new Error("API keys start with 'dr_'. Never pass a wallet private key or seed phrase here.");
    }
    this.#key = key || undefined;
    this.baseUrl = (opts.baseUrl ?? env("SIMVEX_BASE_URL") ?? DEFAULT_BASE_URL).replace(/\/+$/, "");
    this.replaySession = opts.replaySession;
    this.#retry = { ...DEFAULT_RETRY, ...(opts.retry ?? {}) };
    this.#headers = { ...(opts.headers ?? {}) };
    this.#timeoutMs = opts.timeoutMs ?? 30_000;
    const f = opts.fetch ?? (globalThis.fetch as FetchLike | undefined);
    if (!f) throw new Error("No fetch available. Pass opts.fetch.");
    this.#fetch = f;
    this.#sleep = opts.sleep ?? defaultSleep;
  }

  /** The same client bound to a replay session: every call carries X-Replay-Session. */
  inReplay(sessionId: string): Client {
    return new Client({
      apiKey: this.#key, baseUrl: this.baseUrl, retry: this.#retry, replaySession: sessionId, headers: this.#headers,
      timeoutMs: this.#timeoutMs, fetch: this.#fetch, sleep: this.#sleep,
    });
  }

  toJSON(): object {
    return { baseUrl: this.baseUrl, replaySession: this.replaySession }; // never the key
  }

  #backoff(attempt: number): number {
    const d = Math.min(this.#retry.backoffMaxMs, this.#retry.backoffBaseMs * 2 ** attempt);
    return d * (1 + Math.random() * this.#retry.jitter);
  }

  #after(retryAfterSec: number | undefined, attempt: number): number {
    if (retryAfterSec === undefined) return this.#backoff(attempt);
    const base = Math.min(Math.max(retryAfterSec * 1000, 0), this.#retry.maxRetryAfterMs);
    return base + Math.random() * this.#retry.jitter * Math.max(base, 1000);
  }

  #updateRate(h: Headers): void {
    const n = (name: string) => {
      const v = h.get(name);
      return v === null || v === "" || Number.isNaN(Number(v)) ? undefined : Number(v);
    };
    const limit = n("x-ratelimit-limit");
    const remaining = n("x-ratelimit-remaining");
    if (limit !== undefined) this.rate.limit = limit;
    if (remaining !== undefined) this.rate.remaining = remaining;
    const plan = h.get("x-plan");
    if (plan) this.rate.plan = plan;
    const delay = n("x-data-delay-sec");
    if (delay !== undefined) this.rate.dataDelaySec = delay;
    const clock = n("x-replay-clock");
    if (clock !== undefined) this.rate.replayClock = clock;
  }

  /** Any endpoint, with the same pacing, retries and errors as the named methods. */
  async request<T = Body>(method: string, path: string, opts: RequestOptions = {}): Promise<T> {
    const m = method.toUpperCase();
    const json = opts.json as { client_order_id?: unknown } | undefined;
    const canRetry = IDEMPOTENT.has(m) || Boolean(json && typeof json === "object" && json.client_order_id);
    const url = new URL(path.startsWith("http") ? path : this.baseUrl + path);
    for (const [k, v] of Object.entries(clean(opts.query ?? {}))) url.searchParams.set(k, String(v));
    const headers: Record<string, string> = { Accept: "application/json", ...this.#headers };
    if (opts.auth !== false && this.#key) headers["Authorization"] = `Bearer ${this.#key}`;
    if (this.replaySession) headers[REPLAY_HEADER] = this.replaySession;
    if (opts.json !== undefined) headers["Content-Type"] = "application/json";
    Object.assign(headers, opts.headers ?? {});
    const body = opts.json === undefined ? undefined : JSON.stringify(opts.json);

    for (let attempt = 0; ; attempt++) {
      if (this.#retry.pace) {
        const wait = this.#notBefore - Date.now();
        if (wait > 0) await this.#sleep(wait);
      }
      let r: Response;
      const ctl = new AbortController();
      const timer = setTimeout(() => ctl.abort(), this.#timeoutMs);
      try {
        r = await this.#fetch(url.toString(), { method: m, headers, body, signal: ctl.signal });
      } catch (e) {
        clearTimeout(timer);
        if (canRetry && attempt < this.#retry.maxRetries) {
          await this.#sleep(this.#backoff(attempt));
          continue;
        }
        throw new NetworkError("NETWORK", e instanceof Error ? e.name : "fetch failed");
      }
      clearTimeout(timer);
      this.#updateRate(r.headers);
      if (r.status < 400) {
        // an empty bucket: wait for one token before the next call (a 429 says its own wait)
        if (this.rate.remaining === 0 && this.rate.limit) this.#notBefore = Date.now() + 60_000 / this.rate.limit;
        if (opts.raw) return (new Uint8Array(await r.arrayBuffer()) as unknown) as T;
        const ct = r.headers.get("content-type") ?? "";
        return (ct.includes("json") ? await r.json() : await r.text()) as T;
      }
      let data: unknown = {};
      try {
        data = await r.json();
      } catch {
        data = {};
      }
      const raHeader = r.headers.get("retry-after");
      const raBody = (data as { retry_after_sec?: unknown }).retry_after_sec;
      const retryAfter = raHeader !== null && !Number.isNaN(Number(raHeader)) ? Number(raHeader)
        : typeof raBody === "number" ? raBody : undefined;
      if (r.status === 429 && attempt < this.#retry.maxRetries) {
        await this.#sleep(this.#after(retryAfter, attempt));
        continue;
      }
      if (RETRY_STATUSES.has(r.status) && canRetry && attempt < this.#retry.maxRetries) {
        await this.#sleep(this.#after(retryAfter, attempt));
        continue;
      }
      throw fromResponse(r.status, data, retryAfter);
    }
  }

  // ---- meta ----
  health() { return this.request("GET", "/health", { auth: false }); }
  /** Which features are open and when the rest open. */
  ladder() { return this.request("GET", "/v1/ladder", { auth: false }); }
  plans() { return this.request("GET", "/v1/plans", { auth: false }); }
  status() { return this.request("GET", "/v1/status"); }
  fillModel() { return this.request("GET", "/v1/fill-model"); }

  // ---- keys and bots ----
  me() { return this.request("GET", "/v1/me"); }
  /** Exchange an operator invite code for a key (in `api_key`, shown once). */
  redeemInvite(inviteCode: string) { return this.request("POST", "/v1/keys", { json: { invite_code: inviteCode }, auth: false }); }
  bots() { return this.request("GET", "/v1/bots"); }
  createBot(name: string) { return this.request("POST", "/v1/bots", { json: { name } }); }
  bot(bot = "default") { return this.request("GET", `/v1/bots/${enc(bot)}`); }
  resetBot(bot = "default") { return this.request("POST", `/v1/bots/${enc(bot)}/reset`); }
  botSettings(bot = "default", settings: { rug_block: "loose" | "normal" | "strict" | null }) {
    return this.request("PUT", `/v1/bots/${enc(bot)}/settings`, { json: settings });
  }
  leaderboardOptIn(bot = "default", optIn = true) {
    return this.request("POST", `/v1/bots/${enc(bot)}/leaderboard`, { json: { opt_in: optIn } });
  }

  // ---- market data ----
  /** `lang` is accepted for older callers and ignored: responses are English only. */
  tokensNew(opts: { limit?: number; dex?: string; lang?: "en" } = {}) {
    return this.request<TokensNew>("GET", "/v1/tokens/new", { query: { limit: opts.limit ?? 50, dex: opts.dex } });
  }
  /** Metadata, latest snapshot, full rug report. An untracked token answers status 'tracking_started'. */
  /** `lang` is accepted for older callers and ignored: responses are English only. */
  token(mint: string, _opts: { lang?: "en" } = {}) {
    return this.request("GET", `/v1/tokens/${enc(mint)}`);
  }
  snapshots(mint: string, opts: { from?: number; to?: number; limit?: number } = {}) {
    return this.request("GET", `/v1/tokens/${enc(mint)}/snapshots`, { query: opts });
  }
  quote(mint: string, side: "buy" | "sell", amount: number, opts: { slippageBps?: number; unit?: "sol" | "token" } = {}) {
    return this.request<Quote>("GET", "/v1/quote", {
      query: { mint, side, amount, slippageBps: opts.slippageBps ?? 300, unit: opts.unit },
    });
  }

  // ---- orders and fills ----
  /** Place a paper order. A client_order_id is generated when omitted, so retries are safe. */
  placeOrder(order: OrderIn, opts: { bot?: string } = {}) {
    const body = { type: "market", amount_unit: "sol", slippage_bps: 300, priority_fee_lamports: 0, ...order,
      client_order_id: order.client_order_id ?? newClientOrderId() };
    return this.request<Order>("POST", `/v1/bots/${enc(opts.bot ?? "default")}/orders`, { json: body });
  }
  /** One order. wait (seconds, up to 10): the server holds the answer while a live market order is pending. */
  order(orderId: string, opts: { bot?: string; wait?: number } = {}) {
    return this.request<Order>("GET", `/v1/bots/${enc(opts.bot ?? "default")}/orders/${enc(orderId)}`, { query: { wait: opts.wait } });
  }
  orders(opts: { bot?: string; status?: string; limit?: number } = {}) {
    return this.request<Body & { orders: Order[] }>("GET", `/v1/bots/${enc(opts.bot ?? "default")}/orders`, {
      query: { status: opts.status, limit: opts.limit },
    });
  }
  cancelOrder(orderId: string, opts: { bot?: string } = {}) {
    return this.request<Order>("DELETE", `/v1/bots/${enc(opts.bot ?? "default")}/orders/${enc(orderId)}`);
  }
  positions(opts: { bot?: string } = {}) {
    return this.request<Body & { positions: Record<string, unknown>[] }>("GET", `/v1/bots/${enc(opts.bot ?? "default")}/positions`);
  }
  fills(opts: { bot?: string; limit?: number; since?: number } = {}) {
    return this.request<Body & { fills: Fill[] }>("GET", `/v1/bots/${enc(opts.bot ?? "default")}/fills`, {
      query: { limit: opts.limit, since: opts.since },
    });
  }
  equity(opts: { bot?: string; resolution?: "1m" | "5m" | "1h"; from?: number; to?: number } = {}) {
    return this.request("GET", `/v1/bots/${enc(opts.bot ?? "default")}/equity`, {
      query: { resolution: opts.resolution ?? "1m", from: opts.from, to: opts.to },
    });
  }
  /** Every fill, failure and skip with its reason code. */
  decisions(opts: { bot?: string; limit?: number; since?: number } = {}) {
    return this.request("GET", `/v1/bots/${enc(opts.bot ?? "default")}/decisions`, { query: { limit: opts.limit, since: opts.since } });
  }
  /** Wait until the order leaves 'pending' (server long poll). In a speed 0 replay it returns the order as is. */
  async waitForOrder(orderId: string, opts: { bot?: string; timeoutMs?: number } = {}): Promise<Order> {
    const deadline = Date.now() + (opts.timeoutMs ?? 10_000);
    const wait = () => (this.replaySession ? undefined : Math.min(10, Math.max(0, (deadline - Date.now()) / 1000)));
    let o = await this.order(orderId, { bot: opts.bot, wait: wait() });
    while (o.status === "pending" && !this.replaySession && deadline - Date.now() > 50) {
      o = await this.order(orderId, { bot: opts.bot, wait: wait() });
    }
    return o;
  }

  // ---- replay and claims ----
  createReplay(startTs: number, endTs: number, speed = 0) {
    return this.request<ReplaySession>("POST", "/v1/replays", { json: { start_ts: startTs, end_ts: endTs, speed } });
  }
  replaySessionInfo(sessionId: string) { return this.request<ReplaySession>("GET", `/v1/replays/${enc(sessionId)}`); }
  /** The recorded data range replay sessions can use: {available: {from, to, ...}, usage, ...}. */
  replayRange() { return this.request("GET", "/v1/replays/range"); }
  replays(limit?: number) { return this.request("GET", "/v1/replays", { query: { limit } }); }
  finishReplay(sessionId: string) { return this.request("DELETE", `/v1/replays/${enc(sessionId)}`); }
  advanceReplay(sessionId: string, sec: number) {
    return this.request<ReplaySession>("POST", `/v1/replays/${enc(sessionId)}/advance`, { json: { sec } });
  }
  /** Create a replay session and return a helper with a bound client. */
  async replay(startTs: number, endTs: number, speed = 0): Promise<Replay> {
    return new Replay(this, await this.createReplay(startTs, endTs, speed));
  }
  /** Deterministic re-run of a trading claim. */
  checkClaim(claim: ClaimIn) { return this.request("POST", "/v1/claims", { json: { preset: "default", ...claim } }); }
  claim(claimId: string) { return this.request("GET", `/v1/claims/${enc(claimId)}`); }

  // ---- public board, leaderboard, arena ----
  board() { return this.request("GET", "/v1/board", { auth: false }); }
  leaderboard(period: "24h" | "7d" | "season" = "24h") { return this.request("GET", "/v1/board/leaderboard", { query: { period }, auth: false }); }
  /** Share card PNG bytes of one of your bots. */
  botCard(bot = "default", period: "24h" | "7d" | "season" = "7d") {
    return this.request<Uint8Array>("GET", `/v1/bots/${enc(bot)}/card.png`, { query: { period }, raw: true });
  }
  arena() { return this.request("GET", "/v1/arena", { auth: false }); }
  arenaSeason(season: string) { return this.request("GET", `/v1/arena/seasons/${enc(season)}`, { auth: false }); }
  arenaEnter(bot?: string) { return this.request("POST", "/v1/arena/entries", { json: bot ? { bot } : {} }); }
  arenaEntries() { return this.request("GET", "/v1/arena/entries"); }

  // ---- compat layer (the request formats in docs/compat-spec.md) ----
  compatQuote(query: Query) { return this.request("GET", "/compat/quote/v1/quote", { query }); }
  compatTrade(body: Record<string, unknown>, opts: { bot?: string } = {}) {
    return this.request("POST", "/compat/trade/api/trade", { json: body, headers: opts.bot ? { "X-Dryrun-Bot": opts.bot } : {} });
  }

  // ---- WebSocket ----
  /** A WebSocket stream: auth first message, auto-reconnect, resume from the last seq. */
  stream(channels: string[] = [], opts: Omit<StreamOptions, "apiKey" | "baseUrl" | "channels"> = {}): Stream {
    if (!this.#key) throw new Error("an API key is needed for the WebSocket stream");
    return new Stream({ apiKey: this.#key, baseUrl: this.baseUrl, channels, session: this.replaySession, ...opts });
  }
}

/** A replay session: `client` runs your bot code on the session clock, `advance(sec)` moves it. */
export class Replay {
  readonly sessionId: string;
  readonly client: Client;
  session: ReplaySession;
  readonly #parent: Client;

  constructor(parent: Client, session: ReplaySession) {
    if (!session || !session.session_id) throw new SimvexError("INVALID_RESPONSE", "replay session without session_id");
    this.#parent = parent;
    this.session = session;
    this.sessionId = session.session_id;
    this.client = parent.inReplay(this.sessionId);
  }

  get clock(): number | undefined { return this.session.clock_ts; }

  async advance(sec: number): Promise<ReplaySession> {
    const r = await this.#parent.advanceReplay(this.sessionId, sec);
    this.session = { ...this.session, ...r };
    return r;
  }
}

function enc(s: string): string {
  return encodeURIComponent(s);
}
