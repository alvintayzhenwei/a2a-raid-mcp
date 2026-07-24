"""Self-contained A2A client for one Agent Raid connect seat.

This is a deliberate, ~40-line duplication of `a2a_games.examples.connect_client`'s
core logic (`ConnectClient._resume_open_task`/`play`'s per-turn loop) — this
package is standalone and publishable to PyPI (see `a2a-raid-mcp/README.md`), so
it must NOT import `a2a_games` (an unpublished, sibling package in this repo).
Both modules are thin wrappers over the same public `a2a-sdk` call shapes
(`A2ACardResolver` + `JsonRpcTransport`, `message/send` via `SendMessageRequest`/
`new_text_message`, resuming an open task via `ListTasksRequest`), so keeping
them independently readable/copy-pasteable is preferred over a shared internal
dependency between two otherwise-unrelated distributions.

Protocol shape (mirrors `connect_client.py`): one A2A task maps to the WHOLE
game session for this seat. The first `message/send` (no task_id) gets back a
`Task` in `TASK_STATE_INPUT_REQUIRED` carrying the current turn's prompt; every
following `message/send` (same task_id/context_id) submits that turn's reply
and gets back either the NEXT turn's `INPUT_REQUIRED` prompt or a terminal
state (`TASK_STATE_COMPLETED`/`FAILED`/`CANCELED`/`REJECTED`) once the game
ends for this seat. Auth is REQUIRED — the gateway's `BearerContextBuilder`
rejects any call with no valid `Authorization: Bearer` header, so this client
raises immediately if no bearer is supplied. The bearer is stored only in
memory and is never logged, printed, or included in any exception message.
"""
from __future__ import annotations

from typing import Any, Callable
from urllib.parse import urlsplit

import httpx

from a2a.client.card_resolver import A2ACardResolver
from a2a.client.transports.jsonrpc import JsonRpcTransport
from a2a.helpers import get_message_text, new_text_message
from a2a.types.a2a_pb2 import ListTasksRequest, Role, SendMessageRequest, Task, TaskState
from a2a.utils.constants import PROTOCOL_VERSION_1_0, VERSION_HEADER

# Sentinel returned by `open()`/`reply()` once the seat's task has reached a
# terminal state (no further turns are expected from this seat).
DONE = "__DONE__"

# Held-request read timeout: the server holds a reply's `message/send` open
# across an entire player-controlled intermission before returning the next
# turn's prompt. Mirrors `connect_client.py`'s `_TURN_READ_TIMEOUT` — a
# pragmatic ceiling well under the server's own (much longer) idle backstop,
# not an attempt to ride out an arbitrarily long pause.
_TURN_READ_TIMEOUT = 200.0

TransportFactory = Callable[[], Any]


