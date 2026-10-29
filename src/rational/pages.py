"""Serving ``Page`` classes as server-rendered HTML documents."""

from __future__ import annotations

import logging
import re
import secrets
import time
import typing
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any
from urllib.parse import urlencode

from fastapi import Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import TypeAdapter, ValidationError

from . import dev
from .component import Page
from .context import Context
from .document import render_document
from .errors import RationalError, Redirect
from .http import base_path, request_target, security_headers
from .protocol import EVENT_PATH, PROTOCOL_VERSION, STREAM_PATH, WS_PATH
from .rendering.html import escape_text, to_html
from .rendering.nodes import Node
from .runtime import PageRuntime
from .styling.compiler import StyleSheet

if TYPE_CHECKING:
    from .app import App

PATH_PARAM = re.compile(r"{(\w+)(?::\w+)?}")

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
        params = PATH_PARAM.findall(self.path)
        # A {lang} parameter may instead set the page's language (/{lang}/docs/faq.html).
        missing = [p for p in params if p not in self.page._rw_props and p != "lang"]
        if missing:
            raise TypeError(f"{self.page.__name__} must declare path parameter(s) {missing} as annotated props")
        try:
            hints = typing.get_type_hints(self.page)
        except Exception:
            hints = {}
        self.adapters = {p: TypeAdapter(hints.get(p, str)) for p in params}
        self.auth = self.auth or self.page.auth

    def url(self, **params: Any) -> str:
        return PATH_PARAM.sub(lambda m: str(params[m.group(1)]), self.path)

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
        app.housekeeping()
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
        if self.auth == "required" and ctx.user is None:
            if app.login_path:
                login = f"{base}{app.login_path}?{urlencode({'next': request_target(request)}, safe='/')}"
                return await finish(RedirectResponse(login, status_code=303))
            return await finish(error_page(app, request, 401, "Please sign in to view this page"))

        runtime = PageRuntime(page, ctx, StyleSheet(app.compiler))
        runtime.origin = (self.path, {k: str(v) for k, v in request.path_params.items()})
        try:
            with app.logging.span(
                "rational.page.render",
                {"page.name": type(page).__name__, "url.path": request.url.path},
            ) as span:
                render_started = time.perf_counter()
                try:
                    root = await runtime.render_page()
                finally:
                    duration_ms = (time.perf_counter() - render_started) * 1000
                    slow = duration_ms >= app.logging.slow_render_threshold_ms
                    app.logging.finish_span(
                        span,
                        **{
                            "rational.render.duration_ms": duration_ms,
                            "rational.render.slow": slow,
                        },
                    )
                    if slow:
                        app.logging.record(
                            "page.render.slow",
                            level=logging.WARNING,
                            page=type(page).__name__,
                            path=request.url.path,
                            duration_ms=duration_ms,
                            threshold_ms=app.logging.slow_render_threshold_ms,
                        )
        except Redirect as r:
            url = base + r.url if r.url.startswith("/") and not r.url.startswith("//") else r.url
            response: Response = RedirectResponse(url, status_code=r.status)
            return await finish(response)
        except RationalError as e:
            return await finish(error_page(app, request, e.status, e.message))
        except Exception as e:
            if app.debug:
                return await finish(dev.error_page(request, e))
            raise

        manifest = None
        if runtime.interactive:
            session = ctx.session  # interactive pages need a session to bind events to
            runtime.sync_session_revision()
            app.pages.put(runtime.id, runtime)
            runtime.served = True
            if app.resume is not None:
                await app.resume.save(runtime)
            manifest = {
                "v": PROTOCOL_VERSION,
                "page": runtime.id,
                "rev": runtime.revision,
                "seq": runtime.seq,
                "csrf": session.csrf,
                "endpoint": base + EVENT_PATH,
                "stream": base + STREAM_PATH if runtime.wants_stream else None,
                "ws": base + WS_PATH if app.websocket else None,
                "api": base + app.api_prefix,
                "base": base,
                "nav": app.client_nav,
                "transitions": app.view_transitions,
                "debug": app.debug,
            }
        elif app.client_nav or runtime.islands:
            # No server events here, but the runtime still handles links and client components.
            current = ctx.peek_session()
            manifest = {
                "v": PROTOCOL_VERSION,
                "nav": app.client_nav,
                "transitions": app.view_transitions,
                "base": base,
                "api": base + app.api_prefix,
                "csrf": current.csrf if current is not None else None,
                "debug": app.debug,
            }
        scripts = [base + app.islands_src, *(base + path for path in runtime.islands)] if runtime.islands else []
        runtime.sheet.drain()
        nonce = secrets.token_urlsafe(16) if app.csp else None
        title = page.title or self.title or app.title
        lang = page.lang or ctx.locale
        seo = app.seo.head(page, self.url(**request.path_params), title, lang) if app.seo else ""
        html = render_document(
            body=to_html(root if manifest else _without_component_ids(root)),
            title=title,
            description=page.description,
            lang=lang,
            theme_href=base + app.theme_href if app.theme_href else None,
            page_css=runtime.sheet.css(),
            data_theme=app.data_theme(request),
            manifest=manifest,
            runtime_src=base + app.runtime_src,
            nonce=nonce,
            favicon=app.favicon if page.favicon is None else page.favicon,
            head_start=page.head_start,
            head_extra=seo + app.head_extra(nonce, base) + page.head_end,
            scripts=scripts,
            dir=page.dir,
        )
        response = HTMLResponse(html, headers={"Cache-Control": "no-store" if manifest else "no-cache"})
        security_headers(response, nonce, style_origins=app.style_origins, script_origins=app.script_origins)
        return await finish(response)


def _without_component_ids(node: Any) -> Any:
    """Component markers are for the browser runtime; a page without it is plain HTML."""
    if not isinstance(node, Node):
        return node
    return replace(
        node,
        attrs=tuple(a for a in node.attrs if a[0] != "data-rw-c"),
        children=tuple(_without_component_ids(c) for c in node.children),
    )


def error_page(app: App, request: Request, status: int, message: str) -> HTMLResponse:
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
    response = HTMLResponse(html, status_code=status)
    security_headers(
        response,
        nonce,
        inline_styles=True,
        style_origins=app.style_origins,
        script_origins=app.script_origins,
    )
    return response
