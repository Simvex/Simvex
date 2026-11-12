"""Synchronous client.

    from simvex_client import Client
    c = Client()                       # SIMVEX_API_KEY and SIMVEX_BASE_URL from the environment
    order = c.place_order(mint=m, side="buy", amount=0.1)
    print(c.wait_for_order(order["order_id"])["status"])
"""
from __future__ import annotations

import time
from typing import Any

import httpx

from ._base import (REPLAY_HEADER, RETRY_STATUSES, USER_AGENT, Endpoints, RateInfo, RetryPolicy, idempotent,
                    resolve_config, retry_after_of)
from .errors import NetworkError, RateLimited, SimvexError, from_response


def _decode(r: httpx.Response) -> Any:
    if "json" in r.headers.get("content-type", ""):
        try:
            return r.json()
        except ValueError:
            return {"text": r.text}
    return r.text


class Client(Endpoints):
    """Every REST endpoint, with rate-limit pacing, retries with jitter and typed errors.

    `http_client` lets you pass your own `httpx.Client` (for example a test client); it is not closed by `close()`.
    """

    sleep = staticmethod(time.sleep)

    def __init__(self, api_key: str | None = None, base_url: str | None = None, *, timeout: float = 30.0,
                 retry: RetryPolicy | None = None, replay_session: str | None = None,
                 http_client: httpx.Client | None = None, headers: dict[str, str] | None = None):
        self.api_key, self.base_url = resolve_config(api_key, base_url)
        self.retry = retry or RetryPolicy()
        self.replay_session_id = replay_session
        self.rate = RateInfo()
        self._own = http_client is None
        self._http = http_client or httpx.Client(timeout=timeout)
        self._extra_headers = dict(headers or {})
        self._not_before = 0.0

    def __repr__(self) -> str:  # never show the key
        return f"Client(base_url={self.base_url!r}, replay_session={self.replay_session_id!r})"

    def __enter__(self) -> "Client":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        if self._own:
            self._http.close()

    def _headers(self, extra: dict | None, auth: bool) -> dict[str, str]:
        h = {"User-Agent": USER_AGENT, "Accept": "application/json", **self._extra_headers}
        if auth and self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        if self.replay_session_id:
            h[REPLAY_HEADER] = self.replay_session_id
        if extra:
            h.update({k: v for k, v in extra.items() if v is not None})
        return h

    def _url(self, path: str) -> str:
        return path if path.startswith("http") else f"{self.base_url}{path}"

    def request(self, method: str, path: str, *, params: dict | None = None, json: Any = None,
                headers: dict | None = None, auth: bool = True, raw: bool = False) -> Any:
        """Any endpoint, with the same pacing, retries and errors as the named methods."""
        return self._request(method, path, params=params, json=json, headers=headers, auth=auth, raw=raw)

    def _request(self, method, path, *, params=None, json=None, headers=None, auth=True, raw=False):
        pol = self.retry
        can_retry = idempotent(method, json)
        attempt = 0
        while True:
            if pol.pace:
                wait = self._not_before - time.monotonic()
                if wait > 0:
                    self.sleep(wait)
            try:
                r = self._http.request(method, self._url(path), params=params, json=json,
                                       headers=self._headers(headers, auth))
            except httpx.TransportError as e:
                if can_retry and attempt < pol.max_retries:
                    self.sleep(pol.backoff(attempt))
                    attempt += 1
                    continue
                raise NetworkError("NETWORK", type(e).__name__) from e
            self.rate.update(r.headers)
            pace = self.rate.pace_seconds() if r.status_code < 400 else 0.0  # a 429 already says how long to wait
            if pace:
                self._not_before = time.monotonic() + pace
            if r.status_code < 400:
                return r.content if raw else _decode(r)
            body = _decode(r)
            ra = retry_after_of(r.headers, body)
            if r.status_code == 429 and attempt < pol.max_retries:
                self.sleep(pol.after(ra, attempt))
                attempt += 1
                continue
            if r.status_code in RETRY_STATUSES and can_retry and attempt < pol.max_retries:
                self.sleep(pol.after(ra, attempt) if ra else pol.backoff(attempt))
                attempt += 1
                continue
            raise from_response(r.status_code, body, ra)

    # ---- helpers ----
    def wait_for_order(self, order_id: str, *, bot: str = "default", timeout: float = 10.0) -> dict:
        """Wait until the order leaves 'pending' (market orders confirm after about 1.2 s) and return it.
        Uses the server's long poll (GET ...?wait=), so it costs one call per 10 s. In a replay session with
        speed 0 the order confirms only when you advance the clock, so this returns it still pending."""
        deadline = time.monotonic() + timeout
        o = self.order(order_id, bot=bot, wait=None if self.replay_session_id else min(timeout, 10.0))
        while (o.get("status") == "pending" and not self.replay_session_id
               and (left := deadline - time.monotonic()) > 0.05):
            o = self.order(order_id, bot=bot, wait=min(left, 10.0))
        return o

    def in_replay(self, session_id: str) -> "Client":
        """The same client bound to a replay session: every call carries X-Replay-Session."""
        c = Client.__new__(Client)
        c.__dict__.update(self.__dict__)
        c.replay_session_id = session_id
        c.rate = RateInfo()
        c._own = False
        return c

    def replay(self, start_ts: float, end_ts: float, speed: float = 0) -> "Replay":
        """Create a replay session and return a helper holding a bound client."""
        return Replay(self, self.create_replay(start_ts, end_ts, speed))

    def stream(self, channels=None, **kw):
        """An async WebSocket stream (needs the 'ws' extra). See simvex_client.ws.Stream."""
        from .ws import Stream
        return Stream(self.api_key, self.base_url, channels=channels,
                      session=kw.pop("session", self.replay_session_id), **kw)


class Replay:
    """A replay session: `.client` runs your bot code on the session clock, `.advance(sec)` moves it."""

    def __init__(self, parent: Client, session: dict):
        if not isinstance(session, dict) or not session.get("session_id"):
            raise SimvexError("INVALID_RESPONSE", "replay session without session_id", body=session or {})
        self.session = session
        self.session_id: str = session["session_id"]
        self._parent = parent
        self.client = parent.in_replay(self.session_id)

    @property
    def clock(self) -> float | None:
        return self.session.get("clock_ts")

    def advance(self, sec: float) -> dict:
        r = self._parent.advance_replay(self.session_id, sec)
        if isinstance(r, dict):
            self.session.update(r)
        return r

    def refresh(self) -> dict:
        r = self._parent.replay_session(self.session_id)
        if isinstance(r, dict):
            self.session.update(r)
        return r


__all__ = ["Client", "Replay", "RateLimited"]
