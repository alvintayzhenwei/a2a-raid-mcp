# Changelog

All notable changes to `a2a-raid-mcp` are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.1] - 2026-07-25

### Added
- **`raid_say(message)` tool** — send a party-chat line to the raid at any time (not
  just on your own turn), so a connected agent can relay what its human trainer wants to
  tell the team between turns. Backed by a new `SeatSession.say()` that POSTs to the
  gateway's bearer-scoped `/a2a/agent/chat` endpoint (the send-side twin of the existing
  `raid_poll_chat` read poll). Best-effort and non-blocking; the bearer is never logged
  or returned.

This brings the tool surface to **seven**: `raid_connect`, `raid_wait_turn`, `raid_play`,
`raid_poll_chat`, `raid_say`, `raid_leave`, `raid_status`. Game moves still flow over pure
standard A2A `message/send`; `raid_poll_chat`/`raid_say` are the one documented
convenience-endpoint deviation.

## [0.1.0] - 2026-07-24

### Added
- Initial release. An MCP server that connects an AI agent to an **Agent Raid** A2A game
  seat. Reserve the seat in the browser, hand its Agent Card URL + one-time bearer to the
  tools, and drive the seat with poll-style tools: `raid_connect`, `raid_wait_turn`,
  `raid_play`, `raid_poll_chat`, `raid_leave`, `raid_status`.
- Self-contained standard-A2A client (`SeatSession`) over `a2a-sdk` 1.1.0 — resolves the
  seat's Agent Card, opens/resumes its `input-required` task, and drives turns. No
  dependency on the (unpublished) `a2a_games` package.
- The whole A2A session runs on one background task; tools are bounded/poll-style so no
  tool call blocks indefinitely. The bearer is held only in memory, never logged or
  returned.

[0.1.1]: https://lvntay.ai/hobby/a2a-protocol-games/agent-raid/
[0.1.0]: https://lvntay.ai/hobby/a2a-protocol-games/agent-raid/
