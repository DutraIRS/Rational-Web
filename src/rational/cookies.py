"""Cookies for your app: ``ctx.cookies`` (``self.context.cookies`` in components and services).

Plain cookies hold text; ``signed=True`` cookies hold JSON data the browser can read but not change;
``encrypted=True`` cookies hold JSON data it can neither read nor change (needs ``rational[crypto]``).
Signed and encrypted cookies use ``App(secret_key=...)``. Defaults are safe: ``HttpOnly``,
``SameSite=Lax``, ``Secure`` over HTTPS, path ``/``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from .security import Box, InvalidToken, Signer

if TYPE_CHECKING:
    from fastapi import Response

    from .app import App
    from .context import Context

RESERVED_PREFIX = "rw_"  # rw_sid, rw_theme, rw_lang, rw_oauth...


@dataclass(frozen=True)
class _Pending:
    value: str | None  # None: delete
    max_age: int | None
    httponly: bool
    samesite: Literal["lax", "strict", "none"]
    path: str


class Cookies:
    """Read the request's cookies and set the response's."""

    def __init__(self, context: Context) -> None:
        self._context = context
        self._pending: dict[str, _Pending] = {}

    def _incoming(self, name: str) -> str | None:
        request = self._context.request
        return request.cookies.get(name) if request is not None else None

    def get(
        self,
        name: str,
        default: Any = None,
        *,
        signed: bool = False,
        encrypted: bool = False,
        max_age: float | None = None,
    ) -> Any:
        """The cookie's value, or ``default`` if it is missing, forged or (``max_age``) too old."""
        pending = self._pending.get(name)
        raw = pending.value if pending is not None else self._incoming(name)
        if raw is None:
            return default
        if not (signed or encrypted):
            return raw
        try:
            return self._box().open(raw) if encrypted else self._signer().unsign(raw, max_age=max_age)
        except InvalidToken:
            return default

    def set(
        self,
        name: str,
        value: Any,
        *,
        max_age: int | None = None,
        signed: bool = False,
        encrypted: bool = False,
        httponly: bool = True,
        samesite: Literal["lax", "strict", "none"] = "lax",
        path: str = "/",
    ) -> None:
        """Set a cookie on the response. ``value`` is text, or any JSON data when signed or encrypted."""
        if name.startswith(RESERVED_PREFIX):
            raise ValueError(f"{name!r} is used by the framework; pick another cookie name")
        if signed or encrypted:
            text = self._box().seal(value) if encrypted else self._signer().sign(value)
        elif isinstance(value, str):
            text = value
        else:
            raise TypeError("plain cookies hold text; use signed=True or encrypted=True for other data")
        self._pending[name] = _Pending(text, max_age, httponly, samesite, path)

    def delete(self, name: str, *, path: str = "/") -> None:
        if name.startswith(RESERVED_PREFIX):
            raise ValueError(f"{name!r} is used by the framework")
        self._pending[name] = _Pending(None, None, True, "lax", path)

    def apply(self, response: Response, *, secure: bool) -> None:
        for name, c in self._pending.items():
            if c.value is None:
                response.delete_cookie(name, path=c.path)
            else:
                response.set_cookie(
                    name,
                    c.value,
                    max_age=c.max_age,
                    httponly=c.httponly,
                    samesite=c.samesite,
                    secure=secure or c.samesite == "none",
                    path=c.path,
                )

    def _signer(self) -> Signer:
        return self._app().signer("rational.cookie")

    def _box(self) -> Box:
        return self._app().box("rational.cookie")

    def _app(self) -> App:
        app = self._context.app
        if app is None:
            raise RuntimeError("signed and encrypted cookies need an App")
        return app
