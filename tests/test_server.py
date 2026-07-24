"""Tests for the FastMCP tool surface in `a2a_raid_mcp.server`.

Tools are plain async functions (confirmed: `@mcp.tool()` returns the same
callable it decorates), so they're called directly here — no stdio transport
involved. A fake `SeatSession` is injected by monkeypatching the `SeatSession`
symbol the server module references, so nothing touches the network.
"""
from __future__ import annotations

import asyncio
import time

import pytest

import a2a_raid_mcp.server as server

AGENT_CARD_URL = "http://localhost:8787/api/a2a/agent/.well-known/agent-card.json"
BEARER = "super-secret-seat-bearer"


class _FakeSeatSession:
    """Stand-in for `a2a_client.SeatSession`: pre-scripted prompts/replies/chat,
    or a scripted error/hang, so tests control the driver's pace precisely."""

    def __init__(
        self,
        agent_card_url: str,
        bearer: str,
        *,
        prompts: list[str] | None = None,
        open_error: Exception | None = None,
        hang_on_open: bool = False,
        chat_batches: list[list[dict]] | None = None,
        say_result: bool = True,
    ) -> None:
        self.agent_card_url = agent_card_url
        self.bearer = bearer
        self._prompts = list(prompts or [])
        self._open_error = open_error
        self._hang_on_open = hang_on_open
        self._chat_batches = list(chat_batches or [])
        self.say_result = say_result
        self.said: list[str] = []
        self.closed = False

    async def open(self) -> str:
        if self._hang_on_open:
            await asyncio.sleep(3600)
        if self._open_error is not None:
            raise self._open_error
        return self._prompts.pop(0)

    async def reply(self, move: str) -> str:
        return self._prompts.pop(0)

    async def poll_chat(self, since: int) -> list[dict]:
        if self._chat_batches:
            return self._chat_batches.pop(0)
        return []

    async def say(self, text: str) -> bool:
        self.said.append(text)
        return self.say_result

    async def close(self) -> None:
        self.closed = True


@pytest.fixture(autouse=True)
def _reset_module_state():
    server._reset_state()
    yield
    server._reset_state()


def _install_fake(monkeypatch, **kwargs) -> _FakeSeatSession:
    """Monkeypatch `server.SeatSession` with a factory that always returns a
    fresh `_FakeSeatSession(**kwargs)`, and hand back that instance."""
    fake = _FakeSeatSession(AGENT_CARD_URL, BEARER, **kwargs)

    def _factory(agent_card_url: str, bearer: str) -> _FakeSeatSession:
        assert agent_card_url == AGENT_CARD_URL
        assert bearer == BEARER
        return fake

    monkeypatch.setattr(server, "SeatSession", _factory)
    return fake


def test_connect_then_wait_turn_returns_first_prompt(monkeypatch):
    _install_fake(monkeypatch, prompts=["FIGHT/SWITCH/TALK/RUN — pick one"])

    async def _body():
        connect_reply = await server.raid_connect(AGENT_CARD_URL, BEARER)
        assert "Connecting" in connect_reply
        prompt = await server.raid_wait_turn(max_seconds=5)
        assert prompt == "FIGHT/SWITCH/TALK/RUN — pick one"
        # Clean up: nothing pending, so play a dummy... actually leave instead.
        await server.raid_leave()

    asyncio.run(_body())


def test_play_advances_to_the_next_prompt(monkeypatch):
    _install_fake(monkeypatch, prompts=["first turn", "second turn"])

    async def _body():
        await server.raid_connect(AGENT_CARD_URL, BEARER)
        first = await server.raid_wait_turn(max_seconds=5)
        assert first == "first turn"

        played = await server.raid_play("1")
        assert "Sent" in played

        second = await server.raid_wait_turn(max_seconds=5)
        assert second == "second turn"
        await server.raid_leave()

    asyncio.run(_body())


def test_raid_play_before_a_pending_turn_is_rejected(monkeypatch):
    _install_fake(monkeypatch, hang_on_open=True)

    async def _body():
        await server.raid_connect(AGENT_CARD_URL, BEARER)
        reply = await server.raid_play("1")
        assert "not your turn" in reply
        await server.raid_leave()

    asyncio.run(_body())


def test_wait_turn_times_out_boundedly_when_no_turn_is_pending(monkeypatch):
    _install_fake(monkeypatch, hang_on_open=True)

    async def _body():
        await server.raid_connect(AGENT_CARD_URL, BEARER)
        start = time.monotonic()
        result = await server.raid_wait_turn(max_seconds=1)
        elapsed = time.monotonic() - start
        assert result == "No turn yet — call raid_wait_turn again."
        # Bounded: must not have blocked meaningfully longer than max_seconds.
        assert elapsed < 2.5
        await server.raid_leave()

    asyncio.run(_body())


def test_error_on_open_surfaces_via_wait_turn_and_status(monkeypatch):
    _install_fake(monkeypatch, open_error=RuntimeError("gateway unreachable"))

    async def _body():
        await server.raid_connect(AGENT_CARD_URL, BEARER)
        prompt = await server.raid_wait_turn(max_seconds=5)
        assert "Error" in prompt
        assert "gateway unreachable" in prompt

        status = await server.raid_status()
        assert "Error" in status
        assert "gateway unreachable" in status
        await server.raid_leave()

    asyncio.run(_body())


