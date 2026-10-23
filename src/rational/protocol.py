"""The browser <-> server event protocol (v1, HTTP POST).

Request:  ``{v, page, rev, handler, payload}`` + ``X-RW-CSRF`` header + session cookie.
Response: ``{v, rev, patches: [{op: "morph", id, html}], css: [rule], actions: [...], error?, csrf?}``.
"""

from __future__ import annotations

import json
import logging
import time
from typing import TYPE_CHECKING, Any

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ValidationError

from . import dev
from .errors import InvalidInput, RationalError, Redirect
from .http import SESSION_COOKIE, csrf_ok, json_error
from .runtime import StaleHandlerError

if TYPE_CHECKING:
    from .app import App

log = logging.getLogger("rational")

PROTOCOL_VERSION = 1
EVENT_PATH = "/_rational/event"


class EventRequest(BaseModel):
    v: int
    page: str
    rev: int = 0
    handler: str
    payload: dict[str, Any] = {}


def _error(status: int, code: str, message: str) -> JSONResponse:
    return json_error(status, code, message, v=PROTOCOL_VERSION)


async def handle_event(app: App, request: Request) -> Response:
    body = await request.body()
    if len(body) > app.max_event_bytes:
        return _error(413, "too_large", "Event payload too large")
    try:
        event = EventRequest.model_validate(json.loads(body))
    except (ValueError, ValidationError):
        return _error(400, "bad_request", "Malformed event")
    if event.v != PROTOCOL_VERSION:
        return _error(410, "version", "The page is out of date")
    runtime = app.pages.get(event.page)
    if runtime is None:
        return _error(410, "expired", "This page expired")
    session = app.sessions.get(request.cookies.get(SESSION_COOKIE))
    if session is None or session is not runtime.session:
        return _error(403, "forbidden", "Session mismatch")
    if not csrf_ok(request, session):
        return _error(403, "csrf", "Invalid CSRF token")
    if not runtime.allow_event(app.event_burst, app.event_rate):
        return _error(429, "rate_limited", "Too many events")

    ctx = await app.context_for(request, session)
    async with app.session_lock(ctx), runtime.lock:
        if event.rev != runtime.revision:
            return JSONResponse(
                {
                    "v": PROTOCOL_VERSION,
                    "rev": runtime.revision,
                    "patches": [],
                    "css": [],
                    "actions": [{"op": "reload"}],
                    "error": {
                        "code": "stale_revision",
                        "message": "This page changed in another request; reload it before continuing",
                    },
                },
                status_code=409,
                headers={"Cache-Control": "no-store"},
            )
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
            except StaleHandlerError as e:
                # Unknown handler: the browser is out of sync. Resend the whole page instead of failing.
                runtime.dirty.add(runtime.page.cid or "")
                error = e.to_json()
            except Redirect as r:
                runtime.add_action({"op": "navigate", "url": r.url})
            except InvalidInput as e:
                error = e.to_json()  # an expected outcome of user input, not a failed request
            except RationalError as e:
                error, status = e.to_json(), e.status
            except Exception as e:
                log.exception("error in event handler %s", event.handler)
                error, status = {"code": "internal", "message": "Something went wrong"}, 500
                if app.debug:
                    error.update(message=f"{type(e).__name__}: {e}", debug=dev.describe(e))
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
        patches = await runtime.flush()
        runtime.revision += 1
        payload: dict[str, Any] = {
            "v": PROTOCOL_VERSION,
            "rev": runtime.revision,
            "patches": patches,
            "css": runtime.sheet.drain(),
            "actions": runtime.take_actions(),
        }
        if error is not None:
            payload["error"] = error
        if app.commit_session(ctx):
            payload["csrf"] = session.csrf
        response = JSONResponse(payload, status_code=status, headers={"Cache-Control": "no-store"})
        app.finish(request, response, ctx)
        return response
