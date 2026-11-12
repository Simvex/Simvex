"""Shared by the sync and async clients: configuration, retry policy and the endpoint table.

Endpoint methods live once in `Endpoints` and return `self._request(...)`. In `Client` that is the parsed body; in
`AsyncClient` it is an awaitable of the parsed body. So `c.me()` and `await ac.me()` share one definition.
"""
from __future__ import annotations

import os
import random
import uuid
from dataclasses import dataclass, field
from typing import Any

from . import __version__

DEFAULT_BASE_URL = "http://127.0.0.1:8410"
ENV_KEY = "SIMVEX_API_KEY"
ENV_BASE_URL = "SIMVEX_BASE_URL"
REPLAY_HEADER = "X-Replay-Session"
COMPAT_BOT_HEADER = "X-Dryrun-Bot"
USER_AGENT = f"simvex-client-python/{__version__}"
IDEMPOTENT_METHODS = {"GET", "HEAD", "OPTIONS", "PUT", "DELETE"}
RETRY_STATUSES = {500, 502, 503, 504}


@dataclass
class RetryPolicy:
    """429 is always retried (the server refused before doing anything), after `Retry-After` plus jitter.
    5xx and network errors are retried only for idempotent requests: GET, PUT, DELETE, and POSTs that carry a
    `client_order_id` (the server returns the first order for a repeat)."""

    max_retries: int = 3
    backoff_base: float = 0.5      # seconds, doubled per attempt
    backoff_max: float = 20.0
    jitter: float = 0.25           # up to +25% random extra wait
    max_retry_after: float = 120.0
    pace: bool = True              # when X-RateLimit-Remaining hits 0, wait for one token before the next call

    def backoff(self, attempt: int) -> float:
        d = min(self.backoff_max, self.backoff_base * (2 ** attempt))
        return d * (1 + random.uniform(0, self.jitter))

    def after(self, retry_after: float | None, attempt: int) -> float:
        if retry_after is None:
            return self.backoff(attempt)
        base = min(max(retry_after, 0.0), self.max_retry_after)
        return base + random.uniform(0, self.jitter * max(base, 1.0))


@dataclass
class RateInfo:
    """The last rate-limit headers seen (X-RateLimit-Limit, X-RateLimit-Remaining, X-Plan, X-Data-Delay-Sec)."""

    limit: int | None = None
    remaining: int | None = None
    plan: str | None = None
    data_delay_sec: float | None = None
    replay_clock: float | None = None
    extra: dict = field(default_factory=dict)

    def update(self, headers) -> None:
        g = headers.get
        if g("x-ratelimit-limit") is not None:
            self.limit = _num(g("x-ratelimit-limit"), int)
        if g("x-ratelimit-remaining") is not None:
            self.remaining = _num(g("x-ratelimit-remaining"), int)
        if g("x-plan"):
            self.plan = g("x-plan")
        if g("x-data-delay-sec") is not None:
            self.data_delay_sec = _num(g("x-data-delay-sec"), float)
        if g("x-replay-clock") is not None:
            self.replay_clock = _num(g("x-replay-clock"), float)

    def pace_seconds(self) -> float:
        """Seconds until one more call fits, when the bucket is empty (the bucket refills limit/60 per second)."""
        if self.remaining == 0 and self.limit:
            return 60.0 / self.limit
        return 0.0


def _num(v, t):
    try:
        return t(v)
    except (TypeError, ValueError):
        return None


def resolve_config(api_key: str | None, base_url: str | None) -> tuple[str | None, str]:
    key = api_key if api_key is not None else os.environ.get(ENV_KEY)
    if key is not None:
        key = key.strip()
        if not key.startswith("dr_"):
            raise ValueError("API keys start with 'dr_'. Never pass a wallet private key or seed phrase here.")
    base = (base_url or os.environ.get(ENV_BASE_URL) or DEFAULT_BASE_URL).rstrip("/")
    return key, base


def new_client_order_id() -> str:
    return "sdk-" + uuid.uuid4().hex[:24]


def idempotent(method: str, json_body: Any) -> bool:
    return method.upper() in IDEMPOTENT_METHODS or (isinstance(json_body, dict) and bool(json_body.get("client_order_id")))


def retry_after_of(headers, body: Any) -> float | None:
    v = headers.get("retry-after")
    if v is not None:
        try:
            return float(v)
        except ValueError:
            pass
    if isinstance(body, dict) and isinstance(body.get("retry_after_sec"), (int, float)):
        return float(body["retry_after_sec"])
    return None


def _clean(d: dict) -> dict:
    return {k: v for k, v in d.items() if v is not None}


