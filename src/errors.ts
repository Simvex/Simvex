/** Typed errors. Every API error body is {code, message_en, hint, ...}; each error carries `code`. */

export interface ErrorBody {
  code?: string;
  message_en?: string;
  hint?: string;
  retry_after_sec?: number;
  opens_at?: number | null;
  [key: string]: unknown;
}

export class SimvexError extends Error {
  readonly code: string;
  readonly status: number | undefined;
  readonly hint: string;
  readonly body: ErrorBody;
  readonly retryAfter: number | undefined;

  constructor(code: string, message: string, opts: { status?: number; hint?: string; body?: ErrorBody; retryAfter?: number } = {}) {
    super(message ? `${code}: ${message}` : code);
    this.name = new.target.name;
    this.code = code;
    this.status = opts.status;
    this.hint = opts.hint ?? "";
    this.body = opts.body ?? {};
    this.retryAfter = opts.retryAfter;
  }
}

/** UNAUTHORIZED: missing, wrong, rotated or revoked key. */
export class Unauthorized extends SimvexError {}
/** NOT_YET: the feature opens later on the ladder; see `body.opens_at`. */
export class NotYet extends SimvexError {}
/** PLAN_LIMIT: past a plan limit. */
export class PlanLimit extends SimvexError {}
/** RATE_LIMITED: still limited after the client's retries. */
export class RateLimited extends SimvexError {}
/** FUEL_REQUIRED: not enough fuel. */
export class FuelRequired extends SimvexError {}
/** SECRET_REJECTED: looked like a private key or seed phrase. Nothing was stored. */
export class SecretRejected extends SimvexError {}
/** NOT_FOUND or NO_DATA. */
export class NotFound extends SimvexError {}
/** LOOKAHEAD: a replay asked for data after its clock. */
export class Lookahead extends SimvexError {}
/** CONFLICT. */
export class Conflict extends SimvexError {}
/** INVALID_REQUEST: see `body.details` for the field names. */
export class InvalidRequest extends SimvexError {}
/** Orders refused or not filled: QUOTE_*, SLIPPAGE_HIGH, BALANCE_LOW, MAX_POSITIONS, MIN_TRADE, FILL_FAILED_*, RUG_BLOCKED. */
export class OrderRejected extends SimvexError {}
/** 5xx or INTERNAL. */
export class ServerError extends SimvexError {}
/** No answer: connection refused, DNS, timeout. code is NETWORK. */
export class NetworkError extends SimvexError {}

export const ORDER_CODES = new Set([
  "QUOTE_UNAVAILABLE", "QUOTE_STALE", "SLIPPAGE_HIGH", "BALANCE_LOW", "MAX_POSITIONS", "MIN_TRADE",
  "FILL_FAILED_SLIPPAGE", "FILL_FAILED_LIQ", "RUG_BLOCKED",
]);

const BY_CODE: Record<string, typeof SimvexError> = {
  UNAUTHORIZED: Unauthorized, NOT_YET: NotYet, PLAN_LIMIT: PlanLimit, RATE_LIMITED: RateLimited,
  FUEL_REQUIRED: FuelRequired, SECRET_REJECTED: SecretRejected, NOT_FOUND: NotFound, NO_DATA: NotFound,
  LOOKAHEAD: Lookahead, CONFLICT: Conflict, INVALID_REQUEST: InvalidRequest, INTERNAL: ServerError,
};

export function fromResponse(status: number, body: unknown, retryAfter?: number): SimvexError {
  const data: ErrorBody = body && typeof body === "object" ? (body as ErrorBody) : {};
  const code = String(data.code ?? (status >= 500 ? "INTERNAL" : `HTTP_${status}`));
  const Cls = BY_CODE[code] ?? (ORDER_CODES.has(code) ? OrderRejected : status >= 500 ? ServerError : SimvexError);
  return new Cls(code, String(data.message_en ?? ""), { status, hint: String(data.hint ?? ""), body: data, retryAfter });
}
