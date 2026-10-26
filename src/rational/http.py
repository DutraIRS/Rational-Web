"""HTTP conventions shared by pages, the event endpoint and remote services."""

from __future__ import annotations

import hmac
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.cors import CORSMiddleware
from starlette.types import ASGIApp, Message, Receive, Scope, Send

if TYPE_CHECKING:
    from .session import Session

SESSION_COOKIE = "rw_sid"
THEME_COOKIE = "rw_theme"
CSRF_HEADER = "x-rw-csrf"
_SECURITY_HEADERS = {
    b"x-content-type-options": (b"X-Content-Type-Options", b"nosniff"),
    b"referrer-policy": (b"Referrer-Policy", b"strict-origin-when-cross-origin"),
    b"x-frame-options": (b"X-Frame-Options", b"SAMEORIGIN"),
}


def base_path(request: Request) -> str:
    """The URL prefix the app is served under (ASGI ``root_path``): ``""`` or e.g. ``"/app"``."""
    return str(request.scope.get("root_path", "")).rstrip("/")


def json_error(status: int, code: str, message: str, *, details: Any = None, **extra: Any) -> JSONResponse:
    """The one error shape every Rational endpoint returns: ``{"error": {code, message, details?}}``."""
    error: dict[str, Any] = {"code": code, "message": message}
    if details is not None:
        error["details"] = details
    return JSONResponse({**extra, "error": error}, status_code=status, headers={"Cache-Control": "no-store"})


def csrf_ok(request: Request, session: Session) -> bool:
    # Compared as bytes: a header with non-ASCII characters must fail the check, not raise.
    return hmac.compare_digest(request.headers.get(CSRF_HEADER, "").encode("latin-1"), session.csrf.encode())


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


def security_headers(
    response: Response,
    nonce: str | None,
    *,
    inline_styles: bool = False,
    style_origins: Sequence[str] = (),
    script_origins: Sequence[str] = (),
) -> None:
    for name, value in _SECURITY_HEADERS.values():
        response.headers[name.decode("ascii")] = value.decode("ascii")
    if nonce is not None:
        style_src = "'self' 'unsafe-inline'" if inline_styles else f"'self' 'nonce-{nonce}'"
        style_src = " ".join([style_src, *style_origins])
        script_src = " ".join(["'self'", *script_origins])
        response.headers["Content-Security-Policy"] = (
            f"default-src 'self'; script-src {script_src}; style-src {style_src}; img-src 'self' data: https:; "
            "object-src 'none'; base-uri 'self'; frame-ancestors 'self'; form-action 'self'"
        )


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
                headers.extend(header for key, header in _SECURITY_HEADERS.items() if key not in present)
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_security_headers)