class SeatSession:
    """One connect seat's standard-A2A session: resolve the seat's Agent Card,
    open (or resume) its task, and drive turns via `reply()`.

    `agent_card_url` is the FULL served card URL (e.g.
    `http://localhost:8787/api/a2a/agent/.well-known/agent-card.json`) — the
    exact shape the game's `start`/`reserve_connect_seat` response returns
    (`connectSeats[].agentCardUrl`). It is split internally into the gateway
    origin (scheme + host[:port]) and the card's own path.

    `_transport_factory` is a PRIVATE test seam: a zero-argument callable that,
    if provided, is called to build the transport in place of the real
    `A2ACardResolver` + `JsonRpcTransport` pair — so tests can inject a fake
    transport (with async `send_message`/`list_tasks`) without any network
    access. It is never used outside tests.
    """

    def __init__(
        self,
        agent_card_url: str,
        bearer: str,
        *,
        _transport_factory: TransportFactory | None = None,
    ) -> None:
        if not bearer:
            raise ValueError(
                "SeatSession requires a bearer token — there is no unauthenticated path"
            )
        parts = urlsplit(agent_card_url)
        if not parts.scheme or not parts.netloc:
            raise ValueError(f"agent_card_url must be an absolute URL, got: {agent_card_url!r}")
        self._gateway = f"{parts.scheme}://{parts.netloc}"
        self._card_path = parts.path
        # The RPC endpoint is the card's own path with the well-known suffix
        # stripped — NOT the card's advertised interface URL, which may not be
        # reachable behind a reverse proxy (see connect_client.py's comment).
        self._rpc_url = self._card_path.rsplit("/.well-known/", 1)[0]
        self._chat_url = f"{self._rpc_url}/chat"
        self._bearer = bearer
        self._transport_factory = _transport_factory

        self._http: httpx.AsyncClient | None = None
        self._transport: Any = None
        self._task: Task | None = None

    def _build_http_client(self) -> httpx.AsyncClient:
        headers = {
            "authorization": f"Bearer {self._bearer}",
            # A transport built directly (not via the SDK's ClientFactory) does
            # not set PROTOCOL_VERSION_CURRENT for us; a missing A2A-Version
            # header reads as the legacy v0.3 protocol server-side.
            VERSION_HEADER: PROTOCOL_VERSION_1_0,
        }
        timeout = httpx.Timeout(connect=10.0, read=_TURN_READ_TIMEOUT, write=10.0, pool=10.0)
        return httpx.AsyncClient(base_url=self._gateway, headers=headers, timeout=timeout)

    async def open(self) -> str:
        """Resolve the seat's Agent Card, resume its open task if one exists
        (else send a fresh `hello`), and return the current turn's prompt text
        — or `DONE` if the task is already terminal."""
        self._http = self._build_http_client()
        if self._transport_factory is not None:
            self._transport = self._transport_factory()
        else:
            resolver = A2ACardResolver(self._http, self._gateway)
            card = await resolver.get_agent_card(relative_card_path=self._card_path)
            self._transport = JsonRpcTransport(self._http, card, self._rpc_url)

        task = await self._resume_open_task()
        if task is None:
            response = await self._transport.send_message(
                SendMessageRequest(message=new_text_message("hello", role=Role.ROLE_USER))
            )
            task = response.task
        self._task = task
        return self._prompt_or_done(task)

    async def reply(self, text: str) -> str:
        """Submit `text` as this seat's reply to the current turn and return
        the NEXT turn's prompt, or `DONE` once the task reaches a terminal
        state. Must be called after `open()`."""
        if self._task is None:
            raise RuntimeError("SeatSession.reply() called before open()")
        response = await self._transport.send_message(
            SendMessageRequest(message=new_text_message(
                text, role=Role.ROLE_USER,
                task_id=self._task.id, context_id=self._task.context_id,
            ))
        )
        self._task = response.task
        return self._prompt_or_done(self._task)

    async def poll_chat(self, since: int = -1) -> list[dict]:
        """Best-effort `GET {rpc_url}/chat?since=<since>` with this seat's own
        bearer. Returns the parsed `chat` list, or `[]` on any error (a network
        hiccup, an older gateway without this route, a bad response body)."""
        if self._http is None:
            return []
        try:
            resp = await self._http.get(self._chat_url, params={"since": since})
            resp.raise_for_status()
            return resp.json().get("chat", [])
        except Exception:
            return []

    async def say(self, text: str) -> bool:
        """Best-effort `POST {rpc_url}/chat` with `{"text": text}` and this seat's
        own bearer — the send-side twin of `poll_chat`. Returns True on a 2xx,
        False on any error (network hiccup, older gateway without the POST route,
        no open http client). Never raises; the bearer is never logged."""
        if self._http is None:
            return False
        try:
            resp = await self._http.post(self._chat_url, json={"text": text})
            resp.raise_for_status()
            return True
        except Exception:
            return False

    async def close(self) -> None:
        """Close the underlying httpx client."""
        if self._http is not None:
            await self._http.aclose()

    async def _resume_open_task(self) -> Task | None:
        """List this bearer's own tasks and return one still awaiting a reply
        (`TASK_STATE_INPUT_REQUIRED`), or `None` if there isn't one. Any
        transport error (e.g. an older gateway without `ListTasks`) is treated
        as "nothing to resume" so a fresh `hello` still works."""
        try:
            response = await self._transport.list_tasks(
                ListTasksRequest(status=TaskState.TASK_STATE_INPUT_REQUIRED)
            )
        except Exception:
            return None
        return response.tasks[0] if response.tasks else None

    @staticmethod
    def _prompt_or_done(task: Task | None) -> str:
        if task is None or task.status.state != TaskState.TASK_STATE_INPUT_REQUIRED:
            return DONE
        if not task.status.message:
            return ""
        return get_message_text(task.status.message)
