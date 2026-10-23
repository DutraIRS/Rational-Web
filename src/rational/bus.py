"""A tiny publish/subscribe bus so several workers can tell each other about changes.

Pages and streams live in one process, so a change made on worker B reaches a page held by worker A
only if A is told. ``App(bus=...)`` uses the bus for live session sync; the app also exposes it as
``app.bus`` for your own channels. Messages are strings (use JSON), delivery is best effort and
at most once: a worker that is not subscribed at that moment misses the message, and the next request
reads the persisted state anyway.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections import defaultdict
from collections.abc import Callable
from typing import Any, Protocol

log = logging.getLogger("rational")

Callback = Callable[[str], None]
Unsubscribe = Callable[[], Any]


class Bus(Protocol):
    async def publish(self, channel: str, message: str) -> None: ...

    async def subscribe(self, channel: str, callback: Callback) -> Unsubscribe:
        """Call ``callback(message)`` on the event loop for each message. Returns an async unsubscribe."""
        ...


class MemoryBus:
    """In-process bus. Share one instance between apps to simulate several workers in tests."""

    def __init__(self) -> None:
        self._subscribers: dict[str, list[Callback]] = defaultdict(list)

    async def publish(self, channel: str, message: str) -> None:
        for callback in list(self._subscribers.get(channel, ())):
            try:
                callback(message)
            except Exception:
                log.exception("bus subscriber failed")

    async def subscribe(self, channel: str, callback: Callback) -> Unsubscribe:
        self._subscribers[channel].append(callback)

        async def unsubscribe() -> None:
            with contextlib.suppress(ValueError):
                self._subscribers[channel].remove(callback)

        return unsubscribe


class RedisBus:
    """Redis pub/sub (``pip install "rational[redis]"``). Pass a ``redis.asyncio`` client or a URL."""

    def __init__(self, client: Any = None, *, url: str | None = None) -> None:
        if client is None:
            try:
                from redis.asyncio import Redis
            except ImportError as exc:  # pragma: no cover
                raise ImportError("RedisBus needs the redis package: pip install 'rational[redis]'") from exc
            if url is None:
                raise TypeError("RedisBus needs a client or a url")
            client = Redis.from_url(url)
        self.client = client
        self._pubsub: Any = None
        self._callbacks: dict[str, list[Callback]] = defaultdict(list)
        self._reader: asyncio.Task[None] | None = None

    async def publish(self, channel: str, message: str) -> None:
        await self.client.publish(channel, message)

    async def subscribe(self, channel: str, callback: Callback) -> Unsubscribe:
        if self._pubsub is None:
            self._pubsub = self.client.pubsub()
        first = not self._callbacks[channel]
        self._callbacks[channel].append(callback)
        if first:
            await self._pubsub.subscribe(channel)
        if self._reader is None or self._reader.done():
            self._reader = asyncio.get_running_loop().create_task(self._read())

        async def unsubscribe() -> None:
            callbacks = self._callbacks[channel]
            with contextlib.suppress(ValueError):
                callbacks.remove(callback)
            if not callbacks:
                self._callbacks.pop(channel, None)
                await self._pubsub.unsubscribe(channel)

        return unsubscribe

    async def _read(self) -> None:
        try:
            async for item in self._pubsub.listen():
                if item.get("type") != "message":
                    continue
                channel, data = item["channel"], item["data"]
                channel = channel.decode() if isinstance(channel, bytes) else channel
                text = data.decode() if isinstance(data, bytes) else str(data)
                for callback in list(self._callbacks.get(channel, ())):
                    try:
                        callback(text)
                    except Exception:
                        log.exception("bus subscriber failed")
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("the Redis bus reader stopped")

    async def close(self) -> None:
        if self._reader is not None:
            self._reader.cancel()
        if self._pubsub is not None:
            await self._pubsub.aclose()
