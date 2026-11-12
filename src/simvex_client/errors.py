"""Typed errors. Every API error body is {code, message_en, hint, ...}; each exception carries `code`.

Catch `SimvexError` for everything, or a subclass for one family:

    try:
        c.place_order(mint=m, side="buy", amount=0.1)
    except OrderRejected as e:      # BALANCE_LOW, MIN_TRADE, QUOTE_UNAVAILABLE, ...
        print(e.code, e.hint)
"""
from __future__ import annotations

from typing import Any


class SimvexError(Exception):
    """An error answer from the API (or a transport failure, code 'NETWORK')."""

    def __init__(self, code: str, message: str = "", *, status: int | None = None, hint: str = "",
                 body: dict[str, Any] | None = None, retry_after: float | None = None):
        super().__init__(f"{code}: {message}" if message else code)
        self.code = code
        self.status = status
        self.message = message
        self.hint = hint
        self.body = body or {}
        self.retry_after = retry_after

    def __repr__(self) -> str:
        return f"{type(self).__name__}(code={self.code!r}, status={self.status!r})"


class Unauthorized(SimvexError):
    """UNAUTHORIZED: missing, wrong, rotated or revoked key."""


class NotYet(SimvexError):
    """NOT_YET: the feature is not open on the ladder yet. `opens_at` is unix seconds (or None before launch)."""

    @property
    def opens_at(self) -> float | None:
        return self.body.get("opens_at")


class PlanLimit(SimvexError):
    """PLAN_LIMIT: past the plan's bots, tracked mints, WebSocket or replay limits."""


class RateLimited(SimvexError):
    """RATE_LIMITED: still limited after the client's retries. `retry_after` is seconds."""


class FuelRequired(SimvexError):
    """FUEL_REQUIRED: a paid-in-fuel feature with too little fuel. The body lists top-up options."""


class SecretRejected(SimvexError):
    """SECRET_REJECTED: the request looked like it carried a private key or seed phrase. Nothing was stored."""


class NotFound(SimvexError):
    """NOT_FOUND or NO_DATA (a replay or claim window without recorded data; the body has the available range)."""


class Lookahead(SimvexError):
    """LOOKAHEAD: asked a replay session for data after its clock."""


class Conflict(SimvexError):
    """CONFLICT: conflicts with the current state (for example a second reset within 24 hours)."""


class InvalidRequest(SimvexError):
    """INVALID_REQUEST: the body or query does not match the schema. `body['details']` names the fields."""


class OrderRejected(SimvexError):
    """An order that was refused or did not fill: QUOTE_UNAVAILABLE, QUOTE_STALE, SLIPPAGE_HIGH, BALANCE_LOW,
    MAX_POSITIONS, MIN_TRADE, FILL_FAILED_SLIPPAGE, FILL_FAILED_LIQ, RUG_BLOCKED."""


class ServerError(SimvexError):
    """A 5xx answer, or code INTERNAL."""


class NetworkError(SimvexError):
    """The request did not get an answer (connection refused, timeout). code is 'NETWORK'."""


ORDER_CODES = {"QUOTE_UNAVAILABLE", "QUOTE_STALE", "SLIPPAGE_HIGH", "BALANCE_LOW", "MAX_POSITIONS", "MIN_TRADE",
               "FILL_FAILED_SLIPPAGE", "FILL_FAILED_LIQ", "RUG_BLOCKED"}

BY_CODE: dict[str, type[SimvexError]] = {
    "UNAUTHORIZED": Unauthorized, "NOT_YET": NotYet, "PLAN_LIMIT": PlanLimit, "RATE_LIMITED": RateLimited,
    "FUEL_REQUIRED": FuelRequired, "SECRET_REJECTED": SecretRejected, "NOT_FOUND": NotFound, "NO_DATA": NotFound,
    "LOOKAHEAD": Lookahead, "CONFLICT": Conflict, "INVALID_REQUEST": InvalidRequest, "INTERNAL": ServerError,
    **{c: OrderRejected for c in ORDER_CODES},
}


def from_response(status: int, body: Any, retry_after: float | None = None) -> SimvexError:
    data = body if isinstance(body, dict) else {}
    code = str(data.get("code") or ("INTERNAL" if status >= 500 else f"HTTP_{status}"))
    cls = BY_CODE.get(code) or (ServerError if status >= 500 else SimvexError)
    return cls(code, str(data.get("message_en") or data.get("error") or ""), status=status,
               hint=str(data.get("hint") or ""), body=data, retry_after=retry_after)
