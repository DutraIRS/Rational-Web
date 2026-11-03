"""HTTP conventions shared by pages, the event endpoint and remote services."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

from fastapi import Request, WebSocket
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException
from starlette.middleware.cors import CORSMiddleware
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .security import same_text

if TYPE_CHECKING:
    from .session import Session

SESSION_COOKIE = "rw_sid"
THEME_COOKIE = "rw_theme"
CSRF_HEADER = "x-rw-csrf"
_SECURITY_HEADERS = {
    b"x-content-type-options": b"nosniff",
    b"referrer-policy": b"strict-origin-when-cross-origin",
    b"x-frame-options": b"SAMEORIGIN",
}


def base_path(request: Request) -> str:
    """The URL prefix the app is served under (ASGI ``root_path``): ``""`` or e.g. ``"/app"``."""
    return str(request.scope.get("root_path", "")).rstrip("/")


def json_error(
    status: int,
    code: str,
    message: str,
    *,
    details: Any = None,
    headers: Mapping[str, str] | None = None,
    **extra: Any,
) -> JSONResponse:
    """The one error shape every Rational endpoint returns: ``{"error": {code, message, details?}}``."""
    error: dict[str, Any] = {"code": code, "message": message}
    if details is not None:
        error["details"] = details
    return JSONResponse(
        {**extra, "error": error}, status_code=status, headers={"Cache-Control": "no-store", **(headers or {})}
    )


def declared_length(request: Request) -> int:
    """The body size the request announces; 0 if it does not say (chunked encoding)."""
    declared = request.headers.get("content-length", "")
    return int(declared) if declared.isdecimal() else 0


def csrf_ok(request: Request, session: Session) -> bool:
    return same_text(request.headers.get(CSRF_HEADER, ""), session.csrf)


def same_origin(websocket: WebSocket, extra: Sequence[str] = ()) -> bool:
    """True if a WebSocket handshake comes from this site's pages (or from an origin in ``extra``).

    Browsers send cookies on cross-site WebSocket handshakes, so this is what stops another site
    from connecting as the visitor.
    """
    origin, host = websocket.headers.get("origin"), websocket.headers.get("host")
    if not origin:
        return False
    try:
        return origin in extra or (bool(host) and urlsplit(origin).netloc == host)
    except ValueError:  # not a URL
        return False


def is_local_path(value: str) -> bool:
    """True if ``value`` is a path on this site (``"/orders?page=2"``), not a URL to another origin.

    Besides ``https://host`` it refuses ``//host`` and ``/\\host``, and any whitespace or control
    character, because browsers strip those before they parse a URL (``/<TAB>/host`` is ``//host``).
    """
    return (
        value.startswith("/")
        and not value.startswith("//")
        and "\\" not in value
        and not any(ord(c) <= 0x20 or ord(c) == 0x7F for c in value)
    )


def local_path(value: str | None, default: str = "/") -> str:
    """``value`` if it is a path on this site, else ``default``.

    Use it on any redirect target taken from the request, such as a ``?next=`` parameter, so that a
    crafted link cannot send users to another site after they sign in (an open redirect).
    """
    return value if value and is_local_path(value) else default


def request_target(request: Request) -> str:
    """The path and query of ``request`` within the app (without the mount prefix)."""
    path, base = request.url.path, base_path(request)
    if base and path.startswith(base):
        path = path[len(base) :] or "/"
    return f"{path}?{request.url.query}" if request.url.query else path


def content_security_policy(
    nonce: str, *, inline_styles: bool = False, sources: Mapping[str, Sequence[str]] | None = None
) -> str:
    """The ``Content-Security-Policy`` of a page. ``sources`` adds origins to directives, by name."""
    extra = dict(sources or {})

    def directive(name: str, *own: str) -> str:
        return " ".join([name, *own, *extra.pop(name, ())])

    parts = [
        "default-src 'self'",
        directive("script-src", "'self'"),
        directive("style-src", "'self'", "'unsafe-inline'" if inline_styles else f"'nonce-{nonce}'"),
        directive("img-src", "'self'", "data:", "https:"),
    ]
    parts += [directive(name, "'self'") for name in list(extra)]  # frame-src, connect-src...
    parts += ["object-src 'none'", "base-uri 'self'", "frame-ancestors 'self'", "form-action 'self'"]
    return "; ".join(parts)


class ScopedCORS:
    """CORS for the API prefix only; pages and framework assets never get cross-origin access.

    Credentials are never allowed: cross-origin callers authenticate with a bearer token
    (``App.authenticate``), not the session cookie.
    """

    def __init__(self, app: ASGIApp, *, prefix: str, origins: Sequence[str]) -> None:
        self.app = app
        self.prefix = prefix
        self.cors = CORSMiddleware(
            app,
            allow_origins=list(origins),
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
            allow_headers=["Authorization", "Content-Type"],
            allow_credentials=False,
            max_age=600,
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = str(scope.get("path", ""))
        covered = scope["type"] == "http" and (path == self.prefix or path.startswith(self.prefix + "/"))
        await (self.cors if covered else self.app)(scope, receive, send)


class SecurityHeadersMiddleware:
    """Apply baseline security headers to every HTTP response from the framework."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_security_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                present = {name.lower() for name, _ in headers}
                headers.extend((name, value) for name, value in _SECURITY_HEADERS.items() if name not in present)
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_security_headers)


class BodyLimitMiddleware:
    """Refuse request bodies over ``limit`` bytes, before they fill the server's memory.

    A ``Content-Length`` over the limit is answered at once; a body that turns out longer while it
    is being read (chunked encoding) stops at the limit. Either way the answer is 413.
    """

    def __init__(self, app: ASGIApp, *, limit: int) -> None:
        self.app = app
        self.limit = limit

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        declared = next((value for name, value in scope["headers"] if name == b"content-length"), b"")
        if declared.isdigit() and int(declared) > self.limit:
            await json_error(413, "too_large", "Request body too large")(scope, receive, send)
            return
        received = 0

        async def limited() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.limit:
                    raise HTTPException(413, "Request body too large")
            return message

        await self.app(scope, limited, send)
