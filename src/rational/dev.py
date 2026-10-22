"""Development-mode helpers: readable errors and browser live-reload.

``python app.py --dev`` (see ``rational.cli``) sets ``RATIONAL_DEV=1`` so the app
runs with ``debug=True``. Every page then loads ``/_rational/dev.js``, which
polls the server's boot id to reload the page after a restart and shows
event-handler errors in an overlay. Never enable this in production: it
exposes source code and tracebacks.
"""

from __future__ import annotations

import linecache
import os
import secrets
import sys
import traceback
from importlib import resources
from pathlib import Path
from typing import Any

from fastapi import Request
from fastapi.responses import HTMLResponse, PlainTextResponse, Response
from starlette.types import ASGIApp, Receive, Scope, Send

from .http import base_path
from .rendering.html import escape_attr, escape_text

DEV_ENV = "RATIONAL_DEV"
_PACKAGE_DIR = os.path.normcase(str(Path(__file__).parent))

HINTS: list[tuple[str, str, str]] = [
    # (exception type name, substring of the message or "", hint)
    (
        "StyleError",
        "",
        "Style values are validated to keep CSS injection out. Use a theme token, a number (px), "
        "a plain CSS value, or Style(raw={...}) for unusual properties.",
    ),
    (
        "UnsafeMarkupError",
        "",
        "Rational escapes all markup. Pass handlers as on_click=..., and use unsafe_html() only for HTML you trust.",
    ),
    (
        "TypeError",
        "prop",
        "Props are the annotated class attributes of a component; pass them as keywords, e.g. Greeting(name='Ada').",
    ),
    ("RuntimeError", "during render", "render() must not change state. Do it in an event handler or in mount()."),
    (
        "RuntimeError",
        "not mounted",
        "self.context, self.use() and self.navigate() work once the component is "
        "mounted: in mount(), render() and event handlers.",
    ),
    ("ModuleNotFoundError", "sqlalchemy", "Database support is optional: pip install 'rational[db]'."),
    (
        "ModuleNotFoundError",
        "",
        "Python can't find that module. Check the import's spelling, that the file or package exists "
        "(packages need an __init__.py), and that you start the app from its project folder.",
    ),
    (
        "ImportError",
        "cannot import name",
        "The module exists but doesn't define that name. Check the spelling, or look for a circular import "
        "(two modules importing each other at the top).",
    ),
    ("IndentationError", "", "The indentation is inconsistent: look at the highlighted line and the one before."),
    ("SyntaxError", "", "Python couldn't parse this file: look at the highlighted line and the one before."),
]


def is_dev_environment() -> bool:
    return os.environ.get(DEV_ENV) == "1"


def describe(exc: BaseException) -> dict[str, Any]:
    """A JSON-friendly description of ``exc`` pointing at the most relevant *user* frame."""
    tb = traceback.TracebackException.from_exception(exc)
    frames = list(tb.stack)
    user_frames = [f for f in frames if _is_user_frame(f.filename)]
    frame = user_frames[-1] if user_frames else (frames[-1] if frames else None)
    out: dict[str, Any] = {
        "type": type(exc).__name__,
        "message": str(exc),
        "notes": list(getattr(exc, "__notes__", [])),
        "traceback": "".join(tb.format()),
        "hint": _hint(exc),
    }
    if isinstance(exc, SyntaxError) and exc.filename and exc.lineno:
        # The broken file never ran, so no stack frame points at it: the exception itself does.
        filename, lineno, function = exc.filename, exc.lineno, "<module>"
    elif frame is not None and frame.lineno is not None:
        filename, lineno, function = frame.filename, frame.lineno, frame.name
    else:
        return out
    linecache.checkcache(filename)  # the file may have changed since it was cached
    out.update(
        file=_relative(filename),
        line=lineno,
        function=function,
        snippet=[
            [n, linecache.getline(filename, n).rstrip("\n"), n == lineno]
            for n in range(max(lineno - 3, 1), lineno + 3)
            if linecache.getline(filename, n)
        ],
    )
    return out


