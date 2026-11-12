"""Momentum bot: enter new pairs whose price is rising, then protect each position with take-profit and stop-loss.

Paper trading on Simvex (MIT example). Run against a server:

    export SIMVEX_API_KEY=dr_...            # from /key in the Telegram bot
    export SIMVEX_BASE_URL=http://127.0.0.1:8410
    python examples/momentum_bot/momentum_bot.py --steps 3 --interval 20

Rules (deliberately simple, tune them before trusting them):
  1. Candidates: the newest pairs that pass the server's normal rug check, have liquidity and are not pulled.
  2. Momentum: price change over the token's last few snapshots. Enter when it is at least --min-move percent.
  3. Entry: a market buy of --size SOL with a fixed client_order_id per token, so a retry never doubles it.
  4. Exit: a tp_sl order on every open position (take profit, stop loss, trailing stop), placed once.

The same class runs inside a replay session (see examples/replay_backtest). A negative result is a normal outcome:
it is what you want to learn before real money goes in.
"""
from __future__ import annotations

import argparse
import sys
import time

from simvex_client import DISCLAIMER, Client, OrderRejected, PlanLimit, SimvexError


class MomentumBot:
    def __init__(self, client: Client, *, bot: str = "default", size_sol: float = 0.05, min_move_pct: float = 3.0,
                 points: int = 6, max_candidates: int = 4, max_positions: int = 2, tp_pct: float = 40.0,
                 sl_pct: float = 20.0, trail_pct: float = 15.0, min_liquidity_sol: float = 5.0, log=print):
        self.c, self.bot = client, bot
        self.size_sol, self.min_move_pct, self.points = size_sol, min_move_pct, points
        self.max_candidates, self.max_positions = max_candidates, max_positions
        self.tp_pct, self.sl_pct, self.trail_pct = tp_pct, sl_pct, trail_pct
        self.min_liquidity_sol = min_liquidity_sol
        self.log = log
        self.entered: set[str] = set()      # mints we already bought (one entry per token)
        self.protected: set[str] = set()    # mints with a tp_sl order attached
        self.stats = {"steps": 0, "candidates": 0, "orders": 0, "filled": 0, "pending": 0, "failed": 0,
                      "refused": 0, "protected": 0}

    # ---- signals ----
    def candidates(self) -> tuple[list[dict], float]:
        resp = self.c.tokens_new(limit=30)
        out = []
        for t in resp.get("tokens", []):
            rug = t.get("rug") or {}
            if not rug.get("passed") or t.get("liq_pulled") or t["mint"] in self.entered:
                continue
            if not t.get("price_sol") or (t.get("liquidity_sol") or 0) < self.min_liquidity_sol:
                continue
            out.append(t)
        return out[: self.max_candidates], float(resp.get("as_of") or time.time())

    def momentum_pct(self, mint: str, as_of: float) -> float | None:
        """Price change over the last `points` snapshots before as_of (works live and in a replay)."""
        rows = self.c.snapshots(mint, start=as_of - 6 * 3600, end=as_of, limit=self.points).get("snapshots", [])
        prices = [r["price_sol"] for r in rows if r.get("price_sol")]
        if len(prices) < 2 or prices[0] <= 0:
            return None
        return (prices[-1] / prices[0] - 1) * 100

    # ---- actions ----
    def protect_positions(self) -> None:
        for p in self.c.positions(bot=self.bot).get("positions", []):
            mint = p["mint"]
            if mint in self.protected or p.get("liq_pulled"):
                continue
            try:
                self.c.place_order(bot=self.bot, mint=mint, side="sell", type="tp_sl", amount=100, amount_unit="pct",
                                   tp_pct=self.tp_pct, sl_pct=self.sl_pct, trail_pct=self.trail_pct,
                                   client_order_id=f"tpsl-{mint[:16]}")
                self.protected.add(mint)
                self.stats["protected"] += 1
                self.log(f"  protect {mint[:8]}: tp +{self.tp_pct}% / sl -{self.sl_pct}% / trail {self.trail_pct}%")
            except OrderRejected as e:
                self.log(f"  protect {mint[:8]} refused: {e.code}")

    def open_positions(self) -> int:
        return len(self.c.positions(bot=self.bot).get("positions", []))

    def step(self) -> None:
        self.stats["steps"] += 1
        self.protect_positions()
        held = self.open_positions()
        cands, as_of = self.candidates()
        self.stats["candidates"] += len(cands)
        self.log(f"step {self.stats['steps']}: {len(cands)} candidate(s), {held} open position(s)")
        for t in cands:
            if held >= self.max_positions:
                break
            mint = t["mint"]
            move = self.momentum_pct(mint, as_of)
            if move is None:
                self.log(f"  skip {mint[:8]}: not enough price history")
                continue
            if move < self.min_move_pct:
                self.log(f"  skip {mint[:8]}: momentum {move:+.1f}% below {self.min_move_pct}%")
                continue
            self.entered.add(mint)
            self.stats["orders"] += 1
            try:
                o = self.c.place_order(bot=self.bot, mint=mint, side="buy", amount=self.size_sol, slippage_bps=500,
                                       client_order_id=f"mom-{mint[:16]}")
            except OrderRejected as e:
                self.stats["refused"] += 1
                self.log(f"  buy {mint[:8]} refused: {e.code} ({e.hint or e.message})")
                continue
            done = self.c.wait_for_order(o["order_id"], bot=self.bot)
            status = done.get("status")
            if status == "filled":
                self.stats["filled"] += 1
                held += 1
                self.log(f"  buy {mint[:8]} {self.size_sol} SOL at momentum {move:+.1f}%: filled")
            elif status == "pending":
                self.stats["pending"] += 1
                self.log(f"  buy {mint[:8]} {self.size_sol} SOL at momentum {move:+.1f}%: pending (confirms as the clock moves)")
                held += 1
            else:
                self.stats["failed"] += 1
                self.log(f"  buy {mint[:8]} at momentum {move:+.1f}%: {status} {done.get('code') or ''}".rstrip())
        self.protect_positions()

    def report(self) -> dict:
        bot = self.c.bot(self.bot)
        fills = self.c.fills(bot=self.bot, limit=20).get("fills", [])
        pos = self.c.positions(bot=self.bot).get("positions", [])
        self.log(f"result: equity {bot.get('equity_sol', bot.get('cash_sol'))} SOL "
                 f"(cash {bot.get('cash_sol')}), {len(pos)} open position(s), {len(fills)} fill(s)")
        for f in fills[:5]:
            self.log(f"  fill {f['side']} {f['mint'][:8]} {f['sol']:.4f} SOL at {f['price_sol']:.3e} SOL/token "
                     f"(cost {f['tx_cost_sol'] + f['priority_fee_sol']:.5f} SOL, order {f['order_id']})")
        self.log(f"stats: {self.stats}")
        return {"bot": bot, "fills": fills, "positions": pos, "stats": self.stats}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--steps", type=int, default=1)
    ap.add_argument("--interval", type=float, default=20.0, help="seconds between steps")
    ap.add_argument("--size", type=float, default=0.05, help="SOL per entry")
    ap.add_argument("--min-move", type=float, default=3.0, help="percent rise over the last snapshots")
    ap.add_argument("--bot", default="default")
    a = ap.parse_args(argv)
    c = Client()
    me = c.me()
    print(f"momentum bot on {c.base_url}, plan {me['plan']['name']}, bot '{a.bot}' (paper trading)")
    bot = MomentumBot(c, bot=a.bot, size_sol=a.size, min_move_pct=a.min_move)
    for i in range(a.steps):
        bot.step()
        if i + 1 < a.steps:
            time.sleep(a.interval)
    bot.report()
    print(DISCLAIMER)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except PlanLimit as e:
        print(f"plan limit: {e.hint}")
        print(DISCLAIMER)
        sys.exit(0)
    except SimvexError as e:
        print(f"error {e.code}: {e.message} {e.hint}".rstrip())
        print(DISCLAIMER)
        sys.exit(1)
