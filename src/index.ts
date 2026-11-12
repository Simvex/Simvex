/**
 * TypeScript client for the Simvex paper-trading API (MIT). Paper trading only: real fills may differ.
 * Your bot needs an API key (dr_...), never a private key or seed phrase.
 */
export { Client, Replay, DEFAULT_BASE_URL, DEFAULT_RETRY, DISCLAIMER, VERSION, newClientOrderId } from "./client.js";
export type { ClientOptions, RateInfo, RequestOptions, RetryPolicy } from "./client.js";
export { Stream, wsUrl } from "./ws.js";
export type { StreamOptions } from "./ws.js";
export * from "./errors.js";
export type * from "./types.js";
