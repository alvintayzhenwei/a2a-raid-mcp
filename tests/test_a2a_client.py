"""Tests for SeatSession, using a fake transport injected via the private
`_transport_factory` seam so nothing touches the network. Task/message
objects are built with the REAL a2a-sdk proto types (`Task`, `TaskStatus`,
`new_text_message`) — only the transport (the network layer) is faked — so
`get_message_text`/`task.status.state` behave exactly as they do against a
real gateway."""
from __future__ import annotations

import pytest

from a2a.helpers import new_text_message
from a2a.types.a2a_pb2 import (
    ListTasksResponse,
    Role,
    SendMessageResponse,
    Task,
    TaskState,
    TaskStatus,
)

from a2a_raid_mcp.a2a_client import DONE, SeatSession

AGENT_CARD_URL = "http://localhost:8787/api/a2a/agent/.well-known/agent-card.json"
BEARER = "test-bearer-token"


def _task(task_id: str, context_id: str, state: TaskState.ValueType, text: str | None = None) -> Task:
    status = TaskStatus(state=state)
    if text is not None:
        status.message.CopyFrom(new_text_message(text, role=Role.ROLE_AGENT))
    return Task(id=task_id, context_id=context_id, status=status)


class _FakeTransport:
    """Minimal stand-in for `JsonRpcTransport`: pre-canned `list_tasks`/
    `send_message` responses, popped off a queue per call."""

    def __init__(self, *, resume_tasks=None, send_message_tasks=None, list_tasks_error=None):
        self._resume_tasks = resume_tasks or []
        self._send_queue = list(send_message_tasks or [])
        self._list_tasks_error = list_tasks_error
        self.sent_texts: list[str] = []

    async def list_tasks(self, request):
        if self._list_tasks_error is not None:
            raise self._list_tasks_error
        return ListTasksResponse(tasks=self._resume_tasks)

    async def send_message(self, request):
        self.sent_texts.append(request.message.parts[0].text)
        task = self._send_queue.pop(0)
        return SendMessageResponse(task=task)


def _session(transport: _FakeTransport) -> SeatSession:
    return SeatSession(AGENT_CARD_URL, BEARER, _transport_factory=lambda: transport)


def test_requires_a_bearer():
    with pytest.raises(ValueError):
        SeatSession(AGENT_CARD_URL, "")


def test_open_returns_first_prompt_from_a_fresh_task():
    task = _task("t1", "c1", TaskState.TASK_STATE_INPUT_REQUIRED, "what's your move?")
    transport = _FakeTransport(resume_tasks=[], send_message_tasks=[task])
    session = _session(transport)

    prompt = _run(session.open())

    assert prompt == "what's your move?"
    # A fresh `hello` was sent since there was nothing to resume.
    assert transport.sent_texts == ["hello"]


def test_open_resumes_an_existing_input_required_task_without_sending_hello():
    task = _task("t1", "c1", TaskState.TASK_STATE_INPUT_REQUIRED, "resumed prompt")
    transport = _FakeTransport(resume_tasks=[task], send_message_tasks=[])
    session = _session(transport)

    prompt = _run(session.open())

    assert prompt == "resumed prompt"
    assert transport.sent_texts == []


def test_reply_returns_the_next_prompt():
    first = _task("t1", "c1", TaskState.TASK_STATE_INPUT_REQUIRED, "first prompt")
    second = _task("t1", "c1", TaskState.TASK_STATE_INPUT_REQUIRED, "second prompt")
    transport = _FakeTransport(resume_tasks=[], send_message_tasks=[first, second])
    session = _session(transport)

    _run(session.open())
    prompt = _run(session.reply("I strike with fire!"))

    assert prompt == "second prompt"
    assert transport.sent_texts == ["hello", "I strike with fire!"]


def test_reply_returns_done_when_the_task_goes_terminal():
    first = _task("t1", "c1", TaskState.TASK_STATE_INPUT_REQUIRED, "last prompt")
    terminal = _task("t1", "c1", TaskState.TASK_STATE_COMPLETED)
    transport = _FakeTransport(resume_tasks=[], send_message_tasks=[first, terminal])
    session = _session(transport)

    _run(session.open())
    prompt = _run(session.reply("gg"))

    assert prompt == DONE


def test_open_returns_done_when_resumed_task_is_already_terminal():
    terminal = _task("t1", "c1", TaskState.TASK_STATE_COMPLETED)
    transport = _FakeTransport(resume_tasks=[terminal], send_message_tasks=[])
    session = _session(transport)

    prompt = _run(session.open())

    assert prompt == DONE


def test_poll_chat_returns_the_parsed_chat_list(monkeypatch):
    task = _task("t1", "c1", TaskState.TASK_STATE_INPUT_REQUIRED, "prompt")
    transport = _FakeTransport(resume_tasks=[], send_message_tasks=[task])
    session = _session(transport)
    _run(session.open())

    class _FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {"chat": [{"seq": 1, "seat": "you", "text": "hi"}]}

    async def _fake_get(url, params=None):
        assert params == {"since": -1}
        return _FakeResponse()

    monkeypatch.setattr(session._http, "get", _fake_get)

    chat = _run(session.poll_chat())

    assert chat == [{"seq": 1, "seat": "you", "text": "hi"}]


def test_poll_chat_returns_empty_list_on_any_error(monkeypatch):
    task = _task("t1", "c1", TaskState.TASK_STATE_INPUT_REQUIRED, "prompt")
    transport = _FakeTransport(resume_tasks=[], send_message_tasks=[task])
    session = _session(transport)
    _run(session.open())

    async def _boom(url, params=None):
        raise RuntimeError("network hiccup")

    monkeypatch.setattr(session._http, "get", _boom)

    chat = _run(session.poll_chat())

    assert chat == []


def test_poll_chat_before_open_returns_empty_list():
    session = SeatSession(AGENT_CARD_URL, BEARER, _transport_factory=lambda: _FakeTransport())
    assert _run(session.poll_chat()) == []


def test_say_posts_with_bearer_and_returns_true(monkeypatch):
    task = _task("t1", "c1", TaskState.TASK_STATE_INPUT_REQUIRED, "prompt")
    transport = _FakeTransport(resume_tasks=[], send_message_tasks=[task])
    session = _session(transport)
    _run(session.open())

    posted = {}

    class _FakeResponse:
        def raise_for_status(self):
            pass

    async def _fake_post(url, json=None):
        posted["url"] = url
        posted["json"] = json
        return _FakeResponse()

    monkeypatch.setattr(session._http, "post", _fake_post)

    ok = _run(session.say("hello party"))

    assert ok is True
    assert posted["url"] == session._chat_url
    assert posted["json"] == {"text": "hello party"}


def test_say_returns_false_on_any_error(monkeypatch):
    task = _task("t1", "c1", TaskState.TASK_STATE_INPUT_REQUIRED, "prompt")
    transport = _FakeTransport(resume_tasks=[], send_message_tasks=[task])
    session = _session(transport)
    _run(session.open())

    async def _boom(url, json=None):
        raise RuntimeError("net")

    monkeypatch.setattr(session._http, "post", _boom)

    assert _run(session.say("x")) is False


def test_say_before_open_returns_false():
    session = SeatSession(AGENT_CARD_URL, BEARER, _transport_factory=lambda: _FakeTransport())
    assert _run(session.say("x")) is False


def _run(coro):
    """Tiny asyncio runner so tests don't need pytest-asyncio configured."""
    import asyncio

    return asyncio.run(coro)
