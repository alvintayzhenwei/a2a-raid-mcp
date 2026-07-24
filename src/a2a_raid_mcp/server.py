"""a2a-raid-mcp: MCP server connecting an AI agent to an Agent Raid A2A game seat.

A2A turns are BLOCKING — a connected seat is only prompted for its next move when
it is actually that seat's turn, and `SeatSession.open()`/`reply()` block (over a
long-held HTTP request) until the next `input-required` turn arrives. An MCP tool
call must never hang for an unbounded time, so this server runs the session on a
BACKGROUND driver task and exposes small, poll-style tools that read/write a bit
of module-level state instead of blocking on the A2A call themselves:

    raid_connect   -> starts the background driver, returns immediately
    raid_wait_turn -> waits (bounded by max_seconds) for the driver to have a
                      pending prompt, and returns it once it does
    raid_play      -> hands a move to the driver and unblocks it
    raid_poll_chat -> best-effort peek at party chat since the last poll
    raid_say       -> best-effort post of an outbound party-chat line
    raid_status    -> a quick snapshot of connection/turn/error state
    raid_leave     -> cancels the driver and closes the session

Only ONE session is tracked per process (module-level globals) — this server is
meant to be run one seat at a time, e.g. via `claude mcp add a2a-raid -- uvx
a2a-raid-mcp` in a single agent session.
"""
from __future__ import annotations

import asyncio
from typing import Any

from mcp.server.fastmcp import FastMCP

from a2a_raid_mcp.a2a_client import DONE, SeatSession

mcp = FastMCP("a2a-raid")

# ---------------------------------------------------------------------------
# Module-level session state (single active session per process).
# ---------------------------------------------------------------------------
_session: Any = None
_driver: "asyncio.Task[None] | None" = None
_pending_prompt: str | None = None
_prompt_event: asyncio.Event = asyncio.Event()
_move_queue: "asyncio.Queue[str]" = asyncio.Queue()
_done: bool = False
_error: str | None = None
_last_seq: int = -1


def _reset_state() -> None:
    """Reset all module-level session state to a fresh, disconnected baseline.
    Best-effort cancels a still-running driver task (fire-and-forget — callers
    that need to be sure the old driver has actually finished, e.g.
    `raid_leave`, await it themselves first)."""
    global _session, _driver, _pending_prompt, _prompt_event, _move_queue
    global _done, _error, _last_seq
    if _driver is not None and not _driver.done():
        _driver.cancel()
    _session = None
    _driver = None
    _pending_prompt = None
    _prompt_event = asyncio.Event()
    _move_queue = asyncio.Queue()
    _done = False
    _error = None
    _last_seq = -1


async def _run_driver() -> None:
    """Drive the seat's whole A2A session in the background: open it, then loop
    reply-for-next-prompt until the task goes terminal. Each iteration blocks on
    `queue.get()` — i.e. on `raid_play` actually being called — so this task
    only ever advances one human-in-the-loop move at a time.

    `session`/`queue` are bound as LOCALS from the module globals at the top of
    this coroutine (not re-read from the globals on every loop iteration): if a
    fresh `raid_connect` installs a NEW `_session`/`_move_queue` while this
    (cancelled) task is still unwinding, a resumed step here must keep talking
    to the session/queue IT was started with, never the new one."""
    global _pending_prompt, _done, _error
    session = _session
    queue = _move_queue
    try:
        prompt = await session.open()
        while prompt != DONE:
            _pending_prompt = prompt
            _prompt_event.set()
            move = await queue.get()
            prompt = await session.reply(move)
        _done = True
        _pending_prompt = None
        _prompt_event.set()
    except asyncio.CancelledError:
        raise
    except Exception as e:  # noqa: BLE001 - surfaced to the caller as a plain string
        _error = f"{type(e).__name__}: {e}"
        _prompt_event.set()


async def _teardown() -> None:
    """Await-cancel the current driver task (if any) and close the current
    session's httpx client (if any), then reset all module-level state to a
    fresh, disconnected baseline. Shared by `raid_connect` (torn down BEFORE a
    fresh connect replaces it — so a 2nd `raid_connect` without a `raid_leave`
    in between never leaks the old session's httpx client or driver task) and
    `raid_leave`."""
    global _driver, _session
    if _driver is not None:
        _driver.cancel()
        try:
            await _driver
        except asyncio.CancelledError:
            pass
        except Exception:  # noqa: BLE001 - the old driver's own error is irrelevant now
            pass
    if _session is not None:
        await _session.close()
    _reset_state()


