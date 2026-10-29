"""Static export: render an app's static pages to plain HTML files.

``python app.py --export site/`` writes ``site/index.html``, ``site/<path>/index.html`` (or
``site/<path>`` for a route ending in ``.html``), the theme stylesheet and every directory mounted
with ``app.static``. The result can be hosted on any static file host (GitHub Pages, Netlify,
S3, ...).

Only pages that work without a server can be exported: no sign-in requirement and no server
events, and path parameters only with the values to write (``@app.page(path, paths=[...])``).
Client components are fine: they run in the browser, so the runtime scripts and their compiled
modules are exported with the pages. Everything else is reported as skipped rather than exported
broken.
"""

from __future__ import annotations

import json
import re
import shutil
from collections.abc import MutableMapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from starlette.routing import Mount
from starlette.staticfiles import StaticFiles

if TYPE_CHECKING:
    from .app import App

RUNTIME_PATH = b"/_rational/runtime.js"
_MANIFEST = re.compile(rb'<script type="application/json" id="rw-manifest">(.*?)</script>', re.DOTALL)


@dataclass
class ExportReport:
    """What :func:`export_site` wrote and what it left out (with the reason)."""

    pages: list[str] = field(default_factory=list)
    assets: list[str] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)


async def export_site(
    app: App, out: str | Path, *, base_path: str = "", relative: bool = False, not_found: bool = True
) -> ExportReport:
    """Write the static pages and assets of ``app`` under ``out``.

    ``base_path`` is the URL prefix the site will be served under (``"/my-repo"`` for a GitHub
    Pages project site); it prefixes every asset link, exactly like ``--root-path`` does when serving.
    ``relative=True`` links each page's assets relative to that page instead (``../_rational/...``),
    so the site also works opened from disk or under any prefix; the 404 page, shown at any URL,
    still uses ``base_path``. ``not_found=False`` writes no ``404.html``.
    """
    root = Path(out)
    base = base_path.rstrip("/")
    report = ExportReport()
    scripts = False
    was_debug, app.debug = app.debug, False
    was_nav, app.client_nav = app.client_nav, False  # an exported site has no runtime to navigate with
    try:
        async with app.fastapi.router.lifespan_context(app.fastapi):
            for route in app.routes.values():
                name = route.page.__name__
                if (route.auth or "") == "required":
                    report.skipped.append((route.path, f"{name} requires sign-in"))
                    continue
                urls = route.urls()
                if not urls:
                    report.skipped.append((route.path, f"{name} has path parameters: list their values with paths="))
                for url in urls:
                    file = _page_file(url)
                    status, body = await _get(app, url, _relative_base(file) if relative else base)
                    if status != 200:
                        report.skipped.append((url, f"{name} answered HTTP {status}"))
                        continue
                    if _needs_server(body):
                        report.skipped.append((url, f"{name} has server events and needs a live server"))
                        continue
                    _write(root, file, body)
                    report.pages.append(url)
                    scripts = scripts or RUNTIME_PATH in body

            for path in app.exported_files if report.pages else ():  # sitemap.xml, robots.txt, ...
                status, body = await _get(app, path, base)
                if status == 200:
                    _write(root, path.lstrip("/"), body)
                    report.assets.append(path)
            if report.pages and app.theme_href:
                _write(root, "_rational/theme.css", app.theme_css.encode())
                report.assets.append("/_rational/theme.css")
            own_404 = any(_page_file(url) == "404.html" for url in report.pages)  # the site's own 404 page wins
            if report.pages and not_found and not own_404:
                status, body = await _get(app, "/__rational_not_found__", base)
                if status == 404 and b"<html" in body:
                    _write(root, "404.html", body)
            if scripts:  # pages with client components: the browser runtime and every compiled module
                files = {"/_rational/runtime.js": app.runtime_js, "/_rational/islands.js": app.islands_js}
                files.update({module.path: module.js for module in app.client_modules})
                for path, text in files.items():
                    _write(root, path.lstrip("/"), text.encode())
                    report.assets.append(path)
            for mount in app.fastapi.routes:
                directory = _static_directory(mount)
                if directory is not None and isinstance(mount, Mount):
                    shutil.copytree(directory, root / mount.path.strip("/"), dirs_exist_ok=True)
                    report.assets.append(mount.path)
    finally:
        app.debug = was_debug
        app.client_nav = was_nav
    return report


def _needs_server(body: bytes) -> bool:
    """True if the page talks to its server-side view (a manifest with a page id)."""
    match = _MANIFEST.search(body)
    return match is not None and "page" in json.loads(match.group(1))


def _page_file(path: str) -> str:
    """``/about`` is written as ``about/index.html``; a route that names its file, like
    ``/docs/faq.html``, keeps that name, so an exported site can keep existing URLs."""
    if path.endswith(".html"):
        return path.lstrip("/")
    return f"{path.strip('/')}/index.html".lstrip("/")


def _relative_base(file: str) -> str:
    """The way from a page file back to the site root: ``"."``, ``".."``, ``"../.."``, ..."""
    depth = file.count("/")
    return "/".join([".."] * depth) if depth else "."


def _write(root: Path, relative: str, content: bytes) -> None:
    target = (root / relative).resolve()
    if root.resolve() not in target.parents:
        raise ValueError(f"refusing to write outside the export directory: {relative}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)


def _static_directory(route: Any) -> str | None:
    if isinstance(route, Mount) and isinstance(route.app, StaticFiles) and route.app.directory:
        return str(route.app.directory)
    return None


async def _get(app: App, path: str, base: str) -> tuple[int, bytes]:
    """One in-process GET against the ASGI app (no network, no cookies kept)."""
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "root_path": base,
        "query_string": b"",
        "headers": [(b"host", b"localhost"), (b"accept", b"text/html")],
        "client": ("127.0.0.1", 0),
        "server": ("localhost", 80),
    }
    status = 500
    chunks: list[bytes] = []
    sent_request = False

    async def receive() -> MutableMapping[str, Any]:
        nonlocal sent_request
        if sent_request:
            return {"type": "http.disconnect"}
        sent_request = True
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: MutableMapping[str, Any]) -> None:
        nonlocal status
        if message["type"] == "http.response.start":
            status = message["status"]
        elif message["type"] == "http.response.body":
            chunks.append(message.get("body", b""))

    await app(scope, receive, send)
    return status, b"".join(chunks)
