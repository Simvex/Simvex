"""Replay backtest: run the unchanged momentum bot inside a replay session over recorded market data.

Paper trading on Simvex (MIT example).

    export SIMVEX_API_KEY=dr_...            # replay needs plan hours (trainee or higher) or fuel
    python examples/replay_backtest/replay_backtest.py --minutes 60 --step 120

How it works: POST /v1/replays creates a session; `rp.client` sends X-Replay-Session on every call, so the same
MomentumBot code reads the past market and trades in a separate paper book. The bot never sees data after the
session clock (the server answers LOOKAHEAD). Each loop runs one bot step, then advances the clock, which also
confirms pending orders and triggers take-profit and stop-loss. The same window and rules give the same result.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from simvex_client import DISCLAIMER, Client, FuelRequired, NotFound, SimvexError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "momentum_bot"))
from momentum_bot import MomentumBot  # noqa: E402 - the same bot, unchanged


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--minutes", type=float, default=60, help="window length in market minutes")
    ap.add_argument("--step", type=float, default=120, help="market seconds between bot steps")
    ap.add_argument("--start", type=float, help="window start (unix seconds); default: the last recorded window")
    ap.add_argument("--min-move", type=float, default=3.0)
    a = ap.parse_args(argv)

    c = Client()
    rng = c.replay_range()
    avail = rng.get("available") or {}
    if not avail.get("from") or not avail.get("to"):
        print("no recorded market data on this server yet; nothing to replay")
        print(DISCLAIMER)
        return 0
    start = a.start if a.start else max(avail["from"], avail["to"] - a.minutes * 60)
    end = min(avail["to"], start + a.minutes * 60)
    print(f"replay backtest on {c.base_url}: window {start:.0f} to {end:.0f} ({(end - start) / 60:.0f} market min), "
          f"{avail.get('tokens')} tokens recorded (paper trading)")
    try:
        rp = c.replay(start, end, speed=0)
    except (FuelRequired, NotFound) as e:
        print(f"replay refused: {e.code} ({e.hint})")
        print(DISCLAIMER)
        return 0
    print(f"session {rp.session_id}, clock {rp.clock:.0f}")

    bot = MomentumBot(rp.client, min_move_pct=a.min_move, log=print)
    steps = 0
    while rp.clock is not None and rp.clock + a.step <= end:
        bot.step()
        rp.advance(a.step)
        steps += 1
    bot.protect_positions()
    out = bot.report()
    start_sol = out["bot"].get("start_sol", 10.0)
    eq = out["bot"].get("equity_sol") or out["bot"].get("cash_sol")
    ret = (eq / start_sol - 1) * 100 if eq and start_sol else 0.0
    print(f"backtest: {steps} steps, return {ret:+.2f}% on {start_sol} paper SOL "
          f"(a negative number is a normal and useful result)")
    try:
        c.finish_replay(rp.session_id)
    except SimvexError:
        pass
    print(DISCLAIMER)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SimvexError as e:
        print(f"error {e.code}: {e.message} {e.hint}".rstrip())
        print(DISCLAIMER)
        sys.exit(1)
