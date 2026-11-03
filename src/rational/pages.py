"""Serving ``Page`` classes as server-rendered HTML documents."""

from __future__ import annotations

import logging
import re
import secrets
import time
import typing
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from urllib.parse import quote, urlencode

from fastapi import Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import TypeAdapter, ValidationError

from . import dev
from .component import Page
from .context import Context
from .document import render_document
from .errors import RationalError, Redirect
from .http import base_path, request_target
from .protocol import EVENT_PATH, PROTOCOL_VERSION, STREAM_PATH, WS_PATH
from .rendering.html import escape_text, to_html
from .runtime import PageRuntime
from .styling.compiler import StyleSheet

if TYPE_CHECKING:
    from .app import App

PATH_PARAM = re.compile(r"{(\w+)(?::(\w+))?}")

PathValues = Iterable[Mapping[str, Any]]


@dataclass
class PageRoute:
    """The GET endpoint for one ``Page`` class."""

    app: App
    path: str
    page: type[Page]
    title: str | None = None
    auth: str | None = None
    paths: PathValues | Callable[[], PathValues] | None = None  # parameter values to export
    adapters: dict[str, TypeAdapter[Any]] = field(init=False)

    def __post_init__(self) -> None:
        params = [m.group(1) for m in PATH_PARAM.finditer(self.path)]
        # A {lang} parameter may instead set the page's language (/{lang}/docs/faq.html).
        clashes = [p for p in params if p in self.page._rw_reserved and p != "lang"]
        if clashes:
            raise TypeError(f"{self.path}: rename path parameter(s) {clashes}, which mean something else on a Page")
        missing = [p for p in params if p not in self.page._rw_props and p != "lang"]
        if missing:
            raise TypeError(f"{self.page.__name__} must declare path parameter(s) {missing} as annotated props")
        try:
            hints = typing.get_type_hints(self.page)
        except Exception:
            hints = {}
        self.adapters = {p: TypeAdapter(hints.get(p, str)) for p in params}
        self.auth = self.auth or self.page.auth
        if self.paths is not None and not callable(self.paths):
            self.paths = list(self.paths)  # a generator could be read only once

    def url(self, **params: Any) -> str:
        """The URL for these parameter values, percent-encoded (``/`` only stays in ``{name:path}``)."""

        def value(match: re.Match[str]) -> str:
            return quote(str(params[match.group(1)]), safe="/" if match.group(2) == "path" else "")

        return PATH_PARAM.sub(value, self.path)

    def urls(self) -> list[str]:
        """Every URL to export: the path itself, or one per entry of ``paths``."""
        if not self.adapters:
            return [self.path]
        values = self.paths() if callable(self.paths) else self.paths or ()
        urls = []
        for params in values:
            if set(params) != set(self.adapters):
                raise ValueError(
                    f"{self.path}: paths entries need exactly {sorted(self.adapters)}, got {sorted(params)}"
                )
            urls.append(self.url(**params))
        return urls

    def build(self, params: Mapping[str, Any]) -> Page:
        """A page for these path parameters (raises ``ValidationError`` for values of the wrong type)."""
        props = {name: a.validate_python(params[name]) for name, a in self.adapters.items()}
        lang = props.pop("lang", None) if "lang" not in self.page._rw_props else None
        page = self.page(**props)
        if lang is not None:
            page.lang = lang
        return page

    async def __call__(self, request: Request) -> Response:
        app = self.app
        ctx = await app.context_for(request)
        async with app.session_lock(ctx):
            return await self._serve(request, ctx)

    async def _serve(self, request: Request, ctx: Context) -> Response:
        app = self.app
        base = base_path(request)

        async def finish(response: Response) -> Response:
            await app.finish(request, response, ctx)
            return response

        try:
            page = self.build(request.path_params)
        except ValidationError:
            return await finish(error_page(app, request, 404, "Page not found"))
        try:
            await app.limiter.check(self.page, ctx)
        except RationalError as e:
            return await finish(error_page(app, request, e.status, e.message, e.headers))
        if self.auth == "required" and ctx.user is None:
            if app.login_path:
                login = f"{base}{app.login_path}?{urlencode({'next': request_target(request)}, safe='/')}"
                return await finish(RedirectResponse(login, status_code=303))
            return await finish(error_page(app, request, 401, "Please sign in to view this page"))

        runtime = PageRuntime(page, ctx, StyleSheet(app.compiler))
        runtime.origin = (self.path, {k: str(v) for k, v in request.path_params.items()})
        runtime.requires_user = self.auth == "required"
        try:
            try:
                root = await self._render(runtime, request)
            except Redirect as r:
                url = base + r.url if r.url.startswith("/") and not r.url.startswith("//") else r.url
                return await finish(RedirectResponse(url, status_code=r.status))
            except RationalError as e:
                return await finish(error_page(app, request, e.status, e.message, e.headers))
            except Exception as e:
                if app.debug:
                    return await finish(dev.error_page(request, e))
                raise
            return await self._respond(runtime, root, request, ctx)
        finally:
            if not runtime.served:
                runtime.dispose()  # nothing can reach this page again: a static one, or a failed render

    async def _render(self, runtime: PageRuntime, request: Request) -> Any:
        logs, page = self.app.logging, type(runtime.page).__name__
        with logs.span("rational.page.render", {"page.name": page, "url.path": request.url.path}) as span:
            started = time.perf_counter()
            try:
                return await runtime.render_page()
            finally:
                duration_ms = (time.perf_counter() - started) * 1000
                slow = duration_ms >= logs.slow_render_threshold_ms
                logs.finish_span(span, **{"rational.render.duration_ms": duration_ms, "rational.render.slow": slow})
                if slow:
                    logs.record(
                        "page.render.slow",
                        level=logging.WARNING,
                        page=page,
                        path=request.url.path,
                        duration_ms=duration_ms,
                        threshold_ms=logs.slow_render_threshold_ms,
                    )

    def _manifest(self, runtime: PageRuntime, ctx: Context, base: str) -> dict[str, Any] | None:
        """What the browser runtime needs for this page; ``None`` if the page does not need the runtime."""
        app = self.app
        shared: dict[str, Any] = {
            "v": PROTOCOL_VERSION,
            "nav": app.client_nav,
            "transitions": app.view_transitions,
            "base": base,
            "api": base + app.api_prefix,
            "debug": app.debug,
        }
        if runtime.page_scripts:
            shared["full"] = True  # scripts that set up what they find as they load: never swap this page in
        if runtime.interactive:
            return {
                **shared,
                "page": runtime.id,
                "rev": runtime.revision,
                "seq": runtime.seq,
                "csrf": ctx.session.csrf,  # interactive pages need a session to bind events to
                "endpoint": base + EVENT_PATH,
                "stream": base + STREAM_PATH if runtime.wants_stream else None,
                "ws": base + WS_PATH if app.websocket else None,
            }
        if app.client_nav or runtime.islands:
            # No server events here, but the runtime still handles links and client components.
            # A page the app lets browsers or CDNs cache holds no visitor's token: rational.call
            # fetches it from CSRF_PATH when a call needs one.
            current = ctx.peek_session()
            csrf = current.csrf if current is not None and runtime.page.cache_control is None else None
            return {**shared, "csrf": csrf}
        return None

    async def _respond(self, runtime: PageRuntime, root: Any, request: Request, ctx: Context) -> Response:
        app, page, base = self.app, runtime.page, base_path(request)
        manifest = self._manifest(runtime, ctx, base)
        if runtime.interactive:
            runtime.sync_session_revision()
            app.pages.put(runtime.id, runtime)
            runtime.served = True
            if app.resume is not None:
                await app.resume.save(runtime)
        personal = manifest is not None and bool(manifest.get("page") or manifest.get("csrf"))  # this visitor's
        status = page.status or 200
        headers = {"Cache-Control": "no-store" if personal else page.cache_control or "no-cache"}

        async def send(response: Response) -> Response:
            await app.finish(request, response, ctx)
            if "set-cookie" in response.headers and not personal:
                response.headers["Cache-Control"] = "private, no-cache"  # a cookie must not be cached for others
            return response

        if page.etag and not personal and status == 200:
            etag = page.etag if page.etag.startswith(('"', 'W/"')) else f'"{page.etag}"'  # quoted, as HTTP requires
            headers["ETag"] = etag
            if _etag_matches(request.headers.get("if-none-match", ""), etag):
                return await send(Response(status_code=304, headers=headers))
        nonce = secrets.token_urlsafe(16) if app.csp else None
        title = page.title or self.title or app.title
        lang = page.lang or ctx.locale
        seo = app.seo.head(page, self.url(**request.path_params), title, lang) if app.seo else ""
        html = render_document(
            body=to_html(root, component_ids=manifest is not None),
            title=title,
            description=page.description,
            lang=lang,
            theme_href=base + app.theme_href if app.theme_href else None,
            page_css="".join(runtime.sheet.drain()),
            data_theme=app.data_theme(request),
            manifest=manifest,
            runtime_src=base + app.runtime_src,
            nonce=nonce,
            favicon=app.favicon if page.favicon is None else page.favicon,
            head_start=page.head_start,
            head_extra=seo + app.head_extra(nonce, base) + page.head_end,
            scripts=runtime.document_scripts(base),
            dir=page.dir,
        )
        response = HTMLResponse(html, status_code=status, headers=headers)
        app.apply_csp(response, nonce)
        return await send(response)


