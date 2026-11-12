# Changelog

## 0.1.0

- `Client` and `AsyncClient` for every REST endpoint: keys, bots, market data, quotes, orders, positions, fills, decisions, replay, claims, leaderboard, arena.
- `wait_for_order` holds a pending order until its 1.2 s confirmation settles.
- WebSocket stream with `resume` after a reconnect (`[ws]` extra).
- Typed errors: `OrderRejected` and friends carry the server's `code` and `hint`.
- Refuses any key that does not start with `dr_`, so a private key can never be sent by mistake.
- Default base URL `https://simvex.xyz`.
