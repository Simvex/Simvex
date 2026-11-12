import { fromResponse, NotYet, PlanLimit, SecretRejected, SimvexError, Unauthorized } from "./errors.js";
import type { WsFrame } from "./types.js";

/** The key goes in the first message, never in the URL. Close codes the stream does not reconnect after. */
const FATAL_CLOSE: Record<number, string> = { 4001: "UNAUTHORIZED", 4003: "PLAN_LIMIT", 4400: "SECRET_REJECTED" };

type WsCtor = new (url: string) => WebSocket;

export interface StreamOptions {
  apiKey: string;
  baseUrl: string;
  /** e.g. ["orders", "fills", "positions", "tokens.new", "rug.events", "prices:<mint>"] */
  channels?: string[];
  /** Replay session id: receive that session's events instead of live ones. */
  session?: string;
  /** Also yield control frames (subscribed, resumed, error). A resumed frame with complete false is always yielded. */
  includeControl?: boolean;
  /** Reconnect when nothing arrives for this long (default 60 s; the server pings every 20 s). */
  idleTimeoutMs?: number;
  maxBackoffMs?: number;
  maxReconnects?: number;
  /** WebSocket constructor (tests). Defaults to globalThis.WebSocket (Node 22+ and browsers). */
  WebSocket?: WsCtor;
}

export function wsUrl(baseUrl: string): string {
  const b = baseUrl.replace(/\/+$/, "");
  if (b.startsWith("https://")) return "wss://" + b.slice(8) + "/v1/ws";
  if (b.startsWith("http://")) return "ws://" + b.slice(7) + "/v1/ws";
  return b + "/v1/ws";
}

type Item = { frame: WsFrame } | { closed: number };

const statusFor = (code?: string) =>
  ({ UNAUTHORIZED: 401, PLAN_LIMIT: 403, NOT_YET: 403, SECRET_REJECTED: 400, RATE_LIMITED: 429 } as Record<string, number>)[code ?? ""] ?? 400;

class Timeout extends Error {}

/**
 * Async iterable of data frames ({op: "event", seq, channel, data}). Reconnects with backoff and jitter, sends auth
 * again, then {op: "resume", since_seq} with the same channels; missed frames arrive in order and duplicates are
 * dropped by seq. Server pings are answered with pong.
 */
export class Stream implements AsyncIterable<WsFrame> {
  readonly url: string;
  channels: string[];
  readonly session: string | undefined;
  lastSeq: number | undefined;
  streamId: string | undefined;
  reconnects = 0;
  authInfo: WsFrame = { op: "" };
  lastError: WsFrame | undefined;
  readonly resumes: WsFrame[] = [];
  readonly #key: string;
  readonly #opts: StreamOptions;
  readonly #Ws: WsCtor;
  #ws: WebSocket | undefined;
  #closed = false;
  #inbox: Item[] = [];
  #waiter: ((i: Item) => void) | undefined;

  constructor(opts: StreamOptions) {
    if (!opts.apiKey) throw new Error("an API key is needed for the WebSocket stream");
    this.#key = opts.apiKey;
    this.#opts = opts;
    this.url = wsUrl(opts.baseUrl);
    this.channels = [...(opts.channels ?? [])];
    this.session = opts.session;
    const W = opts.WebSocket ?? (globalThis as { WebSocket?: WsCtor }).WebSocket;
    if (!W) throw new Error("No global WebSocket (Node 22+ or a browser). Pass opts.WebSocket.");
    this.#Ws = W;
  }

  toJSON(): object {
    return { url: this.url, channels: this.channels, lastSeq: this.lastSeq }; // never the key
  }

  /** Connect, authenticate and subscribe. */
  async open(): Promise<this> {
    await this.#open(true);
    return this;
  }

  async close(): Promise<void> {
    this.#closed = true;
    this.#drop();
    this.#push({ closed: 1000 });
  }

  async subscribe(channels: string[]): Promise<void> {
    this.channels = [...new Set([...this.channels, ...channels])].sort();
    this.#send({ op: "subscribe", channels, ...(this.session ? { session: this.session } : {}) });
  }

  async unsubscribe(channels: string[]): Promise<void> {
    const drop = new Set(channels);
    this.channels = this.channels.filter((c) => !drop.has(c));
    this.#send({ op: "unsubscribe", channels, ...(this.session ? { session: this.session } : {}) });
  }

