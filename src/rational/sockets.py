"""Live two-way connections: ``Socket`` classes registered with ``@app.socket(path)``.

::

    class Chat(Socket):
        auth = "required"

        async def connect(self) -> None:
            await self.join("lobby")

        async def receive(self, message: ChatMessage) -> None:  # validated with Pydantic
            await self.publish("lobby", {"from": self.user.name, "text": message.text})

In the browser: ``new WebSocket(...)`` to the path, sending and receiving JSON.

Every connection is checked like a page event: the ``Origin`` must be this site (or one listed in
``origins``), the session comes from its cookie, and messages are size- and rate-limited.
``auth = "required"`` refuses anonymous visitors, and keeps checking: with every message, when the
session changes and every ``recheck_seconds``, so signing out ends the connection. ``publish()``
reaches the room's members on every worker when the app has a bus (``App(bus=...)``); otherwise on
this worker.

Messages to a client wait in a queue of ``queue_size``: one that stops reading is disconnected
instead of holding up the others. Changes a socket makes to the session stay on this worker, for
this connection: to change what the session stores, use a page event or a service.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
import typing
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, ClassVar

from pydantic import TypeAdapter, ValidationError
from starlette.websockets import WebSocket, WebSocketDisconnect

from .concurrency import cancel_and_wait
from .errors import RationalError
from .http import SESSION_COOKIE, same_origin

if TYPE_CHECKING:
    from .app import App
    from .context import Context

log = logging.getLogger("rational")

POLICY_VIOLATION, SERVER_ERROR, TRY_AGAIN_LATER = 1008, 1011, 1013
FLUSH_SECONDS = 1.0  # how long what is queued may take to reach the client, before closing
CLOSE_SECONDS = 5.0  # how long the closing handshake may take


def _dumps(data: Any) -> str:
    return json.dumps(data, separators=(",", ":"))


class Socket:
    """One live connection. Override ``connect``, ``receive`` and ``disconnect``."""

    auth: ClassVar[str | None] = None
    origins: ClassVar[Sequence[str]] = ()  # other allowed origins, e.g. ("https://app.example",)
    max_message_bytes: ClassVar[int] = 64 * 1024
    burst: ClassVar[int] = 30
    rate: ClassVar[float] = 10.0  # messages per second, sustained
    queue_size: ClassVar[int] = 256  # messages waiting for a slow client, before it is disconnected
    recheck_seconds: ClassVar[float] = 30.0  # how often auth = "required" is checked between messages

    def __init__(self, context: Context, websocket: WebSocket, app: App) -> None:
        self.context = context
        self.websocket = websocket
        self.app = app
        self.rooms: set[str] = set()
        self._outbox: asyncio.Queue[str] = asyncio.Queue(self.queue_size)
        self._closing = False

    @property
    def user(self) -> Any:
        return self.context.user

    async def connect(self) -> None:
        """Called once accepted. Raise :class:`~rational.Forbidden` (or any RationalError) to close."""

    async def receive(self, message: Any) -> None:
        """Called with each message, validated against this parameter's annotation."""

    async def disconnect(self) -> None:
        """Called once the connection is closed, from either side."""

    async def send(self, data: Any) -> None:
        """Queue JSON data for this connection."""
        self._offer(_dumps(data))

    async def join(self, room: str) -> None:
        self.rooms.add(room)
        await self.app.rooms.join(room, self)

    async def leave(self, room: str) -> None:
        self.rooms.discard(room)
        await self.app.rooms.leave(room, self)

    async def publish(self, room: str, data: Any) -> None:
        """Send ``data`` to every connection in ``room``, on every worker."""
        await self.app.rooms.publish(room, data)

    # -- the connection's machinery -------------------------------------------------------

    def _offer(self, text: str) -> None:
        if self._closing:
            return
        try:
            self._outbox.put_nowait(text)
        except asyncio.QueueFull:
            self._kick(TRY_AGAIN_LATER)

    async def _write(self) -> None:
        while True:
            text = await self._outbox.get()
            with contextlib.suppress(RuntimeError, WebSocketDisconnect):
                await self.websocket.send_text(text)
            self._outbox.task_done()

    def _kick(self, code: int) -> None:
        """Close from outside the connection's own flow (a room delivery, a session change)."""
        if not self._closing:
            self._closing = True
            self.app._spawn(self._close(code))

    async def _close(self, code: int) -> None:
        """Deliver what is queued, if the client reads it, then close."""
        self._closing = True
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self._outbox.join(), FLUSH_SECONDS)
        with contextlib.suppress(TimeoutError, RuntimeError, WebSocketDisconnect):
            await asyncio.wait_for(self.websocket.close(code=code), CLOSE_SECONDS)

    async def _signed_in(self) -> bool:
        """Is the visitor still signed in? Their session may have ended elsewhere, even on another worker."""
        session = self.context.peek_session()
        if session is not None and await self.app.sessions.load(session.id) is None:
            return False
        await self.app.resolve_user(self.context)
        return self.context.user is not None

    async def _check_auth(self) -> None:
        if not self._closing and not await self._signed_in():
            self._kick(POLICY_VIOLATION)

    def on_session_changed(self) -> None:
        """Called by the session whenever it changes (a sign-out in another tab, say)."""
        self.app._spawn(self._check_auth())

    async def _keep_checking_auth(self) -> None:
        while True:
            await asyncio.sleep(self.recheck_seconds)
            try:
                await self._check_auth()
            except Exception:
                log.exception("could not check who is connected to %s", type(self).__name__)


