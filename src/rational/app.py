"""``App``: the composition root. Configuration, registration, sessions and the ASGI entry point."""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import logging
import secrets
import traceback
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from contextlib import asynccontextmanager
from importlib import resources
from typing import TYPE_CHECKING, Any, TypeVar

from fastapi import FastAPI, Request, Response, WebSocket
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import HTMLResponse, PlainTextResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import Receive, Scope, Send

from .apidocs import swagger_html
from .assets import Adapter, Asset, as_asset, render_assets
from .component import Page
from .concurrency import SyncHandlers
from .context import Context
from .dev import BOOT_PATH, DEV_SCRIPT_PATH, is_dev_environment
from .dev import error_page as dev_error_page
from .http import SESSION_COOKIE, THEME_COOKIE, ScopedCORS, SecurityHeadersMiddleware, base_path
from .i18n import I18n
from .logging import Logging, TelemetryMiddleware
from .pages import PageRoute, error_page
from .protocol import EVENT_PATH, STREAM_PATH, WS_PATH, handle_event, handle_stream, handle_websocket
from .resume import PageResumer
from .router import Router
from .runtime import PageRuntime
from .session import Session, SessionBackend, SessionStore, TTLStore
from .styling.compiler import StyleCompiler
from .styling.responsive import Breakpoint
from .styling.theme import Theme, ThemeMode, get_theme

if TYPE_CHECKING:
    from .backend.database import Database
    from .bus import Bus
    from .stores import SessionDriver

log = logging.getLogger("rational")

P = TypeVar("P", bound=type[Page])
T = TypeVar("T", bound=type)

_IMMUTABLE = {"Cache-Control": "public, max-age=31536000, immutable"}