  #push(i: Item): void {
    const w = this.#waiter;
    if (w) {
      this.#waiter = undefined;
      w(i);
    } else this.#inbox.push(i);
  }

  #recv(timeoutMs: number): Promise<Item> {
    const i = this.#inbox.shift();
    if (i) return Promise.resolve(i);
    return new Promise<Item>((resolve, reject) => {
      const t = setTimeout(() => {
        this.#waiter = undefined;
        reject(new Timeout());
      }, timeoutMs);
      this.#waiter = (item) => {
        clearTimeout(t);
        resolve(item);
      };
    });
  }

  #send(msg: unknown): void {
    this.#ws?.send(JSON.stringify(msg));
  }

  #drop(): void {
    const ws = this.#ws;
    this.#ws = undefined;
    if (ws) {
      ws.onmessage = null;
      ws.onclose = null;
      ws.onerror = null;
      try {
        ws.close();
      } catch {
        /* already closed */
      }
    }
  }

  async #connect(): Promise<void> {
    this.#inbox = [];
    const ws = new this.#Ws(this.url);
    await new Promise<void>((resolve, reject) => {
      ws.onopen = () => resolve();
      ws.onerror = () => reject(new SimvexError("NETWORK", "WebSocket connect failed"));
      ws.onclose = (ev: CloseEvent) => reject(new SimvexError("NETWORK", `closed ${ev.code} while connecting`));
    });
    ws.onmessage = (ev: MessageEvent) => {
      try {
        this.#push({ frame: JSON.parse(String(ev.data)) as WsFrame });
      } catch {
        /* not JSON: ignore */
      }
    };
    ws.onclose = (ev: CloseEvent) => {
      if (this.#ws === ws) this.#push({ closed: ev.code });
    };
    ws.onerror = () => undefined;
    this.#ws = ws;
  }

  async #control(op: string, timeoutMs = 10_000): Promise<WsFrame> {
    for (;;) {
      const item = await this.#recv(timeoutMs);
      if ("closed" in item) {
        const err = this.lastError ?? { op: "error", code: FATAL_CLOSE[item.closed] ?? "WS_CLOSED" };
        throw fromResponse(statusFor(err.code as string), err);
      }
      const f = item.frame;
      if (f.op === op) {
        if (f.ok === false) throw fromResponse(400, f);
        return f;
      }
      if (f.op === "error") {
        this.lastError = f;
        throw fromResponse(statusFor(f.code as string), f);
      }
      if (f.op === "ping") this.#send({ op: "pong" });
    }
  }

  async #open(first: boolean): Promise<void> {
    await this.#connect();
    this.#send({ op: "auth", key: this.#key });
    const reply = await this.#control("auth");
    this.authInfo = reply;
    const stream = typeof reply.stream === "string" ? reply.stream : undefined;
    if (first || this.lastSeq === undefined) {
      this.lastSeq = typeof reply.seq === "number" ? reply.seq : 0;
      this.streamId = stream;
      if (this.channels.length) {
        this.#send({ op: "subscribe", channels: this.channels, ...(this.session ? { session: this.session } : {}) });
        await this.#control("subscribed"); // surfaces PLAN_LIMIT and bad channel names now
      }
    } else {
      // Missed frames arrive before the "resumed" frame, so do not wait for it here.
      this.#send({ op: "resume", since_seq: this.lastSeq, channels: this.channels,
        ...(this.session ? { session: this.session } : {}), ...(this.streamId ? { stream: this.streamId } : {}) });
      this.streamId = stream;
    }
  }

  async #reconnect(closeCode: number | undefined): Promise<void> {
    if (closeCode !== undefined && FATAL_CLOSE[closeCode]) {
      const err = this.lastError ?? { op: "error", code: FATAL_CLOSE[closeCode] };
      throw fromResponse(statusFor(err.code as string), err);
    }
    const max = this.#opts.maxBackoffMs ?? 30_000;
    for (let attempt = 0; !this.#closed; attempt++) {
      if (this.#opts.maxReconnects !== undefined && this.reconnects >= this.#opts.maxReconnects) {
        throw new SimvexError("WS_CLOSED", "gave up reconnecting", { body: this.lastError ?? {} });
      }
      this.reconnects++;
      const delay = attempt === 0 ? 50 + Math.random() * 250 : Math.min(max, 500 * 2 ** attempt) * (1 + Math.random() * 0.25);
      await new Promise((r) => setTimeout(r, delay));
      try {
        this.#drop();
        await this.#open(false);
        return;
      } catch (e) {
        if (e instanceof Unauthorized || e instanceof PlanLimit || e instanceof SecretRejected || e instanceof NotYet) throw e;
      }
    }
  }

  /** The next data frame (or control frame with includeControl). */
  async next(): Promise<IteratorResult<WsFrame>> {
    for (;;) {
      if (this.#closed) return { done: true, value: undefined };
      if (!this.#ws) await this.#reconnect(undefined);
      let item: Item;
      try {
        item = await this.#recv(this.#opts.idleTimeoutMs ?? 60_000);
      } catch (e) {
        if (!(e instanceof Timeout)) throw e;
        this.#drop();
        await this.#reconnect(undefined);
        continue;
      }
      if ("closed" in item) {
        if (this.#closed) return { done: true, value: undefined };
        this.#ws = undefined;
        await this.#reconnect(item.closed);
        continue;
      }
      const f = item.frame;
      if (f.op === "ping") {
        this.#send({ op: "pong" });
        continue;
      }
      if (f.op === "event") {
        if (typeof f.seq === "number") {
          if (this.lastSeq !== undefined && f.seq <= this.lastSeq) continue; // already delivered
          this.lastSeq = f.seq;
        }
        return { done: false, value: f };
      }
      if (f.op === "error") this.lastError = f;
      if (f.op === "resumed") {
        this.resumes.push(f);
        if (f.complete === false) return { done: false, value: f };
      }
      if (this.#opts.includeControl) return { done: false, value: f };
    }
  }

  [Symbol.asyncIterator](): AsyncIterator<WsFrame> {
    return {
      next: () => this.next(),
      return: async () => {
        await this.close();
        return { done: true, value: undefined };
      },
    };
  }
}