class Rooms:
    """Room membership on this worker, relayed across workers through the app's bus."""

    def __init__(self, app: App) -> None:
        self.app = app
        self._members: dict[str, set[Socket]] = {}
        self._unsubscribe: dict[str, Any] = {}  # by room: the bus's unsubscribe, or a claim while subscribing

    def _channel(self, room: str) -> str:
        return f"rational:room:{room}"

    async def join(self, room: str, socket: Socket) -> None:
        self._members.setdefault(room, set()).add(socket)
        bus = self.app.bus
        if bus is None or room in self._unsubscribe:
            return
        claim = object()  # taken before the first await, so that joins at the same time subscribe once
        self._unsubscribe[room] = claim
        try:
            unsubscribe = await bus.subscribe(self._channel(room), lambda text: self._relay(room, text))
        except Exception:
            if self._unsubscribe.get(room) is claim:
                del self._unsubscribe[room]  # a later join tries again
            raise
        if self._unsubscribe.get(room) is claim:
            self._unsubscribe[room] = unsubscribe
        else:
            await unsubscribe()  # everyone left meanwhile

    async def leave(self, room: str, socket: Socket) -> None:
        members = self._members.get(room)
        if members is None:
            return
        members.discard(socket)
        if not members:
            del self._members[room]
            unsubscribe = self._unsubscribe.pop(room, None)
            if callable(unsubscribe):  # otherwise a join is still subscribing, and undoes it
                await unsubscribe()

    async def publish(self, room: str, data: Any) -> None:
        text = _dumps(data)
        self._deliver(room, text)
        if self.app.bus is not None:
            await self.app.bus.publish(self._channel(room), f"{self.app.boot_id} {text}")

    def _relay(self, room: str, message: str) -> None:
        origin, _, text = message.partition(" ")
        if origin != self.app.boot_id:  # our own publishes were delivered already
            self._deliver(room, text)

    def _deliver(self, room: str, text: str) -> None:
        for socket in self._members.get(room, ()):
            socket._offer(text)

    def count(self, room: str) -> int:
        """Connections in ``room`` on this worker."""
        return len(self._members.get(room, ()))


def _message_adapter(cls: type[Socket]) -> TypeAdapter[Any]:
    hints = {k: v for k, v in typing.get_type_hints(cls.receive).items() if k != "return"}
    return TypeAdapter(next(iter(hints.values()), Any))


async def _messages(socket: Socket, adapter: TypeAdapter[Any]) -> None:
    """Receive until the client leaves or, for ``auth = "required"``, stops being signed in."""
    cls, websocket = type(socket), socket.websocket
    tokens, stamp = float(cls.burst), time.monotonic()
    while True:
        frame = await websocket.receive()
        if frame["type"] == "websocket.disconnect":
            return
        now = time.monotonic()
        tokens = min(cls.burst, tokens + (now - stamp) * cls.rate)
        stamp = now
        if tokens < 1:
            await socket.send({"error": {"code": "rate_limited", "message": "Too many messages"}})
            continue
        tokens -= 1
        text = frame.get("text")
        if text is not None and len(text.encode()) > cls.max_message_bytes:
            await socket.send({"error": {"code": "too_large", "message": "Message too large"}})
            continue
        if cls.auth == "required" and not await socket._signed_in():
            await socket._close(POLICY_VIOLATION)
            return
        try:
            message = adapter.validate_python(json.loads(text if text is not None else "invalid"))
        except (ValueError, ValidationError):  # binary frames too: messages are JSON text
            await socket.send({"error": {"code": "bad_message", "message": "Invalid message"}})
            continue
        try:
            await socket.receive(message)
        except RationalError as e:
            await socket.send({"error": e.to_json()})


async def _serve(app: App, socket: Socket, adapter: TypeAdapter[Any]) -> None:
    cls = type(socket)
    workers = [asyncio.create_task(socket._write())]
    session = socket.context.peek_session()
    if cls.auth == "required":
        workers.append(asyncio.create_task(socket._keep_checking_auth()))
        if session is not None:
            session.listeners.add(socket)
            app.follow_sessions()
    try:
        await socket.connect()
        await _messages(socket, adapter)
    except RationalError:
        await socket._close(POLICY_VIOLATION)
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        await app.report_error(exc, "socket", f"error in socket {cls.__name__}", context=socket.context, socket=cls)
        await socket._close(SERVER_ERROR)
    finally:
        socket._closing = True
        for worker in workers:
            worker.cancel()  # first: they stop whatever happens below
        if session is not None:
            session.listeners.discard(socket)
        for room in list(socket.rooms):
            try:
                await app.rooms.leave(room, socket)
            except Exception:
                log.exception("could not leave room %s", room)
        try:
            await socket.disconnect()
        except Exception:
            log.exception("error in %s.disconnect", cls.__name__)
        await cancel_and_wait(workers)


def socket_endpoint(app: App, cls: type[Socket]) -> Any:
    adapter = _message_adapter(cls)

    async def endpoint(websocket: WebSocket) -> None:
        if not same_origin(websocket, cls.origins):
            await websocket.close(code=POLICY_VIOLATION)
            return
        session = await app.sessions.load(websocket.cookies.get(SESSION_COOKIE))
        context = await app.websocket_context(websocket, session)
        if cls.auth == "required" and context.user is None:
            await websocket.close(code=POLICY_VIOLATION)
            return
        await websocket.accept()
        await _serve(app, cls(context, websocket, app), adapter)

    return endpoint
