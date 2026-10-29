"""Resumable pages: rebuild a page runtime that the server no longer holds.

After each event the JSON-safe part of a page's state is saved to a driver (memory or Redis, the same
interface the session store uses). If a later event or stream arrives for a page id the process does
not know, because it was evicted, the server restarted or another worker answered, the page is rebuilt:
the route is rendered again, ``mount()`` runs again and the saved state is put back before each
component's first render, so handler ids line up with the ones already in the browser.
"""

from __future__ import annotations

import asyncio
import json
import logging
import weakref
from typing import TYPE_CHECKING, Any

from fastapi import Request

from .runtime import PageRuntime
from .stores import json_plain
from .styling.compiler import StyleSheet

if TYPE_CHECKING:
    from .app import App
    from .stores import SessionDriver

log = logging.getLogger("rational")

SNAPSHOT_VERSION = 1


def _usable(state: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in state.items() if json_plain(v)}


def _revision(raw: bytes) -> int | None:
    """The revision a stored snapshot carries; ``None`` if it is unreadable."""
    try:
        return int(json.loads(raw)["rev"])
    except (ValueError, KeyError, TypeError):
        return None


class PageResumer:
    def __init__(self, app: App, driver: SessionDriver, ttl: int = 60 * 60 * 24) -> None:
        self.app = app
        self.driver = driver
        self.ttl = ttl
        # Single flight per page id. An entry lives while someone holds or awaits its lock.
        self._locks: weakref.WeakValueDictionary[str, asyncio.Lock] = weakref.WeakValueDictionary()

    @staticmethod
    def _key(page_id: str) -> str:
        return f"rw:page:{page_id}"

    def _lock_for(self, page_id: str) -> asyncio.Lock:
        lock = self._locks.get(page_id)
        if lock is None:
            lock = self._locks[page_id] = asyncio.Lock()
        return lock

    def snapshot(self, runtime: PageRuntime) -> dict[str, Any] | None:
        if runtime.origin is None or runtime.session is None:
            return None
        components = {}
        for comp in runtime.components.values():
            if comp.path is None or not comp.resumable:
                continue
            state = _usable(comp._rw_state)
            if state:
                components[comp.path] = state
        return {
            "v": SNAPSHOT_VERSION,
            "route": runtime.origin[0],
            "params": runtime.origin[1],
            "sid": runtime.session.id,
            "rev": runtime.revision,
            "seq": runtime.seq,
            "page_state": _usable(runtime.page_state),
            "components": components,
        }

    async def save(self, runtime: PageRuntime, *, expect_revision: int | None = None) -> bool:
        """Store the page's snapshot. Returns False only if another worker advanced the page first.

        With ``expect_revision`` the write is a compare-and-swap: it lands only if the stored snapshot
        still has that revision, so two workers holding the same page cannot both advance it. A failing
        driver is logged and does not fail the event.
        """
        snap = self.snapshot(runtime)
        if snap is None:
            return True
        key, raw = self._key(runtime.id), json.dumps(snap, separators=(",", ":")).encode()
        try:
            if expect_revision is None:
                await self.driver.set(key, raw, self.ttl)
                return True
            stored = await self.driver.get(key)
            if stored is not None and _revision(stored) not in (None, expect_revision):
                return False
            return await self.driver.cas(key, stored, raw, self.ttl)
        except Exception:
            log.exception("could not save the page snapshot")
            return True

    async def forget(self, page_id: str) -> None:
        try:
            await self.driver.delete(self._key(page_id))
        except Exception:
            log.exception("could not delete the page snapshot")

    async def resume(self, request: Request, page_id: str | None, *, rev: int | None = None) -> PageRuntime | None:
        """The live runtime for ``page_id``, rebuilt from its snapshot if this process lacks it or holds
        a copy older than revision ``rev``; ``None`` if the page is unknown."""
        if not page_id:
            return None
        async with self._lock_for(page_id):  # an event and a stream may ask for the same page at once
            live = self.app.pages.get(page_id)
            if live is not None:
                if rev is None or live.revision >= rev:
                    return live
                self.app.pages.pop(page_id)  # outdated: other workers handled the latest events
                async with live.lock:
                    live.dispose()
            try:
                raw = await self.driver.get(self._key(page_id))
                snap = json.loads(raw) if raw else None
            except Exception:
                log.exception("could not read the page snapshot")
                return None
            if not isinstance(snap, dict) or snap.get("v") != SNAPSHOT_VERSION:
                return None
            return await self._rebuild(request, page_id, snap)

    async def _rebuild(self, request: Request, page_id: str, snap: dict[str, Any]) -> PageRuntime | None:
        app = self.app
        route = next((r for r in app.routes.values() if r.path == snap.get("route")), None)
        session = await app.load_session(request)
        if route is None or session is None or session.id != snap.get("sid"):
            return None
        ctx = await app.context_for(request, session)
        try:
            page = route.build(snap["params"])
            runtime = PageRuntime(page, ctx, StyleSheet(app.compiler))
            runtime.id = page_id
            runtime.origin = (route.path, snap["params"])
            runtime.page_state.update(snap["page_state"])
            runtime.restore = snap["components"]
            await runtime.render_page()
        except Exception:
            log.exception("could not resume page %s", page_id)
            return None
        runtime.restore = {}
        runtime.revision = int(snap["rev"])
        runtime.seq = int(snap["seq"])
        runtime.served = True
        runtime.sheet.drain()  # the browser already holds every rule the old runtime sent
        runtime.sync_session_revision()
        app.pages.put(page_id, runtime)
        app.logging.record("page.resumed", page_id=page_id)
        return runtime
