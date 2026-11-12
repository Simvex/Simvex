# Changelog

## 0.1.0

- `Client` for every REST endpoint, ESM with type definitions, no runtime dependencies (global `fetch` and `WebSocket`, Node 22+ and browsers).
- `waitForOrder` holds a pending order until its 1.2 s confirmation settles.
- WebSocket stream with `resume` after a reconnect.
- Typed errors carry the server's `code` and `hint`.
- Refuses any key that does not start with `dr_`.
- Builds on install from GitHub (`prepare`). Default base URL `https://simvex.xyz`.