class Endpoints:
    """Every REST endpoint. Paths take a bot name or id; the first bot is 'default'."""

    def _request(self, method: str, path: str, *, params: dict | None = None, json: Any = None,
                 headers: dict | None = None, auth: bool = True,
                 raw: bool = False):  # pragma: no cover - implemented by clients
        raise NotImplementedError

    # ---- meta ----
    def health(self):
        return self._request("GET", "/health", auth=False)

    def ladder(self):
        """Which features are open and when the rest open."""
        return self._request("GET", "/v1/ladder", auth=False)

    def plans(self):
        return self._request("GET", "/v1/plans", auth=False)

    def status(self):
        """Collector lag, tracked tokens, quote failure rate, last snapshot time."""
        return self._request("GET", "/v1/status")

    def fill_model(self):
        """The fill model's parameters and rules."""
        return self._request("GET", "/v1/fill-model")

    # ---- keys and bots ----
    def me(self):
        """Your key, plan, limits, fuel, bots and usage."""
        return self._request("GET", "/v1/me")

    def redeem_invite(self, invite_code: str):
        """Exchange an operator invite code for a key. The key is in `api_key`, shown once."""
        return self._request("POST", "/v1/keys", json={"invite_code": invite_code}, auth=False)

    def bots(self):
        return self._request("GET", "/v1/bots")

    def create_bot(self, name: str):
        return self._request("POST", "/v1/bots", json={"name": name})

    def bot(self, bot: str = "default"):
        return self._request("GET", f"/v1/bots/{bot}")

    def reset_bot(self, bot: str = "default"):
        """Back to 10 paper SOL. Once per 24 hours; the bot leaves this season's board."""
        return self._request("POST", f"/v1/bots/{bot}/reset")

    def bot_settings(self, bot: str = "default", *, rug_block: str | None = None):
        """rug_block: None, 'loose', 'normal' or 'strict' (orders on tokens failing that level get RUG_BLOCKED)."""
        return self._request("PUT", f"/v1/bots/{bot}/settings", json={"rug_block": rug_block})

    def leaderboard_opt_in(self, bot: str = "default", opt_in: bool = True):
        return self._request("POST", f"/v1/bots/{bot}/leaderboard", json={"opt_in": opt_in})

    # ---- market data ----
    def tokens_new(self, limit: int = 50, *, dex: str | None = None, lang: str | None = None):
        """Recent new pairs: {'tokens': [...], 'count', 'as_of', 'data_delay_sec'}. `lang` is ignored (English only)."""
        return self._request("GET", "/v1/tokens/new", params=_clean({"limit": limit, "dex": dex}))

    def token(self, mint: str, *, lang: str | None = None):
        """Metadata, latest snapshot and the full rug report. 202 (tracking started) comes back as a normal body
        with status 'tracking_started'; ask again a few seconds later. `lang` is ignored (English only)."""
        return self._request("GET", f"/v1/tokens/{mint}")

    def snapshots(self, mint: str, *, start: float | None = None, end: float | None = None, limit: int | None = None):
        return self._request("GET", f"/v1/tokens/{mint}/snapshots",
                             params=_clean({"from": start, "to": end, "limit": limit}))

    def quote(self, mint: str, side: str, amount: float, *, slippage_bps: int = 300, unit: str | None = None):
        """Paper quote. side 'buy' takes SOL, 'sell' takes tokens (unit 'sol' or 'token')."""
        return self._request("GET", "/v1/quote", params=_clean({"mint": mint, "side": side, "amount": amount,
                                                                "slippageBps": slippage_bps, "unit": unit}))

    # ---- orders and fills ----
    def place_order(self, *, mint: str, side: str, amount: float, type: str = "market",  # noqa: A002
                    amount_unit: str = "sol", slippage_bps: int = 300, priority_fee_lamports: int = 0,
                    client_order_id: str | None = None, limit_price_sol: float | None = None,
                    expires_in_sec: int | None = None, tp_pct: float | None = None, sl_pct: float | None = None,
                    trail_pct: float | None = None, bot: str = "default"):
        """Place a paper order. A client_order_id is generated when you give none, so a retry never doubles it."""
        body = _clean({"mint": mint, "side": side, "type": type, "amount": amount, "amount_unit": amount_unit,
                       "slippage_bps": slippage_bps, "priority_fee_lamports": priority_fee_lamports,
                       "client_order_id": client_order_id or new_client_order_id(),
                       "limit_price_sol": limit_price_sol, "expires_in_sec": expires_in_sec, "tp_pct": tp_pct,
                       "sl_pct": sl_pct, "trail_pct": trail_pct})
        return self._request("POST", f"/v1/bots/{bot}/orders", json=body)

    def order(self, order_id: str, *, bot: str = "default", wait: float | None = None):
        """One order. wait (up to 10 s): the server holds the answer while a live market order is pending."""
        return self._request("GET", f"/v1/bots/{bot}/orders/{order_id}", params=_clean({"wait": wait}))

    def orders(self, *, bot: str = "default", status: str | None = None, limit: int | None = None):
        return self._request("GET", f"/v1/bots/{bot}/orders", params=_clean({"status": status, "limit": limit}))

    def cancel_order(self, order_id: str, *, bot: str = "default"):
        """Cancel an open limit or tp_sl order."""
        return self._request("DELETE", f"/v1/bots/{bot}/orders/{order_id}")

    def positions(self, *, bot: str = "default"):
        return self._request("GET", f"/v1/bots/{bot}/positions")

    def fills(self, *, bot: str = "default", limit: int | None = None, since: float | None = None):
        return self._request("GET", f"/v1/bots/{bot}/fills", params=_clean({"limit": limit, "since": since}))

    def equity(self, *, bot: str = "default", resolution: str = "1m", start: float | None = None,
               end: float | None = None):
        return self._request("GET", f"/v1/bots/{bot}/equity",
                             params=_clean({"resolution": resolution, "from": start, "to": end}))

    def decisions(self, *, bot: str = "default", limit: int | None = None, since: float | None = None):
        """Every fill, failure and skip with its reason code."""
        return self._request("GET", f"/v1/bots/{bot}/decisions", params=_clean({"limit": limit, "since": since}))

    # ---- replay and claims ----
    def create_replay(self, start_ts: float, end_ts: float, speed: float = 0):
        """A replay session over recorded data. speed 0: move the clock with advance_replay; up to 60x."""
        return self._request("POST", "/v1/replays", json={"start_ts": start_ts, "end_ts": end_ts, "speed": speed})

    def replay_session(self, session_id: str):
        return self._request("GET", f"/v1/replays/{session_id}")

    def replay_range(self):
        """The recorded data range replay sessions can use: {'available': {'from', 'to', ...}, 'usage', ...}."""
        return self._request("GET", "/v1/replays/range")

    def replays(self, limit: int | None = None):
        """Your replay sessions."""
        return self._request("GET", "/v1/replays", params=_clean({"limit": limit}))

    def finish_replay(self, session_id: str):
        return self._request("DELETE", f"/v1/replays/{session_id}")

    def advance_replay(self, session_id: str, sec: float):
        return self._request("POST", f"/v1/replays/{session_id}/advance", json={"sec": sec})

    def check_claim(self, *, start_balance_usd: float, claimed_end_usd: float, window_start: float,
                    window_end: float, preset: str | None = "default", rules: dict | None = None,
                    source_url: str | None = None):
        """Deterministic re-run of a trading claim. Verdict: reproduced, not_reproduced or insufficient_data."""
        return self._request("POST", "/v1/claims", json=_clean({
            "start_balance_usd": start_balance_usd, "claimed_end_usd": claimed_end_usd,
            "window_start": window_start, "window_end": window_end, "preset": preset, "rules": rules,
            "source_url": source_url}))

    def claim(self, claim_id: str):
        return self._request("GET", f"/v1/claims/{claim_id}")

    # ---- public board, leaderboard and arena ----
    def board(self):
        """Public board data: leaderboards, arena, dodged rugs, fill model, status (pseudonyms only)."""
        return self._request("GET", "/v1/board", auth=False)

    def leaderboard(self, period: str = "24h"):
        """period: 24h, 7d or season. Opt-in bots only."""
        return self._request("GET", "/v1/board/leaderboard", params={"period": period}, auth=False)

    def bot_card(self, bot: str = "default", *, period: str = "7d") -> Any:
        """Share card PNG (bytes) of one of your bots."""
        return self._request("GET", f"/v1/bots/{bot}/card.png", params={"period": period}, raw=True)

    def arena(self):
        """The running season's standings and the last results."""
        return self._request("GET", "/v1/arena", auth=False)

    def arena_season(self, season: str):
        return self._request("GET", f"/v1/arena/seasons/{season}", auth=False)

    def arena_enter(self, bot: str | None = None):
        """Enter a bot in the running season (its own 10 SOL book)."""
        return self._request("POST", "/v1/arena/entries", json=_clean({"bot": bot}))

    def arena_entries(self):
        return self._request("GET", "/v1/arena/entries")

    # ---- compat layer (same request formats as the services it mirrors; see docs/compat-spec.md) ----
    def compat_quote(self, **params):
        """GET /compat/quote/v1/quote with that format's query fields (inputMint, outputMint, amount, slippageBps)."""
        return self._request("GET", "/compat/quote/v1/quote", params=params)

    def compat_trade(self, body: dict, *, bot: str | None = None):
        """POST /compat/trade/api/trade with that format's body. The receipt id starts with 'paper_'."""
        return self._request("POST", "/compat/trade/api/trade", json=body,
                             headers={COMPAT_BOT_HEADER: bot} if bot else None)
