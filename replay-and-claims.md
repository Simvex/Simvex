# Replay and claim checks

## Replay

`POST /v1/replays` opens a session on a recorded window of the market. Then call the same endpoints with the header `X-Replay-Session`: your bot code does not change.

- The clock moves by hand with `advance` (at most 6 hours a call) or runs at up to 60x.
- Asking for data past the clock is refused with `LOOKAHEAD`. A backtest that cannot cheat.
- A window without recorded data answers `404 NO_DATA` with the range that exists.
- Inside a replay every quote is `curve` or `local_cpmm` on the recorded snapshot at the session clock, and the fill model is the same one the live market uses.
- The same window with the same rules gives the same result, run after run.

Replay is counted in market time, the time that passes on the session clock, not the wall clock. Each plan has monthly replay hours; see [limits](limits.md).

## Claim checks

When a post says a bot did 100x overnight, send the stated start balance, the claimed end, the window and the rules to `POST /v1/claims`. Simvex replays that window on its own recorded data with those rules and answers one of three verdicts.

| Verdict | When |
|---|---|
| Reproduced | The replayed return is at least the claimed return minus the larger of 5 points and 20% of the claim |
| Not reproduced under these conditions | Anything lower. A same-conditions replay, not a verdict on the author |
| Not enough data | A window under 5 minutes, less than 80% of its minutes covered by snapshots, or no tokens |

The verdict compares percentages, so the start size does not move it.

Paper trading result. Real fills may differ.
