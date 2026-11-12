<p align="center"><img src="https://raw.githubusercontent.com/Simvex/Simvex/main/assets/banner.jpg" alt="Simvex. Lose it on paper first." width="100%"></p>

# Example bots

Four small bots on Simvex paper trading, MIT licensed. They use the [Python client](https://github.com/Simvex/simvex-python) and print what they did and the disclaimer. They are starting points to test and change, not strategies to trust: a negative result is a normal and useful outcome.

> **Never send a private key or seed phrase.** These bots need only a `dr_` API key in `SIMVEX_API_KEY`.

```bash
pip install "simvex-client[ws] @ git+https://github.com/Simvex/simvex-python"
export SIMVEX_API_KEY=dr_...                 # send /key to t.me/SimvexApiBot
export SIMVEX_BASE_URL=https://simvex.xyz    # the default
```

| Example | What it shows | Run |
|---|---|---|
| [momentum_bot](momentum_bot/momentum_bot.py) | New pairs that pass the rug check and are rising over their last snapshots: market buy with an idempotent `client_order_id`, then a `tp_sl` order (take profit, stop loss, trailing stop) on each position | `python momentum_bot/momentum_bot.py --steps 3 --interval 20` |
| [rug_avoider](rug_avoider/rug_avoider.py) | Reads each token's full rug report and enters only strict passes; sets `rug_block=strict` so the server refuses failing tokens too, and shows one `RUG_BLOCKED` on purpose | `python rug_avoider/rug_avoider.py` |
| [compat_switch](compat_switch/compat_switch.py) | A bot written in plain `httpx` against the request formats of a widely used quote API and a widely used trade API (format only, no affiliation); only `QUOTE_BASE` and `TRADE_BASE` point it at Simvex. The live URLs are comments, never called | `python compat_switch/compat_switch.py` |
| [replay_backtest](replay_backtest/replay_backtest.py) | The unchanged momentum bot inside a replay session: every call carries `X-Replay-Session`, the clock moves with `advance`, the result is deterministic for the same window | `python replay_backtest/replay_backtest.py --minutes 60 --step 120` |

Replay needs plan hours (trainee or higher) or fuel; the momentum and rug examples run on the free plan, slowly (30 calls per minute).

## What a run looks like

`rug_avoider.py` exactly as it ships, run on Nov 6 against a Simvex server reading the live mainnet market. It read ten new pairs in about 0.4 s, skipped all of them with a reason for each, then sent one order on purpose so you can see the server refuse it.

```text
rug avoider on http://127.0.0.1:8410, bot 'default', level strict (paper trading)
set rug_block=strict: the server now refuses orders on tokens that fail it
  31RmVv2Z: skipped, TOP10_CONCENTRATION: top 10 wallets hold 88% (limit 25%); POOL_TOO_YOUNG: pool age 75s (min 300s)
  DCVcWuRP: skipped, LIQ_TOO_LOW: liquidity $14.3 (min $20,000); POOL_TOO_YOUNG: pool age 77s (min 300s); PRICE_IMPACT_HIGH: price impact 19.21% (limit 2%)
  6Piwxrx4: skipped, LIQ_TOO_LOW: liquidity $0 (min $20,000); POOL_TOO_YOUNG: pool age 77s (min 300s); PRICE_IMPACT_HIGH: price impact 2.17% (limit 2%)
  4FuUoZhX: skipped, POOL_TOO_YOUNG: pool age 79s (min 300s)
  6fxBSrfF: skipped, LIQ_TOO_LOW: liquidity $2,502.51 (min $20,000); POOL_TOO_YOUNG: pool age 79s (min 300s); PRICE_IMPACT_HIGH: price impact None% (limit 2%)
  CAfRfn8n: skipped, LIQ_TOO_LOW: liquidity $1.46 (min $20,000); POOL_TOO_YOUNG: pool age 80s (min 300s); PRICE_IMPACT_HIGH: price impact 22.94% (limit 2%)
  8VuppE9F: skipped, LIQ_TOO_LOW: liquidity $0 (min $20,000); POOL_TOO_YOUNG: pool age 85s (min 300s)
  6RUdxAF2: skipped, LIQ_TOO_LOW: liquidity $1.75 (min $20,000); POOL_TOO_YOUNG: pool age 88s (min 300s); PRICE_IMPACT_HIGH: price impact 13.65% (limit 2%)
  GorFDcjP: skipped, LIQ_TOO_LOW: liquidity $115.42 (min $20,000); POOL_TOO_YOUNG: pool age 91s (min 300s); PRICE_IMPACT_HIGH: price impact 3.16% (limit 2%)
  AHaDJaEs: skipped, LIQ_TOO_LOW: liquidity $0 (min $20,000); POOL_TOO_YOUNG: pool age 99s (min 300s); PRICE_IMPACT_HIGH: price impact 2.79% (limit 2%)
scanned 10: 0 pass, 10 fail
  guard check on 31RmVv2Z: refused by the server with RUG_BLOCKED, as intended
result: 0 filled buy(s), 2 open position(s)
Paper trading result. Real fills may differ.
```

## What the codes mean

| Code | Where | Meaning |
|---|---|---|
| `TOP10_CONCENTRATION` | rug report | the top 10 wallets hold more than the limit |
| `LIQ_TOO_LOW` | rug report | the pool holds less than the minimum liquidity |
| `POOL_TOO_YOUNG` | rug report | the pool is younger than the minimum age |
| `PRICE_IMPACT_HIGH` | rug report | this order size would move the price past the limit |
| `RUG_BLOCKED` | order | `rug_block` is on and the token fails it, so the server refuses the order |
| `FILL_FAILED_SLIPPAGE` | order | the fresh quote at confirmation moved past your `slippage_bps` |
| `FILL_FAILED_LIQ` | order | liquidity was pulled before confirmation; principal returned |

The full list is in the [docs](https://github.com/Simvex/docs).

Paper trading result. Real fills may differ.

More: [Python client](https://github.com/Simvex/simvex-python) · [TypeScript client](https://github.com/Simvex/simvex-js) · [docs](https://github.com/Simvex/docs) · [simvex.xyz](https://simvex.xyz)
