"""HTTP conventions shared by pages, the event endpoint and remote services."""

from __future__ import annotations

import hmac
from typing import TYPE_CHECKING, Any

from fastapi import Request, Response
from fastapi.responses import JSONResponse
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
    return hmac.compare_digest(request.headers.get(CSRF_HEADER, ""), session.csrf)


def security_headers(response: Response, nonce: str | None, *, inline_styles: bool = False) -> None:
    for name, value in _SECURITY_HEADERS.values():
        response.headers[name.decode("ascii")] = value.decode("ascii")
    if nonce is not None:
        style_src = "'self' 'unsafe-inline'" if inline_styles else f"'self' 'nonce-{nonce}'"
        response.headers["Content-Security-Policy"] = (
            f"default-src 'self'; script-src 'self'; style-src {style_src}; img-src 'self' data: https:; "
            "object-src 'none'; base-uri 'self'; frame-ancestors 'self'; form-action 'self'"
        )


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
