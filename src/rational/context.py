"""Per-request context: what server-side code may know about the caller."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from fastapi import Request

    from .app import App
    from .backend.database import Database
    from .session import Session

from .i18n import LANG_COOKIE

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
        self._locale: str | None = None

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
    def locale(self) -> str:
        """The negotiated language tag (``App.lang`` when the app has no ``i18n``)."""
        if self._locale is None:
            app = self.app
            if app is None:
                self._locale = "en"
            elif app.i18n is None:
                self._locale = app.lang
            else:
                headers = self.request.headers if self.request is not None else {}
                cookies = self.request.cookies if self.request is not None else {}
                self._locale = app.i18n.negotiate(cookies.get(LANG_COOKIE), headers.get("accept-language"))
        return self._locale

    def t(self, key: str, **params: Any) -> str:
        """Translate ``key`` into this request's locale."""
        if self.app is None or self.app.i18n is None:
            return key
        return self.app.i18n.translate(self.locale, key, **params)

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