def error_page(request: Request, exc: BaseException, *, stage: str = "") -> HTMLResponse:
    """The development error page. ``stage`` says when it happened, e.g. "while importing the app"."""
    info = describe(exc)
    where = ""
    if "file" in info:
        location = f"{escape_text(info['file'])}:{info['line']}"
        where = f'<p class="where">in <b>{escape_text(info["function"])}()</b> · {location}</p>'
    snippet = "".join(
        f'<div class="{"hl" if current else ""}"><span>{n}</span>{escape_text(code) or " "}</div>'
        for n, code, current in info.get("snippet", [])
    )
    hint = f'<p class="hint">💡 {escape_text(info["hint"])}</p>' if info["hint"] else ""
    notes = "".join(f'<p class="where">{escape_text(n)}</p>' for n in info["notes"])
    tag = " · ".join(
        filter(None, ["Rational Web", f"development error {stage}".strip(), request.method + " " + request.url.path])
    )
    html = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><link rel="icon" href="data:,">
<title>{escape_text(info["type"])} · Rational dev</title><style>{_ERROR_CSS}</style></head><body><main>
<p class="tag">{escape_text(tag)}</p>
<h1>{escape_text(info["type"])}</h1><p class="msg">{escape_text(info["message"])}</p>{where}{notes}
<pre class="code">{snippet}</pre>{hint}
<details><summary>Full traceback</summary><pre>{escape_text(info["traceback"])}</pre></details>
<p class="foot">Save a fix and this page reloads by itself.</p></main>
<script src="{escape_attr(base_path(request) + DEV_SCRIPT_PATH)}" defer></script></body></html>"""
    return HTMLResponse(html, status_code=500, headers={"Cache-Control": "no-store"})


def broken_app(exc: BaseException, stage: str) -> ASGIApp:
    """Stands in for an app that can't be imported or started, during development only.

    Every page shows the error. The live-reload script is served too, so once a fix is saved and
    the dev server restarts, the browser reloads by itself and shows the working app.
    """
    boot_id = secrets.token_hex(8)
    script = resources.files("rational").joinpath("static/dev.js").read_text("utf-8")

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "lifespan":
            while True:
                message = await receive()
                if message["type"] == "lifespan.startup":
                    await send({"type": "lifespan.startup.complete"})
                elif message["type"] == "lifespan.shutdown":
                    await send({"type": "lifespan.shutdown.complete"})
                    return
        if scope["type"] != "http":
            return
        path = scope["path"]
        response: Response
        if path.endswith(DEV_SCRIPT_PATH):
            response = Response(script, media_type="text/javascript", headers={"Cache-Control": "no-store"})
        elif path.endswith(BOOT_PATH):
            response = PlainTextResponse(boot_id, headers={"Cache-Control": "no-store"})
        else:
            response = error_page(Request(scope), exc, stage=stage)
        await response(scope, receive, send)

    return app


def _is_user_frame(filename: str) -> bool:
    name = os.path.normcase(filename)
    return not (name.startswith((_PACKAGE_DIR, os.path.normcase(sys.base_prefix), "<")) or "site-packages" in name)


def _relative(filename: str) -> str:
    try:
        return str(Path(filename).resolve().relative_to(Path.cwd()))
    except ValueError:
        return filename


def _hint(exc: BaseException) -> str | None:
    name, message = type(exc).__name__, str(exc)
    for type_name, needle, hint in HINTS:
        if name == type_name and needle in message:
            return hint
    return None


DEV_SCRIPT_PATH = "/_rational/dev.js"
BOOT_PATH = "/_rational/dev/boot"


_ERROR_CSS = (
    "body{margin:0;background:#140d18;color:#f2e9f0;font:15px/1.55 system-ui,sans-serif}"
    "main{max-width:960px;margin:0 auto;padding:40px 20px}"
    ".tag{color:#b98aa8;font-size:13px;margin:0}h1{color:#ff8fb3;margin:6px 0 4px;font-size:28px}"
    ".msg{font-size:18px;margin:0 0 8px;white-space:pre-wrap}.where{color:#c9b3c2;margin:0 0 12px}"
    ".code{background:#1f1424;border:1px solid #3a2640;border-radius:10px;padding:10px 0;overflow:auto;"
    "font:13px/1.6 ui-monospace,Menlo,Consolas,monospace}.code div{padding:0 14px;white-space:pre}"
    ".code span{display:inline-block;width:3.5em;color:#7d6276}.code .hl{background:#e0457b33}"
    ".hint{background:#2a2410;border:1px solid #6b5a1c;color:#ffe08a;border-radius:10px;padding:10px 14px}"
    "details pre{white-space:pre-wrap;font:12px/1.5 ui-monospace,Menlo,Consolas,monospace;color:#d8c6d2}"
    "summary{cursor:pointer;color:#c9b3c2}.foot{color:#7d6276;font-size:13px;margin-top:24px}"
)
