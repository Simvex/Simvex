"""WebSocket stream for /v1/ws with auth-first-message, auto-reconnect and resume from the last seq.

Needs the `ws` extra (`pip install "simvex-client[ws]"`, which adds the `websockets` package, BSD).

    async with client.stream(["orders", "fills", "tokens.new"]) as s:
        async for ev in s:                      # data frames: {"op": "event", "seq", "channel", "data", ...}
            print(ev["channel"], ev["data"])

Protocol (see the server docs): the key goes in the first message `{"op":"auth","key":"dr_..."}`, never in the URL.
Every data frame has a `seq`. After a dropped connection the stream reconnects with backoff and jitter, sends auth
again, then `{"op":"resume","since_seq":<last seq>}` with the same channels, so missed frames arrive in order
(the server keeps 5 minutes). Duplicates are dropped by seq. A `resumed` frame with `complete: false` is always
yielded: something was older than the window, so resync over REST. Server pings are answered with pong.
"""
from __future__ import annotations

import asyncio
import json
import random
from typing import Any, Callable

from .errors import NotYet, PlanLimit, SecretRejected, SimvexError, Unauthorized, from_response

FATAL_CLOSE = {4001: Unauthorized, 4003: PlanLimit, 4400: SecretRejected}


def ws_url(base_url: str) -> str:
    if base_url.startswith("https://"):
        return "wss://" + base_url[len("https://"):] + "/v1/ws"
    if base_url.startswith("http://"):
        return "ws://" + base_url[len("http://"):] + "/v1/ws"
    return base_url.rstrip("/") + "/v1/ws"


def _default_connect():
    try:
        from websockets.asyncio.client import connect
    except ImportError as e:  # pragma: no cover - depends on the environment
        raise ImportError('The WebSocket stream needs the ws extra: pip install "simvex-client[ws]"') from e
    return lambda url: connect(url, open_timeout=10, ping_interval=None, max_size=2 ** 22)


