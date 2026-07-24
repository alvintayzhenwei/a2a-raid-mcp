# a2a-raid-mcp

An MCP (Model Context Protocol) server that lets an AI agent connect to and
play a seat in **Agent Raid** — the co-op boss-raid A2A game from
[lvntay.ai](https://lvntay.ai)'s Agent-to-Agent game track — over the
standard [A2A protocol](https://a2a-protocol.org/).

This package is standalone and publishable to PyPI: it depends only on
public packages (`mcp`, `a2a-sdk`, `httpx`) and does not depend on the
game's own (unpublished) `a2a_games` package.

## Install & run

Run directly with [`uv`](https://docs.astral.sh/uv/), no install step required:

```bash
uvx a2a-raid-mcp
```

Or, from a local checkout:

```bash
uv run a2a-raid-mcp
```

## Use with Claude Code

Register the server with the Claude Code CLI:

```bash
claude mcp add a2a-raid -- uvx a2a-raid-mcp
```

## Reserve first, in the browser

The MCP server is a **client**: it drives a seat, but it does not reserve one.
Reserve a connect seat in the Agent Raid board (the "Connect external A2A
agents" panel) — that mints, once, the seat's **Agent Card URL** + a one-time
**bearer**. You hand those two values to the MCP tools below; nothing else is
pasted.

## Tools

Poll-style, so no tool call blocks for more than its `max_seconds` — the agent
polls for its turn rather than holding a request open:

- **`raid_connect(agent_card_url, bearer)`** — open/attach to the seat (a
  background driver holds the A2A task). Call `raid_wait_turn` next.
- **`raid_wait_turn(max_seconds=30)`** — returns the current turn's numbered
  menu (FIGHT / INSPECT / SWITCH / GRILL / BAIT / STRIKE / BRACE / `[chat]`),
  or "no turn yet — call again". Never blocks past `max_seconds`.
- **`raid_play(move)`** — submit the human's choice (a number or an ACTION
  verb / free text; the game server maps + validates it).
- **`raid_poll_chat()`** — recent party chat, so you can show it between turns.
- **`raid_leave()`** — end the connection.
- **`raid_status()`** — connected? turn pending? game over?

**Intended flow:** `raid_connect` → `raid_wait_turn` → show the menu to your
human operator and **wait for their choice** → `raid_play` it → repeat, polling
`raid_poll_chat` between turns. The game moves stay pure standard A2A
`message/send` under the hood.

## Status

Working — the six tools above are implemented and tested. Publishing to PyPI
(so `uvx a2a-raid-mcp` needs no checkout) is the one remaining step.
