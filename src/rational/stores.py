"""Persistent session stores: keep sessions outside the process (Redis, or your own driver).

What is persisted is the session's CSRF token, ``session.data`` (including the signed-in user) and
the JSON-compatible ``State(scope="session")`` values, as JSON. Never pickle: a shared store is a
trust boundary, and unpickling attacker-influenced bytes runs code. Store JSON-compatible values in
the session, or pass your own ``serialize`` and ``deserialize``.

Every write is a compare-and-swap against the record this worker last read, so workers never
overwrite each other blindly. On a conflict the store reads the record again, keeps the keys this
worker changed, takes every other key from the stored record, and retries. A record that has
disappeared was ended elsewhere (a logout, or expiry) and is never written back.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any, NamedTuple, Protocol

from .session import Session, SessionStore
from .state import values_equal

log = logging.getLogger("rational.session")

Serializer = Callable[[dict[str, Any]], bytes]
Deserializer = Callable[[bytes], dict[str, Any]]

MAX_CONFLICTS = 5

# Atomic in Redis: scripts run without interleaving. ARGV: expect-absent flag, expected bytes, ttl, value.
_CAS_SCRIPT = """
local current = redis.call('GET', KEYS[1])
local expected = ARGV[1] == '1' and ARGV[2] or false
if current ~= expected then return 0 end
redis.call('SET', KEYS[1], ARGV[4], 'EX', ARGV[3])
return 1
"""


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
    async def cas(self, key: str, expected: bytes | None, value: bytes, ttl: int) -> bool:
        """Atomically set ``key`` only if it currently holds ``expected`` (``None``: if it is absent)."""
        ...

    async def touch(self, key: str, ttl: int) -> None: ...
    async def delete(self, key: str) -> None: ...


class MemorySessionDriver:
    """An in-process driver, mainly for tests and for sharing a store between apps in one process."""

    def __init__(self) -> None:
        self._items: dict[str, tuple[float, bytes]] = {}
        self._writes = 0

    def _sweep(self) -> None:
        """Drop expired items now and then, so keys that are never read again do not pile up."""
        self._writes += 1
        if self._writes % 1000 == 0:
            now = time.monotonic()
            self._items = {k: v for k, v in self._items.items() if v[0] >= now}

    async def get(self, key: str) -> bytes | None:
        entry = self._items.get(key)
        if entry is None:
            return None
        if entry[0] < time.monotonic():
            del self._items[key]
            return None
        return entry[1]

    async def set(self, key: str, value: bytes, ttl: int) -> None:
        self._sweep()
        self._items[key] = (time.monotonic() + ttl, value)

    async def cas(self, key: str, expected: bytes | None, value: bytes, ttl: int) -> bool:
        if await self.get(key) != expected:
            return False
        self._sweep()
        self._items[key] = (time.monotonic() + ttl, value)
        return True

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

    Pass a URL (``"redis://localhost:6379/0"``) or an existing ``redis.asyncio.Redis`` client
    created without ``decode_responses``.
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

    async def cas(self, key: str, expected: bytes | None, value: bytes, ttl: int) -> bool:
        absent = expected is None
        flag, compare = ("0", b"") if absent else ("1", expected)
        return bool(await self.client.eval(_CAS_SCRIPT, 1, key, flag, compare, ttl, value))

    async def touch(self, key: str, ttl: int) -> None:
        await self.client.expire(key, ttl)

    async def delete(self, key: str) -> None:
        await self.client.delete(key)


class _Record(NamedTuple):
    n: int  # write counter: every write of a record bumps it, so equal bytes mean the same write
    csrf: str
    data: dict[str, Any]
    state: dict[str, Any]


def _merge(base: dict[str, Any], ours: dict[str, Any], theirs: dict[str, Any]) -> dict[str, Any]:
    """Three-way merge: keys changed in ``ours`` since ``base`` win, the others follow ``theirs``."""
    merged = dict(theirs)
    for key in base.keys() - ours.keys():
        merged.pop(key, None)  # deleted here
    for key, value in ours.items():
        if key not in base or not values_equal(base[key], value):
            merged[key] = value  # added or changed here
    return merged


class PersistentSessionStore(SessionStore):
    """A ``SessionBackend`` that persists sessions through a ``SessionDriver``.

    Sessions are cached in process memory (up to ``max_local``), and each request reads its record
    from the driver (one round trip), so a change made on another worker is seen, and a logout
    elsewhere ends the session here too. A session is written once when the request finishes, and
    only if it changed. Match ``ttl`` to ``App(session_ttl=...)`` so the cookie and the record
    expire together.
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
        super().__init__(ttl=ttl, max_items=max_local)
        self.driver = driver
        self.ttl = int(ttl)
        self.prefix = prefix
        self.serialize = serialize
        self.deserialize = deserialize
        self.on_saved: Callable[[Session], Awaitable[None]] | None = None  # set by App(bus=...)

    def _key(self, sid: str) -> str:
        return self.prefix + sid

    async def load(self, sid: str | None) -> Session | None:
        if not sid:
            return None
        raw = await self.driver.get(self._key(sid))
        cached = self.get(sid)  # looked up after the read, so two loads of one id share one object
        if cached is None:
            return None if raw is None else self._load_new(sid, raw)
        if raw is None:
            if cached.synced is None:
                return cached  # created here and not written yet
            self._store.pop(sid)  # ended elsewhere (a logout) or expired
            return None
        if raw != cached.synced:
            async with cached.lock:  # never change a session under a running handler
                if cached.id != sid or not self._adopt(cached, raw):  # rotated meanwhile, or unreadable
                    self._store.pop(sid)
                    return None
        return cached

    def _load_new(self, sid: str, raw: bytes) -> Session | None:
        session = Session(sid)
        session.saved_revision = session.revision  # loaded, not created: nothing of its own to write
        if not self._adopt(session, raw):
            return None
        self._store.put(sid, session)
        return session

    async def rotate(self, session: Session) -> None:
        """A new id and CSRF token. The old record is deleted now; ``save`` writes the new one.

        A worker still holding the old id cannot write it back: its compare-and-swap finds the
        record gone, and it drops the session instead.
        """
        await self.driver.delete(self._key(session.id))
        session.synced, session.version, session.saved_revision = None, 0, -1
        await super().rotate(session)

    async def save(self, session: Session) -> None:
        if session.saved_revision == session.revision:
            if session.touched_at is None or time.monotonic() - session.touched_at > self.ttl / 4:
                await self.driver.touch(self._key(session.id), self.ttl)  # reads keep a session alive too
                session.touched_at = time.monotonic()
            return
        for _ in range(MAX_CONFLICTS):
            if await self._write(session):
                if self.on_saved is not None:
                    await self.on_saved(session)
                return
            raw = await self.driver.get(self._key(session.id))
            if raw is None or not self._adopt(session, raw):
                self._store.pop(session.id)  # ended elsewhere: never write it back
                return
        log.warning("a session changed on other workers %d times while saving; will retry next time", MAX_CONFLICTS)

    async def _write(self, session: Session) -> bool:
        """Compare-and-swap the record; False if it changed since this worker last read or wrote it."""
        raw = self.serialize(
            {
                "n": session.version + 1,
                "csrf": session.csrf,
                "data": session.data,
                "state": {k: v for k, v in session.state.items() if json_plain(v)},
            }
        )
        if not await self.driver.cas(self._key(session.id), session.synced, raw, self.ttl):
            return False
        session.synced, session.version = raw, session.version + 1
        session.saved_revision, session.touched_at = session.revision, time.monotonic()
        return True

    def _adopt(self, session: Session, raw: bytes) -> bool:
        """Merge the stored record ``raw`` into ``session``, keeping changes not written yet.

        Returns False if the record is unreadable.
        """
        try:
            record = self._decode(raw)
            base = self._decode(session.synced) if session.synced is not None else _Record(0, "", {}, {})
        except Exception:
            log.warning("discarding an unreadable session record", exc_info=True)
            return False
        if record.n <= session.version:
            return True  # an older read than what this worker holds
        unwritten = session.saved_revision != session.revision
        session.data = _merge(base.data, session.data, record.data)
        session.state = _merge(base.state, session.state, record.state)  # local-only values are kept
        session.csrf, session.version, session.synced = record.csrf, record.n, raw
        session.bump()  # pages of this worker that show session data render again
        if not unwritten:
            session.saved_revision = session.revision
        return True

    def _decode(self, raw: bytes) -> _Record:
        payload = self.deserialize(raw)
        return _Record(int(payload["n"]), str(payload["csrf"]), dict(payload["data"]), dict(payload.get("state") or {}))
