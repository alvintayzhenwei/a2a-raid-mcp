# Changelog

All notable changes to `a2a-raid-mcp` are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.3] - 2026-09-07

### Added
- A `Publish` workflow using PyPI **trusted publishing**: a published GitHub
  Release builds, tests and uploads the wheel via a short-lived OIDC token, so no
  long-lived PyPI API token is stored in this repository.

### Changed
- Maintainer contact is `alvintay1987@gmail.com` (was a work address that is not
  where anyone should reach this project).
- `a2a-sdk` pinned `==1.1.2` (was `1.1.0`) and `mcp` locked to 1.29.1, both via
  reviewed Dependabot pull requests with the suite green on 3.11 and 3.12. The
  `mcp<2` cap is unchanged and still enforced by `tests/test_packaging.py`.

### Changed
- Development moved to its own repository,
  [alvintayzhenwei/a2a-raid-mcp](https://github.com/alvintayzhenwei/a2a-raid-mcp).
  The package used to live in a subdirectory of the closed source of
  [lvntay.ai](https://lvntay.ai), so nobody could read the code they were being
  asked to `uvx` — the source, its history, its tests and its dependency audits
  are all public now. The package itself is unchanged: same name, same PyPI
  project, same tools.
- Continuous integration now runs the test suite on Python 3.11 and 3.12,
  `pip-audit` over the locked runtime dependencies (also weekly, so an advisory
  published against a pinned dependency surfaces without a push), and CodeQL
  static analysis.

### Security
- Locked `cryptography` 49.0.0 -> 50.0.1. 49.0.0 is affected by PYSEC-2026-3552;
  it reaches this package transitively through `a2a-sdk`. Found by the new
  `pip-audit` job on its first run, which is the point of having one.

## [0.1.2] - 2026-09-01

### Fixed
- **`uvx a2a-raid-mcp` was dead on arrival.** The manifest asked for `mcp>=1.12`
  with no upper bound, and mcp 2.0 renamed `mcp.server.fastmcp.FastMCP` to
  `mcp.server.mcpserver.MCPServer` and deleted the old path — so once 2.x
  shipped, every fresh resolve picked it and the server died at import with
  `ModuleNotFoundError: No module named 'mcp.server.fastmcp'`, registering no
  tools at all. `mcp` is now capped `<2`, which is what the manifest already
  did for `a2a-sdk` and had simply failed to apply to itself. Migrating to mcp
  2.x is a deliberate follow-up: move the floor to `>=2` rather than widening
  the range.
- `tests/test_packaging.py` asserts the cap and ties it to the import the server
  actually uses, so changing the code and forgetting the manifest (or the
  reverse) fails in CI instead of in a stranger's terminal. The existing suites
  could not have caught the original break: they run against a locked dev
  environment that already had mcp 1.x, and only a fresh resolve picks up a new
  major — which is why the test checks published metadata, not the import.

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

[0.1.3]: https://pypi.org/project/a2a-raid-mcp/0.1.3/
[0.1.2]: https://pypi.org/project/a2a-raid-mcp/0.1.2/
[0.1.1]: https://pypi.org/project/a2a-raid-mcp/0.1.1/
[0.1.0]: https://pypi.org/project/a2a-raid-mcp/0.1.0/
