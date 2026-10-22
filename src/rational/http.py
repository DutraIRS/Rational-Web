"""HTTP conventions shared by pages, the event endpoint and remote services."""

from __future__ import annotations

import hmac
from typing import TYPE_CHECKING, Any

from fastapi import Request, Response
from fastapi.responses import JSONResponse

if TYPE_CHECKING:
    from .session import Session

SESSION_COOKIE = "rw_sid"
THEME_COOKIE = "rw_theme"
CSRF_HEADER = "x-rw-csrf"


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
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    if nonce is not None:
        style_src = "'self' 'unsafe-inline'" if inline_styles else f"'self' 'nonce-{nonce}'"
        response.headers["Content-Security-Policy"] = (
            f"default-src 'self'; script-src 'self'; style-src {style_src}; img-src 'self' data: https:; "
            "object-src 'none'; base-uri 'self'; frame-ancestors 'self'; form-action 'self'"
        )
