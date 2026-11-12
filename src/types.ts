/** Request and response shapes. Field names are the API's (snake_case). Responses carry more fields than listed. */

export type Side = "buy" | "sell";
export type OrderType = "market" | "limit" | "tp_sl";
export type AmountUnit = "sol" | "token" | "pct";
export type OrderStatus = "pending" | "open" | "filled" | "failed" | "cancelled" | "expired" | "rejected";

export interface Body {
  disclaimer?: string;
  [key: string]: unknown;
}

export interface OrderIn {
  mint: string;
  side: Side;
  amount: number;
  type?: OrderType;
  amount_unit?: AmountUnit;
  slippage_bps?: number;
  priority_fee_lamports?: number;
  /** Generated when omitted, so a retry never doubles an order. */
  client_order_id?: string;
  limit_price_sol?: number;
  expires_in_sec?: number;
  tp_pct?: number;
  sl_pct?: number;
  trail_pct?: number;
}

export interface Order extends Body {
  order_id: string;
  bot_id: string;
  book: string;
  client_order_id: string | null;
  type: OrderType;
  side: Side;
  mint: string;
  amount: number;
  amount_unit: AmountUnit;
  status: OrderStatus;
  code: string | null;
  expected: Record<string, unknown>;
  result: Record<string, unknown>;
}

export interface Fill extends Body {
  fill_id: string;
  order_id: string;
  ts: number;
  mint: string;
  side: Side;
  sol: number;
  tokens: number;
  price_sol: number;
  tx_cost_sol: number;
  priority_fee_sol: number;
  quote_source: string;
  code: string | null;
}

export interface TokenSummary {
  mint: string;
  [key: string]: unknown;
}

export interface TokensNew extends Body {
  tokens: TokenSummary[];
  count: number;
  as_of: number;
  data_delay_sec: number;
}

export interface Quote extends Body {
  mint: string;
  side: Side;
  in_amount: number;
  out_amount: number;
  price_impact_pct: number;
  quote_source: "curve" | "aggregator" | "local_cpmm";
  quote_age_ms: number;
}

export interface ReplaySession extends Body {
  session_id: string;
  clock_ts: number;
}

export interface ClaimIn {
  start_balance_usd: number;
  claimed_end_usd: number;
  window_start: number;
  window_end: number;
  preset?: "safe" | "default" | "degen" | null;
  rules?: Record<string, unknown> | null;
  /** Stored only, never fetched. */
  source_url?: string | null;
}

export interface WsFrame {
  op: string;
  seq?: number;
  channel?: string;
  ts?: number;
  session?: string | null;
  data?: Record<string, unknown>;
  replayed?: boolean;
  [key: string]: unknown;
}