class Stream:
    def __init__(self, api_key: str | None, base_url: str, *, channels: list[str] | None = None,
                 session: str | None = None, include_control: bool = False, idle_timeout: float = 60.0,
                 max_backoff: float = 30.0, max_reconnects: int | None = None,
                 connect: Callable[[str], Any] | None = None):
        if not api_key:
            raise ValueError("an API key is needed for the WebSocket stream")
        self._key = api_key
        self.url = ws_url(base_url)
        self.channels = list(channels or [])
        self.session = session
        self.include_control = include_control
        self.idle_timeout = idle_timeout
        self.max_backoff = max_backoff
        self.max_reconnects = max_reconnects
        self._connect_factory = connect
        self._ws = None
        self._closed = False
        self.stream_id: str | None = None
        self.last_seq: int | None = None
        self.reconnects = 0
        self.auth_info: dict = {}
        self.last_error: dict | None = None
        self.resumes: list[dict] = []

    def __repr__(self) -> str:
        return f"Stream(url={self.url!r}, channels={self.channels!r}, last_seq={self.last_seq!r})"

    async def __aenter__(self) -> "Stream":
        await self._open(first=True)
        return self

    async def __aexit__(self, *exc) -> None:
        await self.close()

    async def close(self) -> None:
        self._closed = True
        ws, self._ws = self._ws, None
        if ws is not None:
            try:
                await ws.close()
            except Exception:  # noqa: BLE001
                pass

    async def _send(self, msg: dict) -> None:
        await self._ws.send(json.dumps(msg))

    async def subscribe(self, channels: list[str]) -> None:
        self.channels = sorted(set(self.channels) | set(channels))
        await self._send({"op": "subscribe", "channels": list(channels), **({"session": self.session}
                                                                             if self.session else {})})

    async def unsubscribe(self, channels: list[str]) -> None:
        self.channels = [c for c in self.channels if c not in set(channels)]
        await self._send({"op": "unsubscribe", "channels": list(channels), **({"session": self.session}
                                                                               if self.session else {})})

    async def _open(self, first: bool) -> None:
        factory = self._connect_factory or _default_connect()
        self._ws = await factory(self.url)
        await self._send({"op": "auth", "key": self._key})
        reply = await self._control_reply("auth")
        self.auth_info = reply
        new_stream = reply.get("stream")
        if first or self.last_seq is None:
            self.last_seq = int(reply.get("seq") or 0)
            self.stream_id = new_stream
            if self.channels:
                msg = {"op": "subscribe", "channels": self.channels}
                if self.session:
                    msg["session"] = self.session
                await self._send(msg)
                await self._control_reply("subscribed")  # surfaces PLAN_LIMIT and bad channel names now
        else:
            # Missed frames arrive before the "resumed" frame, so do not wait for it here.
            msg = {"op": "resume", "since_seq": self.last_seq, "channels": self.channels}
            if self.session:
                msg["session"] = self.session
            if self.stream_id:
                msg["stream"] = self.stream_id
            await self._send(msg)
            self.stream_id = new_stream

    async def _control_reply(self, op: str, timeout: float = 10.0) -> dict:
        while True:
            raw = await asyncio.wait_for(self._ws.recv(), timeout=timeout)
            msg = json.loads(raw)
            if msg.get("op") == op:
                if msg.get("ok") is False:
                    raise from_response(400, msg)
                return msg
            if msg.get("op") == "error":
                self.last_error = msg
                raise from_response(_status_for(msg.get("code")), msg)
            if msg.get("op") == "ping":
                await self._send({"op": "pong"})

    async def _reconnect(self, close_code: int | None) -> None:
        if close_code in FATAL_CLOSE:
            err = self.last_error or {"code": FATAL_CLOSE[close_code].__name__}
            raise from_response(_status_for(err.get("code")), err)
        attempt = 0
        while not self._closed:
            if self.max_reconnects is not None and self.reconnects >= self.max_reconnects:
                raise SimvexError("WS_CLOSED", "gave up reconnecting", body=self.last_error or {})
            self.reconnects += 1
            delay = min(self.max_backoff, 0.5 * (2 ** attempt)) * (1 + random.uniform(0, 0.25))
            await asyncio.sleep(delay if attempt else random.uniform(0.05, 0.3))
            attempt += 1
            try:
                await self._open(first=False)
                return
            except (Unauthorized, PlanLimit, SecretRejected, NotYet):
                raise
            except Exception:  # noqa: BLE001 - network trouble: try again
                continue

    def __aiter__(self) -> "Stream":
        return self

    async def __anext__(self) -> dict:
        from websockets.exceptions import ConnectionClosed  # the ws extra is installed when we got here
        while True:
            if self._closed:
                raise StopAsyncIteration
            try:
                raw = await asyncio.wait_for(self._ws.recv(), timeout=self.idle_timeout)
            except asyncio.TimeoutError:
                await self._drop()
                await self._reconnect(None)
                continue
            except ConnectionClosed as e:
                if self._closed:
                    raise StopAsyncIteration
                rcvd = getattr(e, "rcvd", None)
                await self._reconnect(getattr(rcvd, "code", None))
                continue
            msg = json.loads(raw)
            op = msg.get("op")
            if op == "ping":
                await self._send({"op": "pong"})
                continue
            if op == "event":
                seq = msg.get("seq")
                if isinstance(seq, int):
                    if self.last_seq is not None and seq <= self.last_seq:
                        continue  # already delivered
                    self.last_seq = seq
                return msg
            if op == "error":
                self.last_error = msg
            if op == "resumed":
                self.resumes.append(msg)
                if msg.get("complete") is False:
                    return msg
            if self.include_control:
                return msg

    async def _drop(self) -> None:
        ws, self._ws = self._ws, None
        if ws is not None:
            try:
                await ws.close()
            except Exception:  # noqa: BLE001
                pass


def _status_for(code: str | None) -> int:
    return {"UNAUTHORIZED": 401, "PLAN_LIMIT": 403, "NOT_YET": 403, "SECRET_REJECTED": 400,
            "RATE_LIMITED": 429}.get(code or "", 400)
