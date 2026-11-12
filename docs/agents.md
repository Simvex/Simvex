# For agents and drop-in bots

## MCP server

`https://simvex.xyz/mcp` is a Streamable HTTP MCP server with the same key and the same limits as the REST API. Most MCP clients accept a config like this:

```json
{"mcpServers": {"simvex": {"type": "http", "url": "https://simvex.xyz/mcp",
  "headers": {"Authorization": "Bearer ${SIMVEX_API_KEY}"}}}}
```

Tools: `list_new_tokens`, `get_token`, `get_quote`, `place_order`, `cancel_order`, `get_positions`, `get_fills`, `start_replay`, `advance_replay`, `check_claim`, `get_fill_model`. Results are paper trading. Errors come back as tool errors whose text is the REST error body with its `code`.

## Skill file

[simvex.xyz/skill.md](https://simvex.xyz/skill.md) walks a coding agent through the whole flow in one file: getting a key, auth, a first order, reading the fill, replay, MCP and the compat switch. [simvex.xyz/llms.txt](https://simvex.xyz/llms.txt) lists every page an agent should read.

A coding agent cannot create a key by itself: a human sends `/key` to the Telegram bot and puts the key in `SIMVEX_API_KEY`.

## Compat layer: change only the base URL

The compat layer follows the request and response formats of a widely used swap quote API and a widely used memecoin trade API (format only, no affiliation). A bot written against those formats runs on paper with only its base URLs changed:

```text
quote base: https://simvex.xyz/compat/quote/v1     (then GET  .../quote)
trade base: https://simvex.xyz/compat/trade        (then POST .../api/trade)
```

Send the Simvex `dr_` key as a header, never a live service's key and never a private key. [`examples/compat_switch`](../examples/compat_switch/compat_switch.py) shows the switch end to end.

> **Never send a private key or seed phrase.** Requests that look like they carry one are refused with `400 SECRET_REJECTED` and not stored.

Paper trading result. Real fills may differ.
