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

from .concurrency import cancel_and_wait

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

    reconnect_delay = 1.0  # seconds to wait after losing the connection, before trying again
    subscribe_timeout = 5.0  # seconds subscribe() waits for Redis to confirm, so a publish right after it arrives

    def __init__(self, client: Any = None, *, url: str | None = None) -> None:
        self._owns_client = client is None
        if client is None:
            from .stores import redis_from_url

            if url is None:
                raise TypeError("RedisBus needs a client or a url")
            try:
                client = redis_from_url(url)
            except ImportError as exc:  # pragma: no cover
                raise ImportError("RedisBus needs the redis package: pip install 'rational[redis]'") from exc
        self.client = client
        self._pubsub: Any = None
        self._callbacks: dict[str, list[Callback]] = {}
        self._reader: asyncio.Task[None] | None = None
        self._pending: dict[str, asyncio.Event] = {}  # channels whose SUBSCRIBE Redis has not confirmed yet

    async def publish(self, channel: str, message: str) -> None:
        await self.client.publish(channel, message)

    async def subscribe(self, channel: str, callback: Callback) -> Unsubscribe:
        if self._pubsub is None:
            self._pubsub = self.client.pubsub()
        first = channel not in self._callbacks
        self._callbacks.setdefault(channel, []).append(callback)
        if first:
            confirmed = self._pending[channel] = asyncio.Event()
            try:
                await self._pubsub.subscribe(channel)
            except Exception:
                self._callbacks.pop(channel, None)
                self._pending.pop(channel, None)
                raise
        if self._reader is None or self._reader.done():
            self._reader = asyncio.get_running_loop().create_task(self._read())
        if first:
            # PUBLISH travels on another connection: until Redis has confirmed the SUBSCRIBE, it may handle a
            # publish first and drop the message.
            try:
                await asyncio.wait_for(confirmed.wait(), self.subscribe_timeout)
            except TimeoutError:
                log.warning("Redis has not confirmed the subscription to %s yet", channel)
            finally:
                self._pending.pop(channel, None)

        async def unsubscribe() -> None:
            callbacks = self._callbacks.get(channel, [])
            if callback not in callbacks:
                return
            callbacks.remove(callback)
            if not callbacks:
                del self._callbacks[channel]
                await self._pubsub.unsubscribe(channel)

        return unsubscribe

    async def _read(self) -> None:
        while True:
            try:
                async for item in self._pubsub.listen():
                    self._dispatch(item)
                if not self._callbacks:
                    return  # the last channel was unsubscribed; the next subscribe starts a new reader
                # A subscribe arrived while this loop was ending, and saw this reader still running: go on.
            except Exception:
                if not self._callbacks:
                    return
                log.exception("the Redis bus reader stopped; reconnecting")
                await asyncio.sleep(self.reconnect_delay)
                with contextlib.suppress(Exception):
                    await self._pubsub.subscribe(*self._callbacks)

    def _dispatch(self, item: dict[str, Any]) -> None:
        kind, raw = item.get("type"), item.get("channel")
        channel = raw.decode() if isinstance(raw, bytes) else str(raw)
        if kind == "subscribe" and channel in self._pending:
            self._pending[channel].set()
        if kind != "message":
            return
        data = item["data"]
        text = data.decode() if isinstance(data, bytes) else str(data)
        for callback in list(self._callbacks.get(channel, ())):
            try:
                callback(text)
            except Exception:
                log.exception("bus subscriber failed")

    async def close(self) -> None:
        reader, self._reader = self._reader, None
        if reader is not None:
            await cancel_and_wait([reader])
        pubsub, self._pubsub = self._pubsub, None
        self._callbacks.clear()
        if pubsub is not None:
            await pubsub.aclose()
        if self._owns_client:
            await self.client.aclose()
