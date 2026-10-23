"""``PageRuntime``: one live page view held on the server.

It renders the component tree, assigns component ids, registers event
handlers under opaque ids, records which components read which state, and on
each event rerenders dirty components into morph patches.
"""

from __future__ import annotations

import asyncio
import contextlib
import contextvars
import inspect
import itertools
import json
import logging
import math
import secrets
import time
from collections import Counter
from collections.abc import Callable, Coroutine
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from ._tracking import Cell, Frame, current_frame
from .binding import bind_payload, check_signature
from .component import Component, Page
from .concurrency import invoke
from .diff import diff
from .errors import RationalError
from .rendering.builder import normalize_children
from .rendering.html import to_html
from .rendering.nodes import Node, RawHTML, TextNode
from .styling.compiler import StyleSheet
from .styling.style import merge

if TYPE_CHECKING:
    from .context import Context

MAX_FLUSH_PASSES = 8
PUSH_COALESCE_SECONDS = 0.03
MAX_STREAMS_PER_PAGE = 4
SUBSCRIBER_QUEUE_SIZE = 256

log = logging.getLogger("rational")


class StaleHandlerError(RationalError):
    status = 409
    code = "stale"

    def default_message(self) -> str:
        return "This part of the page changed; it has been refreshed"


class PageRuntime:
    def __init__(self, page: Page, context: Context, sheet: StyleSheet) -> None:
        self.id = secrets.token_urlsafe(18)
        self.page = page
        self.context = context
        self.sheet = sheet
        self.session = context.peek_session()
        self.components: dict[str, Component] = {}
        self.paths: dict[str, str] = {}
        self.parent: dict[str, str | None] = {}
        self.children: dict[str, set[str]] = {}
        self.rendered: dict[str, Node] = {}  # last resolved tree per component, for fine-grained diffs
        self.resync = False  # the browser is out of sync: the next flush sends full morphs
        self.handlers: dict[str, tuple[Component, Callable[..., Any], str]] = {}
        self.component_handlers: dict[str, list[str]] = {}
        self.deps: dict[Cell, set[str]] = {}
        self.component_deps: dict[str, set[Cell]] = {}
        self.page_state: dict[str, Any] = {}
        self.dirty: set[str] = set()
        self.actions: list[dict[str, Any]] = []
        self.revision = 0
        self.session_revision = -1
        self.interactive = False
        self.lock = asyncio.Lock()
        self.tokens = math.inf  # start with a full bucket
        self.token_stamp = time.monotonic()
        self._cids = itertools.count()
        self._visited: set[str] = set()
        # Server push: background tasks mutate state, and the pusher streams the resulting patches.
        self.seq = 0  # bumped for every batch of patches sent, over HTTP or the stream
        self.served = False  # the page HTML has been delivered to the browser
        self.closed = False
        self.wants_stream = False
        self.tasks: dict[asyncio.Task[None], str] = {}
        self.subscribers: set[asyncio.Queue[dict[str, Any] | None]] = set()
        self._push_scheduled = False
        self._pushers: set[asyncio.Task[None]] = set()

    # -- rendering -------------------------------------------------------------------

    async def render_page(self) -> Node:
        node = await self._render_component(self.page, "page", None)
        self._remember(node)
        self.sync_session_revision()
        return node

    def _assemble(self, node: Node, root: bool = True) -> Node:
        """``node`` with nested components replaced by their latest trees (they re-render on their own)."""
        cid = next((v for n, v in node.attrs if n == "data-rw-c"), None)
        if not root and isinstance(cid, str) and cid in self.rendered:
            node = self.rendered[cid]
        if not any(isinstance(c, Node) for c in node.children):
            return node
        kids = tuple(self._assemble(c, False) if isinstance(c, Node) else c for c in node.children)
        return replace(node, children=kids)

    def _remember(self, node: Node) -> None:
        """Record every component subtree in ``node`` so nested trees never go stale."""
        stack: list[Node] = [node]
        while stack:
            current = stack.pop()
            for name, value in current.attrs:
                if name == "data-rw-c" and isinstance(value, str):
                    self.rendered[value] = current
            stack.extend(c for c in current.children if isinstance(c, Node))

    async def rerender(self, component: Component) -> Node:
        assert component.cid is not None and component.path is not None
        before = self._descendants(component.cid)
        self._visited = set()
        node = await self._render_component(component, component.path, self.parent[component.cid])
        for cid in before - self._visited:
            self._unmount(cid)
        self._remember(node)
        return node

    async def _render_component(self, comp: Component, path: str, parent: str | None) -> Node:
        comp = await self._mount_or_reuse(comp, path, parent)
        cid = comp.cid
        assert cid is not None
        if cid in self._visited:
            raise ValueError(f"duplicate component identity {path!r}; give siblings distinct key= values")
        self._visited.add(cid)
        self._forget_render(cid)
        if parent is not None:
            self.children.setdefault(parent, set()).add(cid)

        frame = Frame(self, comp)
        token = current_frame.set(frame)
        try:
            output = comp.render()
            if inspect.isawaitable(output):
                output = await output
            items = normalize_children([output])
        except Exception as exc:
            if not any(n.startswith("while rendering") for n in getattr(exc, "__notes__", [])):
                exc.add_note(f"while rendering {type(comp).__name__} at {path}")
            raise
        finally:
            current_frame.reset(token)

        if len(items) == 1 and isinstance(items[0], Node):
            root = items[0]
            if comp.style is not None:
                root = replace(root, style=merge(root.style, comp.style))
        else:
            root = Node("div", children=tuple(items), style=comp.style)
        resolved = await self._resolve_node(root, frame, Counter())
        return replace(resolved, attrs=(*resolved.attrs, ("data-rw-c", cid)))

    async def _mount_or_reuse(self, comp: Component, path: str, parent: str | None) -> Component:
        existing_cid = self.paths.get(path)
        if existing_cid is not None:
            existing = self.components[existing_cid]
            if existing is comp:
                return comp
            if type(existing) is type(comp) and comp.cid is None:
                existing._rw_adopt(comp)
                return existing
            self._unmount(existing_cid)
        if comp.cid is not None:
            raise ValueError(f"{comp!r} is already mounted elsewhere; create a new instance")
        cid = f"c{next(self._cids)}"
        comp.cid, comp.path, comp._rw_runtime = cid, path, self
        self.components[cid] = comp
        self.paths[path] = cid
        self.parent[cid] = parent
        result = comp.mount()
        if inspect.isawaitable(result):
            await result
        return comp

    async def _resolve(self, items: tuple[Any, ...], frame: Frame, counts: Counter[str]) -> list[Any]:
        out: list[Any] = []
        owner = frame.component
        for item in items:
            if isinstance(item, Component):
                name = type(item).__name__
                if item.key is not None:
                    segment = f"{name}#{item.key}"
                else:
                    segment = f"{name}:{counts[name]}"
                    counts[name] += 1
                out.append(await self._render_component(item, f"{owner.path}/{segment}", owner.cid))
            elif isinstance(item, Node):
                out.append(await self._resolve_node(item, frame, counts))
            elif isinstance(item, (TextNode, RawHTML)):
                out.append(item)
            else:
                out.extend(await self._resolve(tuple(normalize_children([item])), frame, counts))
        return out

    async def _resolve_node(self, node: Node, frame: Frame, counts: Counter[str]) -> Node:
        attrs = [(n, v) for n, v in node.attrs if n != "class"]
        classes = [str(node.attr("class"))] if node.attr("class") else []
        if node.style is not None and node.style:
            classes.append(self.sheet.use(node.style))
        if classes:
            attrs.insert(0, ("class", " ".join(classes)))
        if any(n == "data-rw-menu" for n, _ in attrs):
            self.interactive = True  # the runtime script provides the menu's keyboard support
        for event, handler in node.events:
            attrs.append((f"data-rw-on-{event}", self._register(frame, handler, event)))
        for event, ops in node.client:
            payload = json.dumps([op.to_json() for op in ops], separators=(",", ":"))
            attrs.append((f"data-rw-js-{event}", payload))
            self.interactive = True
        if node.key is not None:
            attrs.append(("data-rw-key", node.key))
        children = await self._resolve(node.children, frame, counts)
        return Node(node.tag, attrs=tuple(attrs), children=tuple(children))

    # -- handlers & dependencies -----------------------------------------------------------

    def _register(self, frame: Frame, handler: Callable[..., Any], event: str) -> str:
        check_signature(handler)
        frame.handler_seq += 1
        cid = frame.component.cid
        assert cid is not None
        hid = f"{cid}.{frame.handler_seq}"
        self.handlers[hid] = (frame.component, handler, event)
        self.component_handlers.setdefault(cid, []).append(hid)
        self.interactive = True
        return hid

    def track(self, cid: str | None, cell: Cell) -> None:
        if cid is None:
            return
        self.deps.setdefault(cell, set()).add(cid)
        self.component_deps.setdefault(cid, set()).add(cell)

    def state_changed(self, cell: Cell) -> None:
        if current_frame.get() is not None:
            raise RuntimeError("state must not be assigned during render(); do it in an event handler or mount()")
        self.dirty.update(self.deps.get(cell, ()))
        if self.tasks:
            self.schedule_push()

    # -- background tasks and server push ------------------------------------------------------

    def spawn(
        self,
        comp: Component,
        fn: Callable[..., Coroutine[Any, Any, Any]],
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
    ) -> asyncio.Task[None]:
        if not inspect.iscoroutinefunction(fn):
            raise TypeError("run_task() needs an async function")
        if self.closed:
            raise RuntimeError("the page is gone")
        assert comp.cid is not None
        self.interactive = True
        self.wants_stream = True
        if self.served:
            self.add_action({"op": "stream"})
        ctx = contextvars.copy_context()
        ctx.run(current_frame.set, None)
        task = asyncio.get_running_loop().create_task(self._run_task(fn, args, kwargs), context=ctx)
        self.tasks[task] = comp.cid
        task.add_done_callback(self.tasks.pop)
        return task

    async def _run_task(
        self, fn: Callable[..., Coroutine[Any, Any, Any]], args: tuple[Any, ...], kwargs: dict[str, Any]
    ) -> None:
        try:
            await fn(*args, **kwargs)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("error in background task %s", getattr(fn, "__qualname__", fn))

    def schedule_push(self) -> None:
        if self._push_scheduled or self.closed:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:  # a state change from a plain thread: the next event will deliver it
            return
        self._push_scheduled = True
        pusher = loop.create_task(self._push())
        self._pushers.add(pusher)
        pusher.add_done_callback(self._pushers.discard)

    async def _push(self) -> None:
        await asyncio.sleep(PUSH_COALESCE_SECONDS)  # coalesce bursts of changes into one batch
        self._push_scheduled = False
        if not self.subscribers or self.closed:
            return  # changes stay dirty and go out when a stream connects
        try:
            async with contextlib.AsyncExitStack() as stack:
                # Same order as event handling (session, then page), so the two can never deadlock.
                if self.session is not None:
                    await stack.enter_async_context(self.session.lock)
                await stack.enter_async_context(self.lock)
                self.refresh_session_state()
                if not self.dirty and not self.actions:
                    return
                patches = await self.flush()
                self.seq += 1
                self.publish(
                    {
                        "v": 1,
                        "seq": self.seq,
                        "patches": patches,
                        "css": self.sheet.drain(),
                        "actions": self.take_actions(),
                    }
                )
        except Exception:
            log.exception("error while pushing page updates")

    def publish(self, batch: dict[str, Any] | None) -> None:
        for queue in list(self.subscribers):
            try:
                queue.put_nowait(batch)
            except asyncio.QueueFull:
                # A client that cannot keep up must resync from scratch.
                self.subscribers.discard(queue)
                while not queue.empty():
                    queue.get_nowait()
                queue.put_nowait(None)

    def subscribe(self) -> asyncio.Queue[dict[str, Any] | None] | None:
        if self.closed or len(self.subscribers) >= MAX_STREAMS_PER_PAGE:
            return None
        queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue(SUBSCRIBER_QUEUE_SIZE)
        self.subscribers.add(queue)
        self.schedule_push()  # deliver anything that changed before the stream connected
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any] | None]) -> None:
        self.subscribers.discard(queue)

    def on_session_changed(self) -> None:
        """Called by the session whenever it changes (from any tab); pushes the result to our streams."""
        if self.subscribers:
            self.schedule_push()

    def watch_session(self) -> None:
        """With ``App(live_session=True)``, follow the session if this page renders any of its data."""
        app = self.context.app
        session = self.session
        if app is None or not app.live_session or session is None or self.closed:
            return
        if not any(cell[0] == "s" for cell in self.deps):
            return
        session.listeners.add(self)
        if not self.wants_stream:
            self.wants_stream = True
            if self.served:
                self.add_action({"op": "stream"})

    def sync_session_revision(self) -> None:
        session = self.context.peek_session()
        if session is not None:
            self.session = session
            self.session_revision = session.revision
        self.watch_session()

    def refresh_session_state(self) -> None:
        """Mark readers of session data dirty if the session changed since we last looked."""
        session = self.context.peek_session()
        if session is None or session.revision == self.session_revision:
            return
        for cell, readers in self.deps.items():
            if cell[0] == "s":
                self.dirty.update(readers)

    def _forget_render(self, cid: str) -> None:
        for hid in self.component_handlers.pop(cid, ()):
            self.handlers.pop(hid, None)
        for cell in self.component_deps.pop(cid, ()):
            readers = self.deps.get(cell)
            if readers is not None:
                readers.discard(cid)
                if not readers:
                    del self.deps[cell]
        self.children[cid] = set()

    def _descendants(self, cid: str) -> set[str]:
        out: set[str] = set()
        stack = list(self.children.get(cid, ()))
        while stack:
            child = stack.pop()
            if child not in out:
                out.add(child)
                stack.extend(self.children.get(child, ()))
        return out

    def _unmount(self, cid: str) -> None:
        for child in self._descendants(cid):
            self._unmount_one(child)
        self._unmount_one(cid)

    def _unmount_one(self, cid: str) -> None:
        comp = self.components.pop(cid, None)
        if comp is None:
            return
        self._forget_render(cid)
        self.rendered.pop(cid, None)
        self.children.pop(cid, None)
        parent = self.parent.pop(cid, None)
        if parent is not None and parent in self.children:
            self.children[parent].discard(cid)
        if comp.path is not None and self.paths.get(comp.path) == cid:
            del self.paths[comp.path]
        self.dirty.discard(cid)
        for task, owner in list(self.tasks.items()):
            if owner == cid:
                task.cancel()
        try:
            comp.unmount()
        finally:
            comp._rw_runtime = None

    # -- events ------------------------------------------------------------------------------

    async def dispatch(
        self, handler_id: str, payload: dict[str, Any], *, timeout: float | None = None, threads: bool = False
    ) -> None:
        entry = self.handlers.get(handler_id)
        if entry is None:
            raise StaleHandlerError()
        _component, handler, event = entry
        args = bind_payload(handler, event, payload)
        await invoke(handler, tuple(args), timeout=timeout, threads=threads)

    async def flush(self) -> list[dict[str, Any]]:
        """Rerender dirty components (outermost first) into morph patches."""
        self.refresh_session_state()
        patches: list[dict[str, Any]] = []
        for _ in range(MAX_FLUSH_PASSES):
            if not self.dirty:
                break
            dirty, self.dirty = self.dirty, set()
            roots = [c for c in dirty if c in self.components and not self._has_dirty_ancestor(c, dirty)]
            roots.sort(key=lambda c: (self.components[c].path or "").count("/"))
            for cid in roots:
                comp = self.components.get(cid)
                if comp is None:
                    continue
                stored = self.rendered.get(cid)
                old = self._assemble(stored) if stored is not None else None
                node = await self.rerender(comp)
                fine = self.context.app is not None and self.context.app.fine_patches and not self.resync
                edits = diff(old, node) if old is not None and fine else None
                if edits is None:
                    patches.append({"op": "morph", "id": cid, "html": to_html(node)})
                elif edits:
                    patches.append({"op": "edit", "id": cid, "edits": edits})
        self.sync_session_revision()
        self.resync = False
        return patches

    def _has_dirty_ancestor(self, cid: str, dirty: set[str]) -> bool:
        parent = self.parent.get(cid)
        while parent is not None:
            if parent in dirty:
                return True
            parent = self.parent.get(parent)
        return False

    def add_action(self, action: dict[str, Any]) -> None:
        self.actions.append(action)

    def take_actions(self) -> list[dict[str, Any]]:
        actions, self.actions = self.actions, []
        return actions

    def dispose(self) -> None:
        """Unmount everything (the page view expired or was evicted)."""
        self.closed = True
        if self.session is not None:
            self.session.listeners.discard(self)
        for cid in list(self.components):
            self._unmount_one(cid)
        for task in list(self.tasks):
            task.cancel()
        self.publish(None)  # closes any open streams

    def allow_event(self, burst: int, per_second: float) -> bool:
        now = time.monotonic()
        self.tokens = min(burst, self.tokens + (now - self.token_stamp) * per_second)
        self.token_stamp = now
        if self.tokens < 1:
            return False
        self.tokens -= 1
        return True
