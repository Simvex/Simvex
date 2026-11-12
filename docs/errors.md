# Errors

Every error body is the same shape: a `code`, a plain `message_en`, a `hint` that says what to change, and the disclaimer. Messages never echo what you sent, so a secret pasted by mistake never comes back in a log.

```json
{
  "code": "SECRET_REJECTED",
  "message_en": "The request looked like it carried a private key or seed phrase. It was rejected and not stored.",
  "hint": "Never send a private key or seed phrase. Simvex only needs your dr_ API key.",
  "disclaimer": "Paper trading result. Real fills may differ."
}
```

Your bot branches on `code`. You read the `hint`.

| Code | Meaning |
|---|---|
| `SECRET_REJECTED` | The request looked like it carried a private key or seed phrase. Refused, not stored |
| `UNAUTHORIZED` | Missing or invalid API key |
| `NOT_YET` | The feature opens later; the answer carries `opens_at`, and `GET /v1/ladder` has the schedule |
| `PLAN_LIMIT` | Past your plan's limit |
| `RATE_LIMITED` | `429`: wait for `Retry-After`. A refused call did nothing, so a retry is safe |
| `FUEL_REQUIRED` | `402`: not enough fuel, with the amount needed |
| `QUOTE_UNAVAILABLE` | No quote for this token right now |
| `QUOTE_STALE` | The only quote available was older than the fill model allows |
| `SLIPPAGE_HIGH` | The quote's own price impact is already above your `slippage_bps`; nothing was reserved |
| `MIN_TRADE` | Below 0.01 SOL |
| `BALANCE_LOW` | Not enough paper cash for the amount plus costs |
| `RUG_BLOCKED` | `rug_block` is on for this bot and the token fails it |
| `FILL_FAILED_SLIPPAGE` | The price at confirmation moved past your slippage. Principal returned, transaction cost charged |
| `FILL_FAILED_LIQ` | Liquidity was pulled before confirmation. Everything returned |
| `LOOKAHEAD` | A replay asked for data past its own clock |
| `NO_DATA` | A replay window without recorded data; the answer carries the range that exists |

Paper trading result. Real fills may differ.
