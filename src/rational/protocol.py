"""The browser <-> server event protocol (v1, HTTP POST).

Request:  ``{v, page, rev, handler, payload}`` + ``X-RW-CSRF`` header + session cookie.
Response: ``{v, rev, patches, css: [rule], actions: [...], error?, csrf?}`` where a patch is
``{op: "morph", id, html}`` or ``{op: "edit", id, edits}``.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any

from fastapi import Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ValidationError

from . import dev
from .errors import InvalidInput, RationalError, Redirect
from .http import SESSION_COOKIE, base_path, csrf_ok, declared_length, json_error, same_origin
from .runtime import PageRuntime, StaleHandlerError

if TYPE_CHECKING:
    from .app import App
    from .context import Context

PROTOCOL_VERSION = 1
EVENT_PATH = "/_rational/event"
CSRF_PATH = "/_rational/csrf"
STREAM_PATH = "/_rational/stream"
WS_PATH = "/_rational/ws"
STREAM_KEEPALIVE_SECONDS = 15


class EventRequest(BaseModel):
    v: int
    page: str
    rev: int = 0
    handler: str
    payload: dict[str, Any] = {}


def _error(status: int, code: str, message: str) -> JSONResponse:
    return json_error(status, code, message, v=PROTOCOL_VERSION)


def _stale(runtime: PageRuntime, message: str) -> JSONResponse:
    """409: the browser's view of the page is out of date; it reloads."""
    return JSONResponse(
        {
            "v": PROTOCOL_VERSION,
            "rev": runtime.revision,
            "patches": [],
            "css": [],
            "actions": [{"op": "reload"}],
            "error": {"code": "stale_revision", "message": message},
        },
        status_code=409,
        headers={"Cache-Control": "no-store"},
    )


async def _failure(
    app: App, runtime: PageRuntime, exc: Exception, request: Request, ctx: Context, handler: str
) -> tuple[dict[str, Any] | None, int]:
    """What the browser hears about an exception from a handler or a re-render: its error and status."""
    if isinstance(exc, Redirect):
        runtime.add_action({"op": "navigate", "url": exc.url})
        return None, 200
    if isinstance(exc, StaleHandlerError):
        runtime.resend()  # unknown handler: the browser is out of sync, so it gets the whole page
        return exc.to_json(), 200
    if isinstance(exc, InvalidInput):
        return exc.to_json(), 200  # an expected outcome of user input, not a failed request
    if isinstance(exc, RationalError):
        return exc.to_json(), exc.status
    await app.report_error(
        exc, "event", f"error in event handler {handler}", request=request, context=ctx, handler=handler
    )
    error: dict[str, Any] = {"code": "internal", "message": "Something went wrong"}
    if app.debug:
        error.update(message=f"{type(exc).__name__}: {exc}", debug=dev.describe(exc))
    return error, 500


async def handle_event(app: App, request: Request) -> Response:
    if declared_length(request) > app.max_event_bytes or len(body := await request.body()) > app.max_event_bytes:
        return _error(413, "too_large", "Event payload too large")
    try:
        event = EventRequest.model_validate(json.loads(body))
    except (ValueError, ValidationError):
        return _error(400, "bad_request", "Malformed event")
    if event.v != PROTOCOL_VERSION:
        return _error(410, "version", "The page is out of date")
    runtime = await app.page_for(request, event.page, rev=event.rev)
    if runtime is None:
        return _error(410, "expired", "This page expired")
    session = await app.load_session(request)
    if session is None or session is not runtime.session:
        return _error(403, "session", "Session mismatch")
    if not csrf_ok(request, session):
        return _error(403, "csrf", "Invalid CSRF token")
    if not runtime.allow_event(app.event_burst, app.event_rate):
        return _error(429, "rate_limited", "Too many events")

    ctx = await app.context_for(request, session)
    if runtime.requires_user and ctx.user is None:
        return _stale(runtime, "Please sign in to continue")  # the reload leads to the login page
    async with app.session_lock(ctx), runtime.lock:
        if event.rev != runtime.revision:
            return _stale(runtime, "This page changed in another request; reload it before continuing")
        runtime.context = ctx
        runtime.refresh_session_state()
        error: dict[str, Any] | None = None
        status = 200
        event_started = time.perf_counter()
        with app.logging.span(
            "rational.event.dispatch",
            {"event.handler": event.handler, "page.id": event.page},
        ) as span:
            try:
                await runtime.dispatch(
                    event.handler,
                    event.payload,
                    timeout=app.handler_timeout,
                    threads=app.sync_handlers == "thread",
                )
            except Exception as e:
                error, status = await _failure(app, runtime, e, request, ctx, event.handler)
            finally:
                duration_ms = (time.perf_counter() - event_started) * 1000
                app.logging.finish_span(
                    span,
                    **{
                        "rational.event.duration_ms": duration_ms,
                        "rational.event.status_code": status,
                    },
                )
                app.logging.record(
                    "event.dispatch.completed",
                    level=logging.WARNING if status >= 500 else logging.INFO,
                    handler=event.handler,
                    page_id=event.page,
                    duration_ms=duration_ms,
                    status_code=status,
                    error_code=error.get("code") if error else None,
                )
        patches: list[dict[str, Any]] = []
        try:
            patches = await runtime.flush()
        except Exception as e:  # a re-render failed: the page stays usable, and the next event resends it
            runtime.resend()
            failure = await _failure(app, runtime, e, request, ctx, event.handler)
            if failure[0] is not None:
                error, status = failure
        stored_revision = runtime.revision
        runtime.revision += 1
        runtime.seq += 1
        if app.resume is not None and not await app.resume.save(runtime, expect_revision=stored_revision):
            # Another worker advanced this page concurrently: this copy has diverged, drop it.
            app.pages.pop(runtime.id)
            runtime.dispose()
            response = _stale(runtime, "This page changed on another server; reload it before continuing")
        else:
            payload: dict[str, Any] = {
                "v": PROTOCOL_VERSION,
                "rev": runtime.revision,
                "seq": runtime.seq,
                "patches": patches,
                "css": runtime.sheet.drain(),
                "actions": runtime.take_actions(),
            }
            if error is not None:
                payload["error"] = error
            scripts = runtime.take_scripts(base_path(request))
            if scripts:
                payload["load"] = scripts
            if await app.commit_session(ctx):
                payload["csrf"] = session.csrf
            response = JSONResponse(payload, status_code=status, headers={"Cache-Control": "no-store"})
        await app.finish(request, response, ctx)
        return response


