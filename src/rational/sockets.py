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
``origins``), the session comes from its cookie, ``auth = "required"`` refuses anonymous visitors,
and messages are size- and rate-limited. ``publish()`` reaches the room's members on every worker
when the app has a bus (``App(bus=...)``); otherwise on this worker.
"""

from __future__ import annotations

import contextlib
import inspect
import json
import logging
import time
import typing
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, ClassVar
from urllib.parse import urlsplit

from pydantic import TypeAdapter, ValidationError
from starlette.websockets import WebSocket, WebSocketDisconnect

from .errors import RationalError

if TYPE_CHECKING:
    from .app import App
    from .context import Context

log = logging.getLogger("rational")


class Socket:
    """One live connection. Override ``connect``, ``receive`` and ``disconnect``."""

    auth: ClassVar[str | None] = None
    origins: ClassVar[Sequence[str]] = ()  # other allowed origins, e.g. ("https://app.example",)
    max_message_bytes: ClassVar[int] = 64 * 1024
    burst: ClassVar[int] = 30
    rate: ClassVar[float] = 10.0  # messages per second, sustained

    def __init__(self, context: Context, websocket: WebSocket, app: App) -> None:
        self.context = context
        self.websocket = websocket
        self.app = app
        self.rooms: set[str] = set()

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
        """Send JSON data to this connection."""
        with contextlib.suppress(RuntimeError, WebSocketDisconnect):
            await self.websocket.send_json(data)

    async def join(self, room: str) -> None:
        self.rooms.add(room)
        await self.app.rooms.join(room, self)

    async def leave(self, room: str) -> None:
        self.rooms.discard(room)
        await self.app.rooms.leave(room, self)

    async def publish(self, room: str, data: Any) -> None:
        """Send ``data`` to every connection in ``room``, on every worker."""
        await self.app.rooms.publish(room, data)


class Rooms:
    """Room membership on this worker, relayed across workers through the app's bus."""

    def __init__(self, app: App) -> None:
        self.app = app
        self._members: dict[str, set[Socket]] = {}
        self._unsubscribe: dict[str, Any] = {}

    def _channel(self, room: str) -> str:
        return f"rational:room:{room}"

    async def join(self, room: str, socket: Socket) -> None:
        members = self._members.setdefault(room, set())
        members.add(socket)
        bus = self.app.bus
        if bus is not None and room not in self._unsubscribe:
            self._unsubscribe[room] = None  # claimed
            self._unsubscribe[room] = await bus.subscribe(self._channel(room), lambda text: self._relay(room, text))

    async def leave(self, room: str, socket: Socket) -> None:
        members = self._members.get(room)
        if members is None:
            return
        members.discard(socket)
        if not members:
            del self._members[room]
            unsubscribe = self._unsubscribe.pop(room, None)
            if unsubscribe is not None:
                await unsubscribe()

    async def publish(self, room: str, data: Any) -> None:
        text = json.dumps(data, separators=(",", ":"))
        await self._deliver(room, text)
        if self.app.bus is not None:
            await self.app.bus.publish(self._channel(room), f"{self.app.boot_id} {text}")

    def _relay(self, room: str, message: str) -> None:
        origin, _, text = message.partition(" ")
        if origin != self.app.boot_id:  # our own publishes were delivered already
            self.app._spawn(self._deliver(room, text))

    async def _deliver(self, room: str, text: str) -> None:
        for socket in list(self._members.get(room, ())):
            with contextlib.suppress(RuntimeError, WebSocketDisconnect):
                await socket.websocket.send_text(text)

    def count(self, room: str) -> int:
        """Connections in ``room`` on this worker."""
        return len(self._members.get(room, ()))


def _origin_allowed(websocket: WebSocket, extra: Sequence[str]) -> bool:
    origin = websocket.headers.get("origin")
    host = websocket.headers.get("host")
    if not origin:
        return False
    return urlsplit(origin).netloc == host or origin in extra


def _message_adapter(cls: type[Socket]) -> TypeAdapter[Any]:
    hints = {k: v for k, v in typing.get_type_hints(cls.receive).items() if k != "return"}
    return TypeAdapter(next(iter(hints.values()), Any))


def socket_endpoint(app: App, cls: type[Socket]) -> Any:
    adapter = _message_adapter(cls)

    async def endpoint(websocket: WebSocket) -> None:
        if not _origin_allowed(websocket, cls.origins):
            await websocket.close(code=1008)
            return
        from .context import Context
        from .http import SESSION_COOKIE

        session = await app.sessions.load(websocket.cookies.get(SESSION_COOKIE))
        context = Context(app, None, session)
        context.websocket = websocket
        if app.authenticator is not None:
            user = app.authenticator(context)
            if inspect.isawaitable(user):
                user = await user
            context.set_user(user)
        if cls.auth == "required" and context.user is None:
            await websocket.close(code=1008)
            return
        socket = cls(context, websocket, app)
        await websocket.accept()
        tokens, stamp = float(cls.burst), time.monotonic()
        try:
            await socket.connect()
            while True:
                text = await websocket.receive_text()
                now = time.monotonic()
                tokens = min(cls.burst, tokens + (now - stamp) * cls.rate)
                stamp = now
                if tokens < 1:
                    await socket.send({"error": {"code": "rate_limited", "message": "Too many messages"}})
                    continue
                tokens -= 1
                if len(text.encode()) > cls.max_message_bytes:
                    await socket.send({"error": {"code": "too_large", "message": "Message too large"}})
                    continue
                try:
                    message = adapter.validate_python(json.loads(text))
                except (ValueError, ValidationError):
                    await socket.send({"error": {"code": "bad_message", "message": "Invalid message"}})
                    continue
                try:
                    await socket.receive(message)
                except RationalError as e:
                    await socket.send({"error": e.to_json()})
        except RationalError:
            with contextlib.suppress(RuntimeError):
                await websocket.close(code=1008)
        except WebSocketDisconnect:
            pass
        except Exception:
            log.exception("error in socket %s", cls.__name__)
            with contextlib.suppress(RuntimeError):
                await websocket.close(code=1011)
        finally:
            for room in list(socket.rooms):
                await app.rooms.leave(room, socket)
            try:
                await socket.disconnect()
            except Exception:
                log.exception("error in %s.disconnect", cls.__name__)

    return endpoint
