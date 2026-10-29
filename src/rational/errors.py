"""Exceptions that cross the client/server boundary as structured, safe errors."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from fastapi import Request


@dataclass(frozen=True)
class ErrorInfo:
    """What ``app.on_error`` receives: an unhandled exception and where it happened.

    ``kind`` is one of ``"page"``, ``"event"``, ``"remote"`` or ``"job"``. ``request`` is the
    incoming request for the first three and ``None`` for jobs. ``context`` is the page or
    request context when one exists. ``extra`` carries per-kind detail: the handler id for
    events, the service and method for remotes, the job name and attempt for jobs.
    """

    exc: BaseException
    kind: str
    request: Request | None = None
    context: Any = None
    extra: dict[str, Any] = field(default_factory=dict)


class RationalError(Exception):
    """Base for errors whose ``message`` is safe to show to the user."""

    status: int = 400
    code: str = "error"

    def __init__(
        self, message: str = "", *, code: str | None = None, status: int | None = None, details: Any = None
    ) -> None:
        super().__init__(message or self.__class__.__name__)
        self.message = message or self.default_message()
        if code is not None:
            self.code = code
        if status is not None:
            self.status = status
        self.details = details

    def default_message(self) -> str:
        return "Request failed"

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.details is not None:
            out["details"] = self.details
        return out


class RemoteError(RationalError):
    """Raise from services or handlers to report a user-facing failure."""


class InvalidInput(RationalError):
    """User input that cannot be accepted. ``details`` lists ``{"field", "message"}`` items,
    which the browser runtime shows next to the matching form fields."""

    status = 422
    code = "validation_error"

    def default_message(self) -> str:
        return "Please correct the highlighted fields"


class FieldError(InvalidInput):
    """Reject one or more form fields from a handler or service::

        raise FieldError("email", "This email is already registered")
        raise FieldError({"password": "Too short", "confirm": "Does not match"})

    Each message is shown under the matching form field; the JSON API answers 422.
    """

    def __init__(self, field: str | dict[str, str], message: str = "") -> None:
        errors = field if isinstance(field, dict) else {field: message}
        super().__init__(details=[{"field": f, "message": m} for f, m in errors.items()])


class Unauthorized(RationalError):
    status = 401
    code = "unauthorized"

    def default_message(self) -> str:
        return "Authentication required"


class Forbidden(RationalError):
    status = 403
    code = "forbidden"

    def default_message(self) -> str:
        return "Not allowed"


class NotFound(RationalError):
    status = 404
    code = "not_found"

    def default_message(self) -> str:
        return "Not found"


class Redirect(Exception):  # noqa: N818 - control flow, not an error
    """Raise during a page render or an event to send the browser elsewhere.

    ``url`` is a path on this site or an ``http(s)`` URL. Never pass a value taken from the request
    unchecked: wrap it in :func:`rational.local_path` first.
    """

    def __init__(self, url: str, status: int = 303) -> None:
        from .rendering.nodes import check_url  # imported here: errors must not depend on rendering at import

        check_url(url)  # no javascript:, vbscript: or data: targets
        super().__init__(url)
        self.url = url
        self.status = status


def redirect(url: str) -> Redirect:
    """``raise redirect("/login")``"""
    return Redirect(url)