async def handle_stream(app: App, request: Request) -> Response:
    """``GET /_rational/stream?page=ID``: server-sent events carrying patches pushed by background tasks."""
    runtime = await app.page_for(request, request.query_params.get("page"))
    if runtime is None:
        return _error(410, "expired", "This page expired")
    session = await app.load_session(request)
    if session is None or session is not runtime.session:
        return _error(403, "session", "Session mismatch")
    if runtime.requires_user and (await app.context_for(request, session)).user is None:
        return _error(403, "session", "Please sign in to continue")
    queue = runtime.subscribe()
    if queue is None:
        return _error(429, "too_many_streams", "Too many open streams for this page")

    def frame(data: dict[str, Any]) -> str:
        return f"data: {json.dumps(data, separators=(',', ':'))}\n\n"

    async def events() -> AsyncIterator[str]:
        try:
            yield frame({"hello": runtime.seq})
            while True:
                try:
                    batch = await asyncio.wait_for(queue.get(), STREAM_KEEPALIVE_SECONDS)
                except TimeoutError:
                    app.pages.get(runtime.id)  # an open stream keeps the page alive
                    yield ": keepalive\n\n"
                    continue
                if batch is None:
                    return
                yield frame(batch)
        finally:
            runtime.unsubscribe(queue)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


async def handle_websocket(app: App, websocket: WebSocket) -> None:
    """``/_rational/ws?page=ID``: the push stream over a WebSocket. Events still travel over POST."""
    runtime = app.pages.get(websocket.query_params.get("page"))
    session = await app.sessions.load(websocket.cookies.get(SESSION_COOKIE))
    if runtime is None or session is None or session is not runtime.session or not same_origin(websocket):
        await websocket.close(code=1008)
        return
    if runtime.requires_user and (await app.websocket_context(websocket, session)).user is None:
        await websocket.close(code=1008)
        return
    queue = runtime.subscribe()
    if queue is None:
        await websocket.close(code=1013)
        return
    await websocket.accept()

    async def watch_disconnect() -> None:
        with contextlib.suppress(Exception):  # a close, or a frame nobody should have sent: the end either way
            while True:
                await websocket.receive_text()  # clients send nothing; this only notices the close

    watcher = asyncio.create_task(watch_disconnect())
    try:
        await websocket.send_json({"hello": runtime.seq})
        while not watcher.done():
            getter = asyncio.ensure_future(queue.get())
            await asyncio.wait({getter, watcher}, timeout=STREAM_KEEPALIVE_SECONDS, return_when=asyncio.FIRST_COMPLETED)
            if not getter.done():
                getter.cancel()
                app.pages.get(runtime.id)  # an open socket keeps the page alive
                continue
            batch = getter.result()
            if batch is None:
                break
            await websocket.send_json(batch)
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        watcher.cancel()
        runtime.unsubscribe(queue)
        with contextlib.suppress(RuntimeError):
            await websocket.close()
