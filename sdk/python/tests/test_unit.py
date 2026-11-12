"""Unit tests with httpx.MockTransport and a fake WebSocket. No server needed: pytest sdk/python/tests"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from simvex_client import (AsyncClient, Client, NotFound, OrderRejected, PlanLimit, RateLimited,  # noqa: E402
                           RetryPolicy, ServerError, SimvexError, Unauthorized)
from simvex_client.ws import Stream, ws_url  # noqa: E402

KEY = "dr_" + "a" * 43


def mk(handler, **kw):
    sleeps: list[float] = []
    c = Client(KEY, "http://test", http_client=httpx.Client(transport=httpx.MockTransport(handler)), **kw)
    c.sleep = sleeps.append
    return c, sleeps


def ok(body=None, **headers):
    return httpx.Response(200, json=body or {"ok": True, "disclaimer": "x"}, headers=headers)


def err(status, code, **extra):
    return httpx.Response(status, json={"code": code, "message_en": code.lower(), "hint": "h", **extra},
                          headers={"Retry-After": "2"} if status == 429 else {})


def test_headers_key_and_repr():
    seen = []

    def h(req):
        seen.append(req)
        return ok()

    c, _ = mk(h)
    c.me()
    r = seen[0]
    assert r.headers["authorization"] == f"Bearer {KEY}" and r.url.path == "/v1/me"
    assert r.headers["user-agent"].startswith("simvex-client-python/")
    assert KEY not in repr(c)
    c.ladder()
    assert "authorization" not in seen[1].headers  # public endpoint


def test_refuses_non_api_key():
    with pytest.raises(ValueError):
        Client("4wBqpZM9xaSheZzJSMawUKKwhdpChKbZ5eu5ky4Vigw9", "http://test")


def test_429_retries_after_retry_after_then_succeeds():
    calls = []

    def h(req):
        calls.append(1)
        return err(429, "RATE_LIMITED", retry_after_sec=2) if len(calls) < 3 else ok({"v": 1})

    c, sleeps = mk(h)
    assert c.me() == {"v": 1}
    assert len(calls) == 3 and len(sleeps) == 2 and all(2 <= s <= 2.6 for s in sleeps)


def test_429_gives_up_with_typed_error():
    c, sleeps = mk(lambda r: err(429, "RATE_LIMITED"), retry=RetryPolicy(max_retries=2))
    with pytest.raises(RateLimited) as e:
        c.me()
    assert e.value.code == "RATE_LIMITED" and e.value.retry_after == 2 and len(sleeps) == 2


def test_5xx_retried_for_get_not_for_plain_post():
    n = {"get": 0, "post": 0}

    def h(req):
        n["get" if req.method == "GET" else "post"] += 1
        return httpx.Response(503, json={"code": "INTERNAL"})

    c, _ = mk(h, retry=RetryPolicy(max_retries=2))
    with pytest.raises(ServerError):
        c.me()
    with pytest.raises(ServerError):
        c.create_bot("b2")
    assert n == {"get": 3, "post": 1}


def test_place_order_gets_client_order_id_and_is_retried():
    bodies = []

    def h(req):
        bodies.append(json.loads(req.content))
        return httpx.Response(502, json={}) if len(bodies) == 1 else ok({"order_id": "o1", "status": "pending"})

    c, _ = mk(h)
    out = c.place_order(mint="M" * 32, side="buy", amount=0.1)
    assert out["order_id"] == "o1" and len(bodies) == 2
    assert bodies[0]["client_order_id"] == bodies[1]["client_order_id"] and bodies[0]["client_order_id"].startswith("sdk-")
    assert bodies[0]["amount_unit"] == "sol" and bodies[0]["type"] == "market"


def test_network_error_retried_then_raised():
    def h(req):
        raise httpx.ConnectError("refused")

    c, sleeps = mk(h, retry=RetryPolicy(max_retries=1))
    with pytest.raises(SimvexError) as e:
        c.me()
    assert e.value.code == "NETWORK" and len(sleeps) == 1


def test_pacing_when_remaining_is_zero(monkeypatch):
    c, sleeps = mk(lambda r: ok(headers={"X-RateLimit-Limit": "30", "X-RateLimit-Remaining": "0"}) if False else
                   httpx.Response(200, json={}, headers={"X-RateLimit-Limit": "30", "X-RateLimit-Remaining": "0",
                                                         "X-Plan": "free", "X-Data-Delay-Sec": "30"}))
    c.me()
    c.me()
    assert c.rate.limit == 30 and c.rate.remaining == 0 and c.rate.plan == "free" and c.rate.data_delay_sec == 30
    assert sleeps and 1.5 < sleeps[0] <= 2.0  # 60 / 30 seconds for one token


@pytest.mark.parametrize("status,code,cls", [(403, "PLAN_LIMIT", PlanLimit), (409, "FILL_FAILED_LIQ", OrderRejected),
                                             (404, "NO_DATA", NotFound), (401, "UNAUTHORIZED", Unauthorized)])
def test_typed_errors(status, code, cls):
    c, _ = mk(lambda r: err(status, code, available={"from": 1, "to": 2}))
    with pytest.raises(cls) as e:
        c.me()
    assert e.value.code == code and e.value.status == status and e.value.hint == "h"
    assert e.value.body["available"] == {"from": 1, "to": 2}


def test_replay_helper_binds_header_and_advances():
    seen = []

    def h(req):
        seen.append(req)
        if req.url.path == "/v1/replays":
            return ok({"session_id": "rs_1", "clock_ts": 100.0})
        if req.url.path.endswith("/advance"):
            return ok({"session_id": "rs_1", "clock_ts": 160.0})
        return ok({"positions": []})

    c, _ = mk(h)
    rp = c.replay(100, 200)
    rp.client.positions()
    assert seen[1].headers["x-replay-session"] == "rs_1"
    assert rp.advance(60)["clock_ts"] == 160.0 and rp.clock == 160.0
    assert "x-replay-session" not in seen[2].headers  # the advance call itself is not in the session
    c.positions()
    assert "x-replay-session" not in seen[3].headers  # the parent client is unchanged


def test_compat_bot_header():
    seen = []
    c, _ = mk(lambda r: seen.append(r) or ok())
    c.compat_trade({"action": "buy", "mint": "M" * 32, "amount": 0.1, "denominatedInSol": "true"}, bot="b1")
    assert seen[0].headers["x-dryrun-bot"] == "b1" and seen[0].url.path == "/compat/trade/api/trade"


def test_async_client_retries():
    calls = []

    def h(req):
        calls.append(1)
        return err(429, "RATE_LIMITED") if len(calls) == 1 else ok({"v": 2})

    async def run():
        async with AsyncClient(KEY, "http://test",
                               http_client=httpx.AsyncClient(transport=httpx.MockTransport(h))) as c:
            slept = []

            async def fake_sleep(s):
                slept.append(s)

            c.sleep = fake_sleep
            out = await c.me()
            return out, slept

    out, slept = asyncio.run(run())
    assert out == {"v": 2} and len(slept) == 1 and slept[0] >= 2


def test_ws_url():
    assert ws_url("https://api.example.test") == "wss://api.example.test/v1/ws"
    assert ws_url("http://127.0.0.1:8410") == "ws://127.0.0.1:8410/v1/ws"


class FakeWs:
    """Scripted server: answers auth, subscribe and resume like /v1/ws."""

    def __init__(self, script):
        self.sent: list[dict] = []
        self.script = list(script)
        self.inbox: asyncio.Queue = asyncio.Queue()

    async def send(self, text):
        msg = json.loads(text)
        self.sent.append(msg)
        if msg["op"] == "auth":
            await self.inbox.put(json.dumps({"op": "auth", "ok": True, "stream": "st1", "seq": 5}))
        elif msg["op"] == "subscribe":
            await self.inbox.put(json.dumps({"op": "subscribed", "channels": msg["channels"], "seq": 5}))
            for item in self.script:
                await self.inbox.put(item)

    async def recv(self):
        item = await self.inbox.get()
        if isinstance(item, Exception):
            raise item
        return item

    async def close(self):
        pass


def test_ws_reconnect_resumes_from_last_seq_and_drops_duplicates():
    from websockets.exceptions import ConnectionClosedError

    ev = lambda seq: json.dumps({"op": "event", "seq": seq, "channel": "orders", "data": {"n": seq}})  # noqa: E731
    first = FakeWs([ev(6), json.dumps({"op": "ping", "seq": 6}), ev(7), ConnectionClosedError(None, None)])
    second = FakeWs([])
    conns = [first, second]

    async def connect(url):
        return conns.pop(0)

    async def run():
        got = []
        s = Stream(KEY, "http://test", channels=["orders"], connect=connect, max_reconnects=3)
        async with s:
            got.append(await s.__anext__())
            got.append(await s.__anext__())
            # second connection: replay 7 (duplicate) and 8, then resumed
            await second.inbox.put(json.dumps({"op": "auth", "ok": True, "stream": "st1", "seq": 8}))
            task = asyncio.create_task(s.__anext__())
            await asyncio.sleep(0.5)
            for item in (ev(7), ev(8)):
                await second.inbox.put(item)
            got.append(await asyncio.wait_for(task, 5))
        return got, s

    got, s = asyncio.run(run())
    assert [g["seq"] for g in got] == [6, 7, 8]
    assert {"op": "pong"} in first.sent
    assert first.sent[0] == {"op": "auth", "key": KEY} and first.sent[1]["op"] == "subscribe"
    resume = [m for m in second.sent if m["op"] == "resume"][0]
    assert resume["since_seq"] == 7 and resume["channels"] == ["orders"] and resume["stream"] == "st1"
    assert s.reconnects == 1
