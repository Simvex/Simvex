"""Rug avoider: read each new token's full rug report and only enter the ones that pass the strict level.

Paper trading on Simvex (MIT example).

    export SIMVEX_API_KEY=dr_...
    python examples/rug_avoider/rug_avoider.py --max-buys 2

What it shows:
  - GET /v1/tokens/{mint} returns rug reports at three levels (loose, normal, strict). Each check has a reason code,
    its value, its limit and a readable sentence, so the bot can say why it skipped a token.
  - The bot also sets rug_block='strict' on itself, so the server refuses an order on a failing token with
    RUG_BLOCKED even if the bot's own filter has a bug. The script tries one such order on purpose to show it.
"""
from __future__ import annotations

import argparse
import sys

from simvex_client import DISCLAIMER, Client, OrderRejected, SimvexError

LEVEL = "strict"


def report_for(c: Client, mint: str) -> dict | None:
    t = c.token(mint)
    if t.get("status") == "tracking_started":
        return None  # a token the server did not follow yet; ask again later
    return t


def why_failed(rep: dict) -> list[str]:
    return [f"{ch['code']}: {ch.get('text_en') or ch.get('text')}" for ch in rep.get("checks", [])
            if not ch.get("passed") and not ch.get("warn_only")]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--max-buys", type=int, default=2)
    ap.add_argument("--size", type=float, default=0.05)
    ap.add_argument("--scan", type=int, default=12, help="how many new tokens to read")
    ap.add_argument("--bot", default="default")
    a = ap.parse_args(argv)

    c = Client()
    print(f"rug avoider on {c.base_url}, bot '{a.bot}', level {LEVEL} (paper trading)")
    c.bot_settings(a.bot, rug_block=LEVEL)
    print(f"set rug_block={LEVEL}: the server now refuses orders on tokens that fail it")

    tokens = c.tokens_new(limit=a.scan).get("tokens", [])
    passed, failed = [], []
    for t in tokens:
        rep_all = report_for(c, t["mint"])
        if rep_all is None:
            print(f"  {t['mint'][:8]}: tracking just started, skipped this round")
            continue
        rep = (rep_all.get("rug_reports") or {}).get(LEVEL)
        if not rep:
            print(f"  {t['mint'][:8]}: no rug data yet, skipped")
            continue
        if rep.get("passed") and not rep_all.get("liq_pulled"):
            passed.append(t)
            print(f"  {t['mint'][:8]} {t.get('symbol') or t.get('name') or ''}: passes {LEVEL}".rstrip())
        else:
            failed.append(t)
            reasons = why_failed(rep)[:3] or (["liquidity pulled"] if rep_all.get("liq_pulled") else ["failed"])
            print(f"  {t['mint'][:8]}: skipped, " + "; ".join(reasons))

    print(f"scanned {len(tokens)}: {len(passed)} pass, {len(failed)} fail")
    bought = 0
    for t in passed[: a.max_buys]:
        try:
            o = c.place_order(bot=a.bot, mint=t["mint"], side="buy", amount=a.size, slippage_bps=500,
                              client_order_id=f"rug-{t['mint'][:16]}")
            done = c.wait_for_order(o["order_id"], bot=a.bot)
            print(f"  buy {t['mint'][:8]} {a.size} SOL: {done['status']} {done.get('code') or ''}".rstrip())
            bought += done["status"] == "filled"
        except OrderRejected as e:
            print(f"  buy {t['mint'][:8]} refused: {e.code} ({e.hint or e.message})")

    if failed:  # show the server-side guard: this order is meant to be refused
        t = failed[0]
        try:
            o = c.place_order(bot=a.bot, mint=t["mint"], side="buy", amount=a.size,
                              client_order_id=f"rugtest-{t['mint'][:16]}")
            done = c.wait_for_order(o["order_id"], bot=a.bot)
            print(f"  guard check on {t['mint'][:8]}: {done['status']} {done.get('code') or ''}".rstrip())
        except OrderRejected as e:
            print(f"  guard check on {t['mint'][:8]}: refused by the server with {e.code}, as intended")

    pos = c.positions(bot=a.bot).get("positions", [])
    print(f"result: {bought} filled buy(s), {len(pos)} open position(s)")
    print(DISCLAIMER)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SimvexError as e:
        print(f"error {e.code}: {e.message} {e.hint}".rstrip())
        print(DISCLAIMER)
        sys.exit(1)
