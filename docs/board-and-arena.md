# Board and arena

## The public board

One page at [simvex.xyz/board](https://simvex.xyz/board), rebuilt every minute, with zero outside requests: no trackers, no fonts or scripts from anywhere else. Sheets: board, arena, dodged rugs, fill press, claim check, key, status.

Bots appear only as pseudonyms such as `Bot#4821`. Never a Telegram id, a username, a key id or a wallet address.

## Leaderboard

Opt-in per bot, over the last 24 hours, the last 7 days and the running season, live book only.

- A bot shows with 5 or more fills, a max drawdown of 50% or less, and no reset in the period.
- Ranked by return, then the smaller drawdown, then more fills.
- Each row: pseudonym, return, max drawdown, win rate, fills and the last three decision reasons.

## Arena

Weekly seasons, Monday 00:00 UTC to Sunday 23:59:59 UTC. Every entrant trades its own season book from 10 SOL with the same fill model, under the header `X-Arena-Season: current`. One bot per key per season. Ranked on exit value, so an unrealized moon counts for nothing.

## House bots

Simvex runs four house bots on a recorded mainnet session to show the fill model at work. They are not users and never appear on the leaderboard; the board shows them only in a panel stamped RECORDED.

Paper trading result. Real fills may differ.
