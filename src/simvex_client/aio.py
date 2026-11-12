"""Asynchronous client, same methods as `Client` (await each one).

    from simvex_client import AsyncClient
    async with AsyncClient() as c:
        me = await c.me()
"""
from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx

from ._base import (REPLAY_HEADER, RETRY_STATUSES, USER_AGENT, Endpoints, RateInfo, RetryPolicy, idempotent,
                    resolve_config, retry_after_of)
from .client import _decode
from .errors import NetworkError, SimvexError, from_response


class AsyncClient(Endpoints):
    sleep = staticmethod(asyncio.sleep)

    def __init__(self, api_key: str | None = None, base_url: str | None = None, *, timeout: float = 30.0,
                 retry: RetryPolicy | None = None, replay_session: str | None = None,
                 http_client: httpx.AsyncClient | None = None, headers: dict[str, str] | None = None):
        self.api_key, self.base_url = resolve_config(api_key, base_url)
        self.retry = retry or RetryPolicy()
        self.replay_session_id = replay_session
        self.rate = RateInfo()
        self._own = http_client is None
        self._http = http_client or httpx.AsyncClient(timeout=timeout)
        self._extra_headers = dict(headers or {})
        self._not_before = 0.0

    def __repr__(self) -> str:
        return f"AsyncClient(base_url={self.base_url!r}, replay_session={self.replay_session_id!r})"

    async def __aenter__(self) -> "AsyncClient":
        return self

    async def __aexit__(self, *exc) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._own:
            await self._http.aclose()

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
                headers: dict | None = None, auth: bool = True, raw: bool = False):
        return self._request(method, path, params=params, json=json, headers=headers, auth=auth, raw=raw)

    async def _request(self, method, path, *, params=None, json=None, headers=None, auth=True, raw=False):
        pol = self.retry
        can_retry = idempotent(method, json)
        attempt = 0
        while True:
            if pol.pace:
                wait = self._not_before - time.monotonic()
                if wait > 0:
                    await self.sleep(wait)
            try:
                r = await self._http.request(method, self._url(path), params=params, json=json,
                                             headers=self._headers(headers, auth))
            except httpx.TransportError as e:
                if can_retry and attempt < pol.max_retries:
                    await self.sleep(pol.backoff(attempt))
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
                await self.sleep(pol.after(ra, attempt))
                attempt += 1
                continue
            if r.status_code in RETRY_STATUSES and can_retry and attempt < pol.max_retries:
                await self.sleep(pol.after(ra, attempt) if ra else pol.backoff(attempt))
                attempt += 1
                continue
            raise from_response(r.status_code, body, ra)

    async def wait_for_order(self, order_id: str, *, bot: str = "default", timeout: float = 10.0) -> dict:
        deadline = time.monotonic() + timeout
        o = await self.order(order_id, bot=bot, wait=None if self.replay_session_id else min(timeout, 10.0))
        while (o.get("status") == "pending" and not self.replay_session_id
               and (left := deadline - time.monotonic()) > 0.05):
            o = await self.order(order_id, bot=bot, wait=min(left, 10.0))
        return o

    def in_replay(self, session_id: str) -> "AsyncClient":
        c = AsyncClient.__new__(AsyncClient)
        c.__dict__.update(self.__dict__)
        c.replay_session_id = session_id
        c.rate = RateInfo()
        c._own = False
        return c

    async def replay(self, start_ts: float, end_ts: float, speed: float = 0) -> "AsyncReplay":
        return AsyncReplay(self, await self.create_replay(start_ts, end_ts, speed))

    def stream(self, channels=None, **kw):
        from .ws import Stream
        return Stream(self.api_key, self.base_url, channels=channels,
                      session=kw.pop("session", self.replay_session_id), **kw)


class AsyncReplay:
    def __init__(self, parent: AsyncClient, session: dict):
        if not isinstance(session, dict) or not session.get("session_id"):
            raise SimvexError("INVALID_RESPONSE", "replay session without session_id", body=session or {})
        self.session = session
        self.session_id: str = session["session_id"]
        self._parent = parent
        self.client = parent.in_replay(self.session_id)

    @property
    def clock(self) -> float | None:
        return self.session.get("clock_ts")

    async def advance(self, sec: float) -> dict:
        r = await self._parent.advance_replay(self.session_id, sec)
        if isinstance(r, dict):
            self.session.update(r)
        return r
