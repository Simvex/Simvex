# Examples

Four small bots on Simvex paper trading, MIT licensed. They use the Python SDK in `sdk/python` and print what they did and the disclaimer. They are starting points to test and change, not strategies to trust: a negative result is a normal and useful outcome.

> **Never send a private key or seed phrase.** These bots need only a `dr_` API key in `SIMVEX_API_KEY`.

```bash
pip install "./sdk/python[ws]"
export SIMVEX_API_KEY=dr_...                 # /key in the Telegram bot
export SIMVEX_BASE_URL=http://127.0.0.1:8410
```

| Example | What it shows | Run |
|---|---|---|
| [momentum_bot](momentum_bot/momentum_bot.py) | New pairs that pass the rug check and are rising over their last snapshots: market buy with an idempotent `client_order_id`, then a `tp_sl` order (take profit, stop loss, trailing stop) on each position | `python examples/momentum_bot/momentum_bot.py --steps 3 --interval 20` |
| [rug_avoider](rug_avoider/rug_avoider.py) | Reads each token's full rug report and enters only strict passes; sets `rug_block=strict` so the server refuses failing tokens too, and shows one `RUG_BLOCKED` on purpose | `python examples/rug_avoider/rug_avoider.py` |
| [compat_switch](compat_switch/compat_switch.py) | A bot written in plain `httpx` against the request formats of a widely used quote API and a widely used trade API (format only, no affiliation); only `QUOTE_BASE` and `TRADE_BASE` point it at Simvex. The live URLs are comments, never called | `python examples/compat_switch/compat_switch.py` |
| [replay_backtest](replay_backtest/replay_backtest.py) | The unchanged momentum bot inside a replay session: every call carries `X-Replay-Session`, the clock moves with `advance`, the result is deterministic for the same window | `python examples/replay_backtest/replay_backtest.py --minutes 60 --step 120` |

Replay needs plan hours (trainee or higher) or fuel; the momentum and rug examples run on the free plan, slowly (30 calls per minute).

## Run all four on a local server

```bash
.venv/Scripts/python scripts/run_examples.py
```

The script starts a local server on port 8414 with the recorded market data, issues a key per example, runs each one, runs the TypeScript SDK tests, and reports pass or fail for each.

Paper trading result. Real fills may differ.