def _etag_matches(if_none_match: str, etag: str) -> bool:
    """``If-None-Match`` compares weakly: ``W/`` makes no difference, and ``*`` matches anything."""
    opaque = etag.removeprefix("W/")
    return any(tag.strip() == "*" or tag.strip().removeprefix("W/") == opaque for tag in if_none_match.split(","))


def error_page(
    app: App, request: Request, status: int, message: str, headers: Mapping[str, str] | None = None
) -> HTMLResponse:
    body = (
        '<main style="max-width:560px;margin:15vh auto;padding:0 16px">'
        f'<p style="color:var(--rw-color-muted);margin:0 0 8px">{status}</p>'
        f'<h1 style="margin:0 0 16px">{escape_text(message)}</h1>'
        '<a href="/">Go to the home page</a></main>'
    )
    nonce = secrets.token_urlsafe(16) if app.csp else None
    html = render_document(
        body=body,
        title=f"{status} · {app.title}",
        lang=app.lang,
        theme_href=base_path(request) + app.theme_href if app.theme_href else None,
        page_css="",
        data_theme=app.data_theme(request),
        nonce=nonce,
        favicon=app.favicon,
        head_extra=app.head_extra(nonce, base_path(request)),
    )
    response = HTMLResponse(html, status_code=status, headers=headers)
    app.apply_csp(response, nonce, inline_styles=True)
    return response