class App:
    """A Rational Web application, and an ASGI app (``uvicorn module:app``).

    One origin serves pages at ``/``, ``@remote`` services under ``api_prefix`` (default
    ``/api``, with OpenAPI docs at ``/api/docs``) and framework assets under ``/_rational``.
    Run it with ``python app.py --dev`` or ``--prod`` (see :mod:`rational.cli`).

    Page views are held in process memory: run a single worker, or use sticky sessions.
    """

    def __init__(
        self,
        *,
        title: str = "Rational App",
        description: str | None = None,
        version: str = "0.1.0",
        theme: str | Theme = "modern",
        theme_mode: ThemeMode = "system",
        lang: str = "en",
        database: str | Database | None = None,
        breakpoints: Mapping[str, Breakpoint] | None = None,
        containers: Mapping[str, Breakpoint] | None = None,
        login_path: str | None = None,
        debug: bool | None = None,
        api_prefix: str = "/api",
        api_docs: bool = True,
        favicon: str | None = None,
        secure_cookies: bool | None = None,
        csp: bool = False,
        session_store: SessionBackend | None = None,
        session_ttl: float = 24 * 60 * 60,
        page_ttl: float = 30 * 60,
        max_pages: int = 5_000,
        event_burst: int = 40,
        event_rate: float = 20.0,
        max_event_bytes: int = 64 * 1024,
        handler_timeout: float | None = None,
        sync_handlers: SyncHandlers = "loop",
        client_nav: bool = False,
        live_session: bool = False,
        api_only: bool = False,
        cors_origins: Sequence[str] = (),
        fine_patches: bool = True,
        websocket: bool = False,
        page_snapshots: SessionDriver | None = None,
        page_snapshot_ttl: int = 60 * 60 * 24,
        bus: Bus | None = None,
        i18n: I18n | None = None,
        adapter: Adapter | None = None,
        stylesheets: Sequence[str | Asset] = (),
        scripts: Sequence[str | Asset] = (),
    ) -> None:
        if handler_timeout is not None and handler_timeout <= 0:
            raise ValueError("handler_timeout must be a positive number of seconds or None")
        if sync_handlers not in ("loop", "thread"):
            raise ValueError("sync_handlers must be 'loop' or 'thread'")
        if "*" in cors_origins and len(cors_origins) > 1:
            raise ValueError("cors_origins: use '*' on its own, or list the allowed origins")
        self.api_only = api_only
        self.fine_patches = fine_patches
        self.websocket = websocket and not api_only
        self.i18n = i18n
        if adapter is not None and adapter.needs_inline_styles and csp:
            raise ValueError(f"this adapter needs inline styles and cannot be used with csp=True ({adapter.notes})")
        self.stylesheets = (*(adapter.stylesheets if adapter else ()), *map(as_asset, stylesheets))
        self.scripts = (*(adapter.scripts if adapter else ()), *map(as_asset, scripts))
        self.cors_origins = tuple(cors_origins)
        self.handler_timeout = handler_timeout
        self.sync_handlers = sync_handlers
        self.client_nav = client_nav
        self.live_session = live_session
        self.title = title
        self.api_docs = api_docs
        self.theme = get_theme(theme)
        self.theme_mode = theme_mode
        self.lang = lang
        self.login_path = login_path
        self.debug = is_dev_environment() if debug is None else debug
        self.api_prefix = "/" + api_prefix.strip("/")
        self.favicon = favicon
        self.boot_id = secrets.token_hex(8)
        self.secure_cookies = secure_cookies
        self.csp = csp
        self.session_ttl = session_ttl
        self.event_burst = event_burst
        self.event_rate = event_rate
        self.max_event_bytes = max_event_bytes
        self.logging = Logging()

        self.compiler = StyleCompiler(self.theme, breakpoints, containers)
        self.sessions: SessionBackend = session_store or SessionStore(ttl=session_ttl)
        self.bus = bus
        self._followed: dict[str, Any] = {}
        if bus is not None and hasattr(self.sessions, "on_saved"):
            self.sessions.on_saved = self._announce_session
        self.pages: TTLStore[PageRuntime] = TTLStore(page_ttl, max_pages, on_evict=PageRuntime.dispose)
        self.routes: dict[type[Page], PageRoute] = {}
        self.resume: PageResumer | None = (
            PageResumer(self, page_snapshots, page_snapshot_ttl) if page_snapshots is not None else None
        )
        self.services: list[type] = []
        self.authenticator: Callable[[Context], Any] | None = None
        self._startup: list[Callable[[], Any]] = []
        self._startup_error: BaseException | None = None
        self._requests = 0

        if isinstance(database, str):
            from .backend.database import Database

            database = Database(database)
        self.db: Database | None = database

        self.theme_css = self.theme.css(theme_mode)
        self.theme_href = f"/_rational/theme.css?v={_digest(self.theme_css)}"
        static = resources.files("rational").joinpath("static")
        self.runtime_js = static.joinpath("runtime.js").read_text("utf-8")
        self.dev_js = static.joinpath("dev.js").read_text("utf-8")
        self.runtime_src = f"/_rational/runtime.js?v={_digest(self.runtime_js)}"

        self.fastapi = FastAPI(
            title=title,
            description=description or "",
            version=version,
            lifespan=self._lifespan,
            docs_url=None,  # replaced by a CSRF-aware Swagger UI page, see rational.apidocs
            redoc_url=None,
            openapi_url=f"{self.api_prefix}/openapi.json" if api_docs else None,
        )
        self.fastapi.add_middleware(TelemetryMiddleware, telemetry=self.logging)
        self.fastapi.add_middleware(SecurityHeadersMiddleware)
        if self.cors_origins:
            self.fastapi.add_middleware(ScopedCORS, prefix=self.api_prefix, origins=self.cors_origins)
        page_routes: list[tuple[str, Callable[..., Any], str]] = [
            ("/_rational/runtime.js", self._asset(self.runtime_js, "text/javascript"), "GET"),
            ("/_rational/theme.css", self._asset(self.theme_css, "text/css"), "GET"),
            (EVENT_PATH, self._event, "POST"),
            (STREAM_PATH, self._stream, "GET"),
        ]
        routes: list[tuple[str, Callable[..., Any], str]] = [
            *([(f"{self.api_prefix}/docs", self._api_docs, "GET")] if api_docs else []),
            *([] if api_only else page_routes),
            (DEV_SCRIPT_PATH, self._dev_script, "GET"),
            (BOOT_PATH, self._dev_boot, "GET"),
        ]
        for path, endpoint, method in routes:
            self.fastapi.add_api_route(path, endpoint, methods=[method], include_in_schema=False)
        if self.websocket:
            self.fastapi.add_api_websocket_route(WS_PATH, self._ws)
        self.fastapi.add_exception_handler(StarletteHTTPException, self._http_error)  # type: ignore[arg-type]
        self.fastapi.add_exception_handler(Exception, self._server_error)

    # -- registration ------------------------------------------------------------------

    def page(self, path: str, *, title: str | None = None, auth: str | None = None) -> Callable[[P], P]:
        """Register a ``Page`` subclass at ``path``. ``{name}`` segments become typed props."""
        if self.api_only:
            raise TypeError("this App is api_only=True and serves no pages; remove api_only or use @app.service")

        def decorator(cls: P) -> P:
            if not (isinstance(cls, type) and issubclass(cls, Page)):
                raise TypeError("@app.page decorates Page subclasses")
            route = PageRoute(self, path, cls, title, auth)

            async def endpoint(request: Request) -> Response:
                return await route(request)

            endpoint.__signature__ = inspect.Signature(  # type: ignore[attr-defined]
                [
                    inspect.Parameter(
                        "request",
                        inspect.Parameter.POSITIONAL_OR_KEYWORD,
                        annotation=Request,
                    )
                ],
                return_annotation=Response,
            )
            self.fastapi.add_api_route(
                path,
                endpoint,
                methods=["GET"],
                response_model=None,
                include_in_schema=False,
                name=cls.__name__,
            )
            self.routes[cls] = route
            return cls

        return decorator

    def service(self, cls: T) -> T:
        """Register a ``Service``: each ``@remote`` method becomes a typed HTTP endpoint."""
        from .backend.services import register_service

        register_service(self, cls)
        self.services.append(cls)
        return cls

    def include(self, router: Router) -> None:
        """Register everything a :class:`~rational.Router` recorded: pages, services and startup hooks."""
        for entry in router.pages:
            self.page(entry.path, title=entry.title, auth=entry.auth)(entry.page)
        for service in router.services:
            self.service(service)
        for hook in router.startup:
            self.on_startup(hook)

    def url_for(self, page: type[Page], **params: Any) -> str:
        return self.routes[page].url(**params)

    def on_startup(self, fn: Callable[[], Any]) -> Callable[[], Any]:
        self._startup.append(fn)
        return fn

    def authenticate(self, fn: Callable[[Context], Any]) -> Callable[[Context], Any]:
        """Replace the default authenticator (``session.user``).

        ``fn(context)`` (sync or async) returns the principal or ``None``; it runs once per request.
        """
        self.authenticator = fn
        return fn

    def static(self, path: str, directory: str) -> None:
        from fastapi.staticfiles import StaticFiles

        self.fastapi.mount(path, StaticFiles(directory=directory), name=f"static:{path}")

    def run(self, argv: list[str] | None = None, **overrides: Any) -> None:
        """Serve from the command line: ``python app.py --dev`` or ``python app.py --prod``.

        ``argv`` defaults to ``sys.argv[1:]``; keyword ``overrides`` (``mode``, ``host``, ``port``
        and any uvicorn option) take precedence. See :mod:`rational.cli`.
        """
        from .cli import serve

        serve(self, argv, **overrides)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            self._startup_error is not None
            and scope["type"] == "http"
            and not scope["path"].endswith((DEV_SCRIPT_PATH, BOOT_PATH))
        ):
            await dev_error_page(Request(scope), self._startup_error, stage="while starting the app")(
                scope, receive, send
            )
            return
        await self.fastapi(scope, receive, send)

    # -- request context & sessions -----------------------------------------------------------

    async def load_session(self, request: Request) -> Session | None:
        return await self.sessions.load(request.cookies.get(SESSION_COOKIE))

    async def context_for(self, request: Request, session: Any = None) -> Context:
        if session is None:
            session = await self.load_session(request)
        ctx = Context(self, request, session)
        request.state.rational_context = ctx
        if self.authenticator is not None:
            user = self.authenticator(ctx)
            if inspect.isawaitable(user):
                user = await user
            ctx.set_user(user)
        return ctx

    def commit_session(self, ctx: Context) -> bool:
        """Apply a pending id rotation. Returns True if the browser needs a new cookie."""
        session = ctx.peek_session()
        if session is None:
            return False
        if session.rotated:
            self.sessions.rotate(session)
            session.rotated = False
            ctx.session_created = True
        return ctx.session_created

    def finish(self, request: Request, response: Response, ctx: Context) -> None:
        """Persist session changes (creation, id rotation) into the response cookie."""
        if self.commit_session(ctx):
            secure = self.secure_cookies if self.secure_cookies is not None else request.url.scheme == "https"
            response.set_cookie(
                SESSION_COOKIE,
                ctx.session.id,
                max_age=int(self.session_ttl),
                httponly=True,
                samesite="lax",
                secure=secure,
                path="/",
            )

    @asynccontextmanager
    async def session_lock(self, ctx: Context) -> AsyncIterator[None]:
        """Serialize requests that mutate a session shared by multiple pages, then persist it."""
        session = ctx.peek_session()
        if session is None:
            try:
                yield
            finally:
                created = ctx.peek_session()  # the request may have created the session meanwhile
                if created is not None:
                    await self.sessions.save(created)
            return
        async with session.lock:
            try:
                yield
            finally:
                await self.sessions.save(ctx.peek_session() or session)

    def data_theme(self, request: Request) -> str | None:
        chosen = request.cookies.get(THEME_COOKIE)
        if chosen in ("light", "dark"):
            return chosen
        return None if self.theme_mode == "system" else self.theme_mode

    def housekeeping(self) -> None:
        self._requests += 1
        if self._requests % 500 == 0:
            self.pages.sweep()
            self.sessions.sweep()

    # -- endpoints ---------------------------------------------------------------------------------

    async def _event(self, request: Request) -> Response:
        return await handle_event(self, request)

    async def _stream(self, request: Request) -> Response:
        return await handle_stream(self, request)

    async def page_for(self, request: Request, page_id: str | None) -> PageRuntime | None:
        """The live runtime for ``page_id``, resumed from a snapshot when the app keeps them."""
        live = self.pages.get(page_id)
        if live is not None or self.resume is None:
            return live
        return await self.resume.resume(request, page_id)

    async def _ws(self, websocket: WebSocket) -> None:
        await handle_websocket(self, websocket)

    async def _api_docs(self, request: Request) -> Response:
        session = (await self.context_for(request)).peek_session()
        html = swagger_html(
            title=self.title,
            openapi_url=f"{base_path(request)}{self.api_prefix}/openapi.json",
            csrf=session.csrf if session else None,
        )
        return HTMLResponse(html, headers={"Cache-Control": "no-store"})

    def head_extra(self, nonce: str | None, base: str = "") -> str:
        """Configured stylesheets and scripts, then the dev script (debug only)."""
        return render_assets(self.stylesheets, self.scripts, base, nonce) + self.dev_head(nonce, base)

    @property
    def style_origins(self) -> list[str]:
        return sorted({a.origin for a in self.stylesheets if a.origin})

    @property
    def script_origins(self) -> list[str]:
        return sorted({a.origin for a in self.scripts if a.origin})

    def dev_head(self, nonce: str | None, base: str = "") -> str:
        """The live-reload/error-overlay script tag, in debug mode only."""
        if not self.debug:
            return ""
        nonce_attr = f' nonce="{nonce}"' if nonce else ""
        return f'<script src="{base}{DEV_SCRIPT_PATH}" defer{nonce_attr}></script>'

    async def _dev_script(self) -> Response:
        if not self.debug:
            return Response(status_code=404)
        return Response(self.dev_js, media_type="text/javascript", headers={"Cache-Control": "no-store"})

    async def _dev_boot(self) -> Response:
        if not self.debug:
            return Response(status_code=404)
        return PlainTextResponse(self.boot_id, headers={"Cache-Control": "no-store"})

    async def _http_error(self, request: Request, exc: StarletteHTTPException) -> Response:
        wants_html = "text/html" in request.headers.get("accept", "")
        if wants_html and request.method == "GET" and not request.url.path.startswith("/_rational/"):
            message = "Page not found" if exc.status_code == 404 else str(exc.detail)
            return error_page(self, request, exc.status_code, message)
        return await http_exception_handler(request, exc)

    async def _server_error(self, request: Request, exc: Exception) -> Response:
        logging.getLogger("rational").exception("unhandled request error", exc_info=(type(exc), exc, exc.__traceback__))
        response = PlainTextResponse("Internal Server Error", status_code=500)
        ctx = getattr(request.state, "rational_context", None)
        if isinstance(ctx, Context):
            self.finish(request, response, ctx)
        return response

    @staticmethod
    def _asset(content: str, media_type: str) -> Callable[[], Any]:
        async def serve() -> Response:
            return Response(content, media_type=media_type, headers=_IMMUTABLE)

        return serve

    # -- cross-worker live sessions ------------------------------------------------------------

    @staticmethod
    def _channel(sid: str) -> str:
        return f"rational:session:{sid}"

    async def _announce_session(self, session: Session) -> None:
        if self.bus is None:
            return
        try:
            await self.bus.publish(self._channel(session.id), self.boot_id)
        except Exception:
            log.exception("could not announce a session change")

    def follow_session(self, session: Session) -> None:
        """Listen for changes other workers make to ``session`` while a page here shows its data."""
        if self.bus is None or session.id in self._followed:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        sid = session.id
        self._followed[sid] = None  # claimed; the subscription follows

        def on_message(origin: str) -> None:
            if origin == self.boot_id:
                return
            live = self.sessions.get(sid)
            if live is None or not live.listeners:
                unsubscribe = self._followed.pop(sid, None)
                if unsubscribe is not None:
                    loop.create_task(unsubscribe())
                return
            loop.create_task(self.sessions.load(sid))  # a newer version bumps the session and wakes its pages

        async def subscribe() -> None:
            assert self.bus is not None
            try:
                self._followed[sid] = await self.bus.subscribe(self._channel(sid), on_message)
            except Exception:
                self._followed.pop(sid, None)
                log.exception("could not follow session changes")

        loop.create_task(subscribe())

    @asynccontextmanager
    async def _lifespan(self, _app: FastAPI) -> AsyncIterator[None]:
        try:
            for fn in self._startup:
                result = fn()
                if inspect.isawaitable(result):
                    await result
        except Exception as exc:
            if not self.debug:
                raise
            traceback.print_exception(type(exc), exc, exc.__traceback__)
            self._startup_error = exc
        try:
            yield
        finally:
            if self.db is not None:
                await self.db.dispose()


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:10]
