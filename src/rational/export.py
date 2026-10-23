"""Static export: render an app's static pages to plain HTML files.

``python app.py --export site/`` writes ``site/index.html``, ``site/<path>/index.html``, the
theme stylesheet and every directory mounted with ``app.static``. The result can be hosted on
any static file host (GitHub Pages, Netlify, S3, ...).

Only pages that are fully static can be exported: no path parameters, no sign-in requirement
and no interactivity (an interactive page needs the live server for its events). Everything
else is reported as skipped rather than exported broken.
"""

from __future__ import annotations

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


@dataclass
class ExportReport:
    """What :func:`export_site` wrote and what it left out (with the reason)."""

    pages: list[str] = field(default_factory=list)
    assets: list[str] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)


async def export_site(app: App, out: str | Path, *, base_path: str = "") -> ExportReport:
    """Write the static pages and assets of ``app`` under ``out``.

    ``base_path`` is the URL prefix the site will be served under (``"/my-repo"`` for a GitHub
    Pages project site); it prefixes every asset link, exactly like ``--root-path`` does when serving.
    """
    root = Path(out)
    base = base_path.rstrip("/")
    report = ExportReport()
    was_debug, app.debug = app.debug, False
    was_nav, app.client_nav = app.client_nav, False  # an exported site has no runtime to navigate with
    try:
        async with app.fastapi.router.lifespan_context(app.fastapi):
            for route in app.routes.values():
                name = route.page.__name__
                if "{" in route.path:
                    report.skipped.append((route.path, f"{name} has path parameters"))
                    continue
                if (route.auth or "") == "required":
                    report.skipped.append((route.path, f"{name} requires sign-in"))
                    continue
                status, body = await _get(app, route.path, base)
                if status != 200:
                    report.skipped.append((route.path, f"{name} answered HTTP {status}"))
                    continue
                if RUNTIME_PATH in body:
                    report.skipped.append((route.path, f"{name} is interactive and needs a live server"))
                    continue
                _write(root, _page_file(route.path), body)
                report.pages.append(route.path)

            if report.pages:
                _write(root, "_rational/theme.css", app.theme_css.encode())
                report.assets.append("/_rational/theme.css")
                status, body = await _get(app, "/__rational_not_found__", base)
                if status == 404 and b"<html" in body:
                    _write(root, "404.html", body)
            for mount in app.fastapi.routes:
                directory = _static_directory(mount)
                if directory is not None and isinstance(mount, Mount):
                    shutil.copytree(directory, root / mount.path.strip("/"), dirs_exist_ok=True)
                    report.assets.append(mount.path)
    finally:
        app.debug = was_debug
        app.client_nav = was_nav
    return report


def _page_file(path: str) -> str:
    return f"{path.strip('/')}/index.html".lstrip("/")


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
