"""Per-request context: what server-side code may know about the caller."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from fastapi import Request

    from .app import App
    from .backend.database import Database
    from .session import Session

_UNRESOLVED: Any = object()


class Context:
    """Bound to one HTTP request (a page view or an event).

    ``session`` is created lazily, so pages that never touch it set no cookie.
    """

    def __init__(self, app: App | None, request: Request | None = None, session: Session | None = None) -> None:
        self.app = app
        self.request = request
        self._session = session
        self.session_created = False
        self._user: Any = _UNRESOLVED

    @property
    def session(self) -> Session:
        if self._session is None:
            if self.app is None:
                from .session import Session

                self._session = Session("detached")
            else:
                self._session = self.app.sessions.create()
            self.session_created = True
        return self._session

    def peek_session(self) -> Session | None:
        return self._session

    @property
    def user(self) -> Any:
        """The authenticated principal, or ``None``."""
        if self._user is not _UNRESOLVED:
            return self._user
        session = self._session
        return None if session is None else session.user

    def set_user(self, user: Any) -> None:
        """Used by custom authenticators (``App.authenticator``)."""
        self._user = user

    @property
    def db(self) -> Database:
        if self.app is None or self.app.db is None:
            raise RuntimeError("no database configured; pass App(database=...)")
        return self.app.db

    def require_user(self) -> Any:
        from .errors import Unauthorized

        user = self.user
        if user is None:
            raise Unauthorized()
        return user
