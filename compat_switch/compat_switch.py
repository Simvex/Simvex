"""Compat switch: a bot written against the request formats of a widely used swap quote API and a widely used
memecoin trade API, pointed at Simvex paper trading by changing only two base URLs.

Paper trading on Simvex (MIT example). Format compatibility only, no affiliation.

    export SIMVEX_API_KEY=dr_...
    python examples/compat_switch/compat_switch.py

The trading code below uses plain httpx and the two formats as documented. Nothing in it knows about Simvex except
QUOTE_BASE and TRADE_BASE. Read docs/compat-spec.md (the "differs" list) before switching them back.
"""
from __future__ import annotations

import argparse
import os
import sys

import httpx

from simvex_client import DISCLAIMER, Client, SimvexError

SIMVEX = os.environ.get("SIMVEX_BASE_URL", "http://127.0.0.1:8410").rstrip("/")

# ---- the only lines that change between paper and live -------------------------------------------------------
# Live (format only, no affiliation; never called by this example):
#   QUOTE_BASE = "https://lite-api.jup.ag/swap/v1"      # Jupiter Metis Swap API v1 quote format
#   TRADE_BASE = "https://pumpportal.fun"               # PumpPortal Lightning trade format (key in ?api-key=)
QUOTE_BASE = f"{SIMVEX}/compat/quote/v1"
TRADE_BASE = f"{SIMVEX}/compat/trade"
# Paper: the Simvex dr_ key, sent as a header. Live: that service's own key. Never send a live key to Simvex.
AUTH = {"Authorization": f"Bearer {os.environ.get('SIMVEX_API_KEY', '')}"}
# -----------------------------------------------------------------------------------------------------------------

SOL_MINT = "So11111111111111111111111111111111111111112"


def quote_buy(http: httpx.Client, mint: str, sol: float, slippage_bps: int = 300) -> dict:
    r = http.get(f"{QUOTE_BASE}/quote", params={"inputMint": SOL_MINT, "outputMint": mint,
                                                "amount": int(sol * 1e9), "slippageBps": slippage_bps}, headers=AUTH)
    return {"status": r.status_code, **r.json()}


def trade(http: httpx.Client, action: str, mint: str, amount, *, in_sol: bool, slippage_pct: int = 10) -> dict:
    body = {"action": action, "mint": mint, "amount": amount, "denominatedInSol": "true" if in_sol else "false",
            "slippage": slippage_pct, "priorityFee": 0.00001, "pool": "auto"}
    r = http.post(f"{TRADE_BASE}/api/trade", json=body, headers=AUTH)
    return {"status": r.status_code, **r.json()}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--mint", help="token to trade; default: the newest one that passes the rug check")
    ap.add_argument("--size", type=float, default=0.05, help="SOL")
    a = ap.parse_args(argv)

    sdk = Client()  # used only to pick a token and to read the paper book afterwards
    mint = a.mint
    if not mint:
        tokens = [t for t in sdk.tokens_new(limit=20).get("tokens", []) if (t.get("rug") or {}).get("passed")]
        if not tokens:
            print("no token passes the rug check right now; nothing to trade")
            print(DISCLAIMER)
            return 0
        mint = tokens[0]["mint"]
    print(f"compat switch: quote base {QUOTE_BASE}, trade base {TRADE_BASE} (paper trading)")

    with httpx.Client(timeout=30) as http:
        q = quote_buy(http, mint, a.size)
        if q["status"] == 200:
            print(f"  quote {a.size} SOL -> {q.get('outAmount')} raw units of {mint[:8]}, "
                  f"price impact {float(q.get('priceImpactPct') or 0) * 100:.3f}%")
        else:
            print(f"  quote refused: {q.get('error')} ({q.get('code')})")
        t = trade(http, "buy", mint, a.size, in_sol=True)
        if t["status"] == 200:
            d = t.get("dryrun") or {}
            print(f"  trade buy signature {t.get('signature')} (a paper receipt, not a transaction)")
            print(f"  order {d.get('order_id')}: {d.get('status')} {d.get('code') or ''}".rstrip())
        else:
            print(f"  trade refused: {t.get('errors') or t.get('error') or t.get('message_en')} ({t.get('code')})")

    pos = sdk.positions().get("positions", [])
    held = [p for p in pos if p["mint"] == mint]
    print(f"result: {len(held)} open paper position(s) in {mint[:8]}, {len(pos)} in total")
    print(DISCLAIMER)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SimvexError as e:
        print(f"error {e.code}: {e.message} {e.hint}".rstrip())
        print(DISCLAIMER)
        sys.exit(1)
