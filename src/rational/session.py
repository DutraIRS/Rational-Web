"""Server-side browser sessions and bounded in-memory stores.

The browser only holds an opaque random id (``rw_sid`` cookie). The default store keeps
sessions in process memory; :mod:`rational.stores` persists them for several workers.
"""

from __future__ import annotations

import asyncio
import secrets
import time
import weakref
from collections import OrderedDict
from collections.abc import Callable, Iterator, MutableMapping
from typing import Any, Generic, Protocol, TypeVar

from ._tracking import changed, track_read

USER_KEY = "rw.user"

V = TypeVar("V")


class Session(MutableMapping[str, Any]):
    """Per-browser key/value data. Reads during render are tracked like state."""

    def __init__(self, sid: str) -> None:
        self.id = sid
        self.csrf = secrets.token_urlsafe(24)
        self.data: dict[str, Any] = {}
        self.state: dict[str, Any] = {}
        self.lock = asyncio.Lock()
        self.revision = 0
        self.rotated = False
        # Bookkeeping for persistent stores: the stored record this worker last read or wrote,
        # its write counter, the revision it reflects and when the record's expiry was renewed.
        self.synced: bytes | None = None
        self.version = 0
        self.saved_revision = -1
        self.touched_at: float | None = None
        # Page runtimes that want to hear about changes (live cross-tab sync); weak, so they can expire.
        self.listeners: weakref.WeakSet[Any] = weakref.WeakSet()

    def __getitem__(self, key: str) -> Any:
        track_read(("s", key))
        return self.data[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self.data[key] = value
        self.bump()

    def __delitem__(self, key: str) -> None:
        del self.data[key]
        self.bump()

    def __iter__(self) -> Iterator[str]:
        return iter(self.data)

    def __len__(self) -> int:
        return len(self.data)

    def bump(self) -> None:
        self.revision += 1
        changed()
        for listener in list(self.listeners):
            listener.on_session_changed()

    @property
    def user(self) -> Any:
        return self.get(USER_KEY)

    def login(self, user: Any) -> None:
        """Store the authenticated principal and rotate the session id (anti-fixation)."""
        self[USER_KEY] = user
        self.rotated = True

    def logout(self) -> None:
        self.data.clear()
        self.state.clear()
        self.bump()
        self.rotated = True


class TTLStore(Generic[V]):
    """LRU map with idle expiry."""

    def __init__(self, ttl: float, max_items: int, on_evict: Callable[[V], None] | None = None) -> None:
        self.ttl = ttl
        self.max_items = max_items
        self.on_evict = on_evict
        self._items: OrderedDict[str, tuple[float, V]] = OrderedDict()

    def get(self, key: str | None) -> V | None:
        if not key:
            return None
        entry = self._items.get(key)
        if entry is None:
            return None
        stamp, value = entry
        now = time.monotonic()
        if now - stamp > self.ttl:
            self._evict(key)
            return None
        self._items[key] = (now, value)
        self._items.move_to_end(key)
        return value

    def put(self, key: str, value: V) -> None:
        self._items[key] = (time.monotonic(), value)
        self._items.move_to_end(key)
        while len(self._items) > self.max_items:
            self._evict(next(iter(self._items)))

    def pop(self, key: str) -> V | None:
        entry = self._items.pop(key, None)
        return None if entry is None else entry[1]

    def sweep(self) -> int:
        now = time.monotonic()
        expired = [k for k, (stamp, _) in self._items.items() if now - stamp > self.ttl]
        for key in expired:
            self._evict(key)
        return len(expired)

    def __len__(self) -> int:
        return len(self._items)

    def _evict(self, key: str) -> None:
        entry = self._items.pop(key, None)
        if entry is not None and self.on_evict is not None:
            self.on_evict(entry[1])


class SessionBackend(Protocol):
    """What ``App`` needs from a session store; implement it to plug in Redis, a database, etc.

    ``get``, ``create`` and ``sweep`` are synchronous and local. The rest may talk to a store outside
    the process: ``load`` runs at the start of a request, ``rotate`` gives a session a new id and CSRF
    token (login, logout) before the response names the new id, and ``save`` runs when the request is
    done with the session. A purely in-memory store makes all three trivial.
    """

    def get(self, sid: str | None) -> Session | None: ...
    def create(self) -> Session: ...
    def sweep(self) -> int: ...
    async def load(self, sid: str | None) -> Session | None: ...
    async def rotate(self, session: Session) -> None: ...
    async def save(self, session: Session) -> None: ...


class SessionStore:
    """The default, in-process ``SessionBackend``."""

    def __init__(self, ttl: float = 60 * 60 * 24, max_items: int = 100_000) -> None:
        self._store: TTLStore[Session] = TTLStore(ttl, max_items)

    def get(self, sid: str | None) -> Session | None:
        return self._store.get(sid)

    async def load(self, sid: str | None) -> Session | None:
        return self.get(sid)

    async def save(self, session: Session) -> None:
        return None

    def create(self) -> Session:
        session = Session(secrets.token_urlsafe(32))
        self._store.put(session.id, session)
        return session

    async def rotate(self, session: Session) -> None:
        self._store.pop(session.id)
        session.id = secrets.token_urlsafe(32)
        session.csrf = secrets.token_urlsafe(24)
        self._store.put(session.id, session)

    def sweep(self) -> int:
        return self._store.sweep()
