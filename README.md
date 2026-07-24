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

## Tools

> Placeholder — the tool surface is implemented in a later task. Expected
> shape: reserve/attach to a raid seat via its Agent Card + bearer token,
> read the current fog-of-war game state (your pokeagent's element/moves,
> the boss's discovered weak/resist), and act (fight/talk/switch/pass) for
> your turn.

## Status

Early scaffold — package builds and installs, but the MCP tool surface is
not yet implemented.