def test_poll_chat_formats_lines_and_advances_last_seq(monkeypatch):
    _install_fake(
        monkeypatch,
        prompts=["turn 1"],
        chat_batches=[
            [
                {"seq": 1, "seat": "npc-fire", "text": "go left"},
                {"seq": 3, "seat": "npc-water", "text": "ok, covering"},
            ],
            [],
        ],
    )

    async def _body():
        await server.raid_connect(AGENT_CARD_URL, BEARER)
        await server.raid_wait_turn(max_seconds=5)

        chat = await server.raid_poll_chat()
        assert chat == "npc-fire: go left\nnpc-water: ok, covering"
        assert server._last_seq == 3

        empty = await server.raid_poll_chat()
        assert empty == "(no new party chat)"
        await server.raid_leave()

    asyncio.run(_body())


def test_raid_say_not_connected_returns_message():
    async def _body():
        out = await server.raid_say("hi")
        assert "not connected" in out.lower()

    asyncio.run(_body())


def test_raid_say_forwards_to_session(monkeypatch):
    fake = _install_fake(monkeypatch, prompts=["turn 1"], say_result=True)

    async def _body():
        await server.raid_connect(AGENT_CARD_URL, BEARER)
        out = await server.raid_say("go water")
        assert fake.said == ["go water"]
        assert out == "sent"
        assert BEARER not in out
        await server.raid_leave()

    asyncio.run(_body())


def test_raid_say_reports_failure_without_leaking_bearer(monkeypatch):
    _install_fake(monkeypatch, prompts=["turn 1"], say_result=False)

    async def _body():
        await server.raid_connect(AGENT_CARD_URL, BEARER)
        out = await server.raid_say("go water")
        assert "could not send" in out.lower()
        assert BEARER not in out
        await server.raid_leave()

    asyncio.run(_body())


def test_raid_poll_chat_before_connect_is_a_safe_no_op():
    async def _body():
        result = await server.raid_poll_chat()
        assert "Not connected" in result

    asyncio.run(_body())


def test_raid_status_before_connect():
    async def _body():
        status = await server.raid_status()
        assert "Not connected" in status

    asyncio.run(_body())


def test_raid_wait_turn_and_play_before_connect_are_safe_no_ops():
    async def _body():
        wait_result = await server.raid_wait_turn(max_seconds=1)
        assert "No turn yet" in wait_result
        play_result = await server.raid_play("1")
        assert "not your turn" in play_result

    asyncio.run(_body())


def test_raid_leave_cancels_a_hung_driver_cleanly(monkeypatch):
    fake = _install_fake(monkeypatch, hang_on_open=True)

    async def _body():
        await server.raid_connect(AGENT_CARD_URL, BEARER)
        # Driver is stuck awaiting `open()`'s indefinite sleep.
        result = await server.raid_leave()
        assert "Left the raid" in result
        assert fake.closed is True

        status = await server.raid_status()
        assert "Not connected" in status

    asyncio.run(_body())


def test_raid_leave_is_safe_when_never_connected():
    async def _body():
        result = await server.raid_leave()
        assert "Left the raid" in result

    asyncio.run(_body())


def test_empty_string_prompt_flows_through_wait_turn_and_play(monkeypatch):
    # A turn whose message is genuinely empty must still be treated as a
    # pending prompt (not confused with "no turn yet") and must still be
    # playable — this fails against a truthiness check on `_pending_prompt`,
    # which would treat "" the same as no-turn-pending forever.
    _install_fake(monkeypatch, prompts=["", "next turn"])

    async def _body():
        await server.raid_connect(AGENT_CARD_URL, BEARER)

        first = await server.raid_wait_turn(max_seconds=5)
        assert first == ""
        assert server._pending_prompt == ""

        status = await server.raid_status()
        assert "pending" in status

        played = await server.raid_play("1")
        assert "Sent" in played

        second = await server.raid_wait_turn(max_seconds=5)
        assert second == "next turn"
        await server.raid_leave()

    asyncio.run(_body())


def test_reconnect_without_leave_closes_the_old_session(monkeypatch):
    first_fake = _install_fake(monkeypatch, prompts=["first session turn"])

    second_fake = _FakeSeatSession(
        AGENT_CARD_URL, BEARER, prompts=["second session turn"]
    )

    def _second_factory(agent_card_url: str, bearer: str):
        return second_fake

    async def _body():
        await server.raid_connect(AGENT_CARD_URL, BEARER)
        await server.raid_wait_turn(max_seconds=5)
        assert first_fake.closed is False

        # Reconnect WITHOUT calling raid_leave first.
        monkeypatch.setattr(server, "SeatSession", _second_factory)
        await server.raid_connect(AGENT_CARD_URL, BEARER)

        assert first_fake.closed is True
        assert server._session is second_fake

        prompt = await server.raid_wait_turn(max_seconds=5)
        assert prompt == "second session turn"
        await server.raid_leave()

    asyncio.run(_body())


def test_bearer_never_appears_in_any_tool_return_value(monkeypatch):
    _install_fake(
        monkeypatch,
        prompts=["turn 1", "turn 2"],
        chat_batches=[[{"seq": 1, "seat": "npc", "text": "hi"}]],
    )

    async def _body():
        outputs = [
            await server.raid_connect(AGENT_CARD_URL, BEARER),
            await server.raid_wait_turn(max_seconds=5),
            await server.raid_play("1"),
            await server.raid_wait_turn(max_seconds=5),
            await server.raid_poll_chat(),
            await server.raid_say("hi team"),
            await server.raid_status(),
            await server.raid_leave(),
        ]
        for out in outputs:
            assert BEARER not in out

    asyncio.run(_body())


