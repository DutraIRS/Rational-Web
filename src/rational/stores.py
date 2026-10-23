"""Persistent session stores: keep ``session.data`` outside the process (Redis, or your own driver).

What is persisted is the session id, its CSRF token and ``session.data`` (including the logged-in
user), as JSON. Never pickle: a shared store is a trust boundary, and unpickling attacker-influenced
bytes runs code. Store JSON-compatible values in the session, or pass your own ``serialize`` and
``deserialize``. ``State(scope="session")`` values and open pages stay worker-local, so a
multi-worker deployment still needs sticky routing for interactive pages, but logins, CSRF tokens
and API calls work on any worker and survive restarts.
"""

from __future__ import annotations

import json
import logging
import secrets
import time
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from .session import Session, TTLStore

log = logging.getLogger("rational.session")

Serializer = Callable[[dict[str, Any]], bytes]
Deserializer = Callable[[bytes], dict[str, Any]]


def json_plain(value: Any) -> bool:
    """True if ``value`` survives a JSON round trip unchanged."""
    try:
        return bool(json.loads(json.dumps(value)) == value)
    except (TypeError, ValueError):
        return False


def json_serialize(payload: dict[str, Any]) -> bytes:
    try:
        return json.dumps(payload, separators=(",", ":")).encode()
    except TypeError as e:
        raise TypeError(
            f"session data must be JSON-serializable to use a persistent store ({e}); "
            "store ids or plain values, or pass serialize=/deserialize="
        ) from e


def json_deserialize(raw: bytes) -> dict[str, Any]:
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("session payload is not an object")
    return value


class SessionDriver(Protocol):
    """A tiny async key-value interface with expiry. Keys are strings, values bytes."""

    async def get(self, key: str) -> bytes | None: ...
    async def set(self, key: str, value: bytes, ttl: int) -> None: ...
    async def touch(self, key: str, ttl: int) -> None: ...
    async def delete(self, key: str) -> None: ...


class MemorySessionDriver:
    """An in-process driver, mainly for tests and for sharing a store between apps in one process."""

    def __init__(self) -> None:
        self._items: dict[str, tuple[float, bytes]] = {}

    async def get(self, key: str) -> bytes | None:
        entry = self._items.get(key)
        if entry is None:
            return None
        if entry[0] < time.monotonic():
            del self._items[key]
            return None
        return entry[1]

    async def set(self, key: str, value: bytes, ttl: int) -> None:
        self._items[key] = (time.monotonic() + ttl, value)

    async def touch(self, key: str, ttl: int) -> None:
        entry = self._items.get(key)
        if entry is not None:
            self._items[key] = (time.monotonic() + ttl, entry[1])

    async def delete(self, key: str) -> None:
        self._items.pop(key, None)

    def __len__(self) -> int:
        return len(self._items)


class RedisSessionDriver:
    """Redis through ``redis.asyncio`` (``pip install redis``).

    Pass a URL (``"redis://localhost:6379/0"``) or an existing ``redis.asyncio.Redis`` client.
    """

    def __init__(self, client: Any = None, *, url: str | None = None) -> None:
        if client is None:
            if url is None:
                raise ValueError("pass a redis client or url=")
            try:
                from redis.asyncio import Redis
            except ImportError as e:
                raise ImportError("RedisSessionDriver needs the 'redis' package: pip install redis") from e
            client = Redis.from_url(url)
        self.client = client

    async def get(self, key: str) -> bytes | None:
        value = await self.client.get(key)
        return None if value is None else bytes(value)

    async def set(self, key: str, value: bytes, ttl: int) -> None:
        await self.client.set(key, value, ex=ttl)

    async def touch(self, key: str, ttl: int) -> None:
        await self.client.expire(key, ttl)

    async def delete(self, key: str) -> None:
        await self.client.delete(key)


class PersistentSessionStore:
    """A ``SessionBackend`` that persists sessions through a ``SessionDriver``.

    Each request reads its session from the driver (one round trip), so a change made on another
    worker is seen, and a logout elsewhere ends the session here too. Writes happen once when the
    request finishes, and only if the session changed. Concurrent writes from different workers are
    last-write-wins. Match ``ttl`` to ``App(session_ttl=...)`` so the cookie and the record expire
    together.
    """

    def __init__(
        self,
        driver: SessionDriver,
        *,
        ttl: float = 60 * 60 * 24,
        prefix: str = "rational:session:",
        max_local: int = 100_000,
        serialize: Serializer = json_serialize,
        deserialize: Deserializer = json_deserialize,
    ) -> None:
        self.driver = driver
        self.ttl = int(ttl)
        self.prefix = prefix
        self.serialize = serialize
        self.deserialize = deserialize
        self._local: TTLStore[Session] = TTLStore(ttl, max_local)
        self._stale: list[str] = []
        self.on_saved: Callable[[Session], Awaitable[None]] | None = None  # set by App(bus=...)

    def _key(self, sid: str) -> str:
        return self.prefix + sid

    # -- local, synchronous part -------------------------------------------------------------

    def get(self, sid: str | None) -> Session | None:
        return self._local.get(sid)

    def create(self) -> Session:
        session = Session(secrets.token_urlsafe(32))
        self._local.put(session.id, session)
        return session

    def rotate(self, session: Session) -> None:
        self._local.pop(session.id)
        self._stale.append(session.id)  # deleted from the driver at the next save
        session.id = secrets.token_urlsafe(32)
        session.csrf = secrets.token_urlsafe(24)
        session.saved_revision = -1
        self._local.put(session.id, session)

    def sweep(self) -> int:
        return self._local.sweep()

    # -- persistence ---------------------------------------------------------------------------

    async def load(self, sid: str | None) -> Session | None:
        if not sid:
            return None
        cached = self._local.get(sid)
        raw = await self.driver.get(self._key(sid))
        if raw is None:
            if cached is not None and cached.saved_revision != -1:
                self._local.pop(sid)  # ended or expired elsewhere
                return None
            return cached
        try:
            payload = self.deserialize(raw)
            version, csrf, data = int(payload["n"]), str(payload["csrf"]), dict(payload["data"])
            state = dict(payload.get("state") or {})
        except Exception:
            log.warning("discarding an unreadable session record", exc_info=True)
            return None
        if cached is not None:
            if cached.version != version:
                cached.data, cached.csrf, cached.version = data, csrf, version
                cached.state.update(state)  # values that are not JSON stay local
                cached.bump()  # tell open pages of this worker that the data changed under them
                cached.saved_revision = cached.revision
            return cached
        session = Session(sid)
        session.data, session.csrf, session.version = data, csrf, version
        session.state.update(state)
        session.saved_revision = session.revision
        self._local.put(sid, session)
        return session

    async def save(self, session: Session) -> None:
        stale, self._stale = self._stale, []
        for old in stale:
            await self.driver.delete(self._key(old))
        key = self._key(session.id)
        if session.saved_revision != session.revision:
            session.version += 1
            payload = {
                "n": session.version,
                "csrf": session.csrf,
                "data": session.data,
                "state": {k: v for k, v in session.state.items() if json_plain(v)},
            }
            await self.driver.set(key, self.serialize(payload), self.ttl)
            session.saved_revision = session.revision
            session.touched_at = time.monotonic()
            if self.on_saved is not None:
                await self.on_saved(session)
        elif time.monotonic() - session.touched_at > self.ttl / 4:
            await self.driver.touch(key, self.ttl)  # idle expiry counts reads too, not only writes
            session.touched_at = time.monotonic()
