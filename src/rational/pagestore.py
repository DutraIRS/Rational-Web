"""``PageStore``: the live page views a process holds, in two pools and with a quota per session."""

from __future__ import annotations

from .limits import Limits
from .runtime import PageRuntime
from .session import TTLStore


class PageStore:
    """Live page views by id, dropped after ``page_ttl`` idle seconds or when a pool is full.

    A first-time visitor's page view goes to a smaller pool and moves to the main one when the browser
    proves it kept the session cookie (its first event or stream), so anonymous requests only push out
    each other. One session holds at most ``pages_per_session`` page views: past that, its own oldest
    goes. See :mod:`rational.limits`.
    """

    def __init__(self, limits: Limits) -> None:
        evict = PageRuntime.dispose_when_free
        self._main: TTLStore[PageRuntime] = TTLStore(limits.page_ttl, limits.max_pages, on_evict=evict)
        self._new: TTLStore[PageRuntime] = TTLStore(limits.page_ttl, limits.max_new_pages, on_evict=evict)
        self.per_session = limits.pages_per_session

    def get(self, page_id: str | None) -> PageRuntime | None:
        runtime = self._main.get(page_id)
        return runtime if runtime is not None else self._new.get(page_id)

    def put(self, runtime: PageRuntime, *, new: bool = False) -> None:
        """Hold ``runtime``; ``new``: its session was created by this request (a first-time visitor)."""
        (self._new if new else self._main).put(runtime.id, runtime)
        session = runtime.session
        if session is None:
            return
        session.pages[runtime.id] = None
        while len(session.pages) > self.per_session:
            oldest = next(iter(session.pages))
            del session.pages[oldest]
            self._main.discard(oldest)
            self._new.discard(oldest)

    def promote(self, runtime: PageRuntime) -> None:
        """The browser came back with the session cookie: keep the page view in the main pool."""
        if self._new.pop(runtime.id) is not None:
            self._main.put(runtime.id, runtime)

    def pop(self, page_id: str) -> PageRuntime | None:
        """Remove a page view without disposing of it."""
        runtime = self._main.pop(page_id)
        return runtime if runtime is not None else self._new.pop(page_id)

    def sweep(self) -> int:
        return self._main.sweep() + self._new.sweep()

    def clear(self) -> None:
        """Dispose of every page view (the app is shutting down)."""
        self._main.clear()
        self._new.clear()

    def values(self) -> list[PageRuntime]:
        return self._main.values() + self._new.values()

    def __len__(self) -> int:
        return len(self._main) + len(self._new)
