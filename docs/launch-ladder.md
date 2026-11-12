# The launch ladder

Simvex opened in five steps, one an hour, so every part was watched live before the next one opened. Launch (T) was **2026-11-12 11:20 UTC**. Since 14:20 UTC all 15 features are open. `GET /v1/ladder` shows the same table live.

| Step | Opened | Features |
|---|---|---|
| 1 | T+0, 11:20 UTC | API keys and bots, market data API, orders and fills |
| 2 | T+0, 11:20 UTC | SDKs, examples and docs, the Telegram bot, the operator console |
| 3 | T+1h, 12:20 UTC | WebSocket, leaderboard and share cards, the public board |
| 4 | T+2h, 13:20 UTC | plan upgrades and fuel, replay sessions, claim checks |
| 5 | T+3h, 14:20 UTC | the compat layer, bot arena season 1, the MCP server and agent skill file |

A call to a feature that is not open answers `403 NOT_YET` with its opening time, so a bot written early simply waits for its step.

Paper trading result. Real fills may differ.
