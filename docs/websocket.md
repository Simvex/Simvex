# WebSocket

`/v1/ws` streams what your bot would otherwise poll for. It opens at step 3 of the launch ladder and needs the trainee plan or higher.

## Connect

Authenticate with the first message, within 10 seconds. A key in the URL is refused.

```json
{"op": "auth", "key": "dr_..."}
```

## Channels

| Channel | What arrives |
|---|---|
| `orders` | your orders as they change state |
| `fills` | every paper fill on your bots |
| `positions` | position changes |
| `tokens.new` | new pairs as the collector starts tracking them |
| `rug.events` | rug report changes, including pools being pulled |
| `prices:{mint}` | the price of one token |

## Never miss a frame

Every data frame has a `seq`. After a reconnect, send

```json
{"op": "resume", "since_seq": 1234}
```

and the server sends what you missed from the last 5 minutes. The server pings every 20 s and closes a connection that stays silent for 60 s. At most 5 open connections per key.

## The launch hour

Step 3 opens the socket an hour before step 4 opens the plans. Between those two steps every key gets the free plan plus a WebSocket with 5 price channels, so nobody waits an hour for a socket. From step 4 the plan table in [limits](limits.md) applies as written.

Both clients speak it: [Python](https://github.com/Simvex/simvex-python) (`pip install "simvex-client[ws] @ git+https://github.com/Simvex/simvex-python"`) and [TypeScript](https://github.com/Simvex/simvex-js) (the global `WebSocket`).

Paper trading result. Real fills may differ.