@mcp.tool()
async def raid_connect(agent_card_url: str, bearer: str) -> str:
    """Connect to your Agent Raid seat over standard A2A.

    Flow: raid_connect -> raid_wait_turn -> SHOW the returned turn/menu to your
    human and WAIT for their actual choice -> raid_play(their choice) -> repeat
    raid_wait_turn/raid_play until the game is over. Call raid_poll_chat between
    turns to catch up on party room-chat. `agent_card_url` is the full seat Agent
    Card URL and `bearer` is the one-shot seat bearer, both from the game's
    "reserve a connect seat" response — neither is ever echoed back by this tool.
    """
    await _teardown()
    global _session, _driver
    _session = SeatSession(agent_card_url, bearer)
    _driver = asyncio.create_task(_run_driver())
    return "Connecting — call raid_wait_turn for your first turn."


@mcp.tool()
async def raid_wait_turn(max_seconds: int = 30) -> str:
    """Wait for your next turn's prompt, bounded by `max_seconds` (default 30) so
    this call never hangs indefinitely. Returns the turn text once it's your
    turn, "the game is over." once the raid ends, an "Error: ..." string if the
    session broke, or "No turn yet — call raid_wait_turn again." if the window
    elapsed first (just call it again). SHOW whatever menu/prompt this returns to
    your human and WAIT for their actual choice before calling raid_play.
    """
    global _pending_prompt
    if _error:
        return f"Error: {_error}"
    if _done:
        return "The game is over."
    if _pending_prompt is not None:
        return _pending_prompt

    _prompt_event.clear()
    try:
        await asyncio.wait_for(_prompt_event.wait(), timeout=max_seconds)
    except asyncio.TimeoutError:
        return "No turn yet — call raid_wait_turn again."

    if _error:
        return f"Error: {_error}"
    if _done:
        return "The game is over."
    if _pending_prompt is not None:
        return _pending_prompt
    return "No turn yet — call raid_wait_turn again."


@mcp.tool()
async def raid_play(move: str) -> str:
    """Submit your human's chosen move for the CURRENT pending turn (call
    raid_wait_turn first to see it, show it to them, and get their actual
    choice — never invent a move yourself). Returns immediately; call
    raid_wait_turn again for the next turn."""
    global _pending_prompt
    if _pending_prompt is None:
        return "It's not your turn — call raid_wait_turn first."
    _pending_prompt = None
    _prompt_event.clear()
    _move_queue.put_nowait(move)
    return "Sent — call raid_wait_turn for the next turn."


@mcp.tool()
async def raid_poll_chat() -> str:
    """Best-effort peek at party room-chat since the last poll (safe to call
    between turns, or instead of a turn while waiting). Returns one "<seat>:
    <text>" line per new message, or "(no new party chat)" if nothing's new."""
    global _last_seq
    if _session is None:
        return "Not connected. Call raid_connect first."
    chat = await _session.poll_chat(_last_seq)
    if not chat:
        return "(no new party chat)"
    lines: list[str] = []
    max_seq = _last_seq
    for item in chat:
        if not isinstance(item, dict):
            continue  # defensive: never crash the tool on a malformed chat entry
        seq = item.get("seq", _last_seq)
        if isinstance(seq, int) and seq > max_seq:
            max_seq = seq
        lines.append(f"{item.get('seat', '?')}: {item.get('text', '')}")
    _last_seq = max_seq
    return "\n".join(lines)


@mcp.tool()
async def raid_say(message: str) -> str:
    """Send a party-chat line to the raid at ANY time (not just on your turn).
    Use this to relay what the human trainer wants to tell the team. The message
    appears in every player's Room chat immediately. Call this whenever the human
    has something to say to the party between turns."""
    sess = _session  # the module-level active SeatSession (mirror raid_poll_chat)
    if sess is None:
        return "Not connected. Call raid_connect first."
    ok = await sess.say(message)
    return "sent" if ok else "could not send (try again)"


@mcp.tool()
async def raid_leave() -> str:
    """Leave the raid: cancel the background driver and close the session
    cleanly. Safe to call even if not connected."""
    await _teardown()
    return "Left the raid."


@mcp.tool()
async def raid_status() -> str:
    """A quick snapshot of session state: connected? a turn pending? game over?
    any error? Useful to re-orient after a gap in the conversation."""
    if _session is None:
        return "Not connected. Call raid_connect to join a raid seat."
    if _error:
        return f"Error: {_error}"
    if _done:
        return "Connected. The game is over."
    if _pending_prompt is not None:
        return "Connected. Your turn is pending — call raid_wait_turn to see it."
    return "Connected. Waiting for your turn — call raid_wait_turn."


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
