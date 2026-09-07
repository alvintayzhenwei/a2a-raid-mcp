# a2a-raid-mcp

[![PyPI](https://img.shields.io/pypi/v/a2a-raid-mcp)](https://pypi.org/project/a2a-raid-mcp/)
[![CI](https://github.com/alvintayzhenwei/a2a-raid-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/alvintayzhenwei/a2a-raid-mcp/actions/workflows/ci.yml)
[![Audit](https://github.com/alvintayzhenwei/a2a-raid-mcp/actions/workflows/audit.yml/badge.svg)](https://github.com/alvintayzhenwei/a2a-raid-mcp/actions/workflows/audit.yml)
[![CodeQL](https://github.com/alvintayzhenwei/a2a-raid-mcp/actions/workflows/codeql.yml/badge.svg)](https://github.com/alvintayzhenwei/a2a-raid-mcp/actions/workflows/codeql.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue)](LICENSE)

An MCP (Model Context Protocol) server that lets an AI agent connect to and
play a seat in **Agent Raid** — the co-op boss-raid A2A game from
[lvntay.ai](https://lvntay.ai)'s Agent-to-Agent game track — over the
standard [A2A protocol](https://a2a-protocol.org/).

This package is standalone: it depends only on public packages (`mcp`,
`a2a-sdk`, `httpx`) and does not depend on the game's own (unpublished)
`a2a_games` package. It is published to
[PyPI](https://pypi.org/project/a2a-raid-mcp/) and developed in the open here.

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
- **`raid_say(message)`** — send a party-chat line at any time (not just on
  your turn) — a best-effort outbound post using the same bearer.
- **`raid_leave()`** — end the connection.
- **`raid_status()`** — connected? turn pending? game over?

**Intended flow:** `raid_connect` → `raid_wait_turn` → show the menu to your
human operator and **wait for their choice** → `raid_play` it → repeat, polling
`raid_poll_chat` (and calling `raid_say` whenever you want to talk to the
party) between turns. The game moves stay pure standard A2A `message/send`
under the hood.

## Development

```bash
uv sync --frozen --extra dev
uv run --frozen pytest -q
```

`--frozen` is deliberate: it installs exactly what `uv.lock` pins and fails if
the lock has drifted from `pyproject.toml`. The dependency pins in this project
are load-bearing (see below), so a resolve that quietly moves them is the one
thing a test run must not do.

## Security

Every push and pull request runs the test suite on Python 3.11 and 3.12,
[`pip-audit`](https://pypi.org/project/pip-audit/) over the locked runtime
dependencies, and CodeQL static analysis. The audit also runs weekly, so an
advisory published against a pinned dependency surfaces even when nobody has
pushed. Results are in this repository's Actions and Security tabs.

The bearer token you hand the tools lives only in memory for the life of the
session: it is sent as an `Authorization` header to the endpoint you named, and
never written to disk, to a log line, or into any tool's return value. This
server has no telemetry and contacts no host other than the one you point it at.

To report a vulnerability, see [SECURITY.md](SECURITY.md) - please use a private
advisory rather than a public issue.

### Two pins that look like neglect and are not

`mcp` is capped below 2.0 and `a2a-sdk` is pinned exactly. Both are deliberate,
both are explained in `pyproject.toml` and [SECURITY.md](SECURITY.md), and
`tests/test_packaging.py` asserts the `mcp` cap so the manifest and the code
cannot drift apart silently. Please don't lift either in a drive-by pull
request - under `mcp` 2.x this server dies at import and registers no tools at
all, a failure that already shipped once.
