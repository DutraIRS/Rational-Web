"""The HTML document shell around a rendered page."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any, Literal

from .rendering.html import escape_attr, escape_text


def json_for_script(data: Any) -> str:
    """JSON that is safe inside a ``<script type="application/json">`` element."""
    text = json.dumps(data, separators=(",", ":"))
    return text.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def render_document(
    *,
    body: str,
    title: str,
    lang: str,
    theme_href: str | None,
    page_css: str,
    description: str | None = None,
    data_theme: str | None = None,
    manifest: dict[str, Any] | None = None,
    runtime_src: str | None = None,
    nonce: str | None = None,
    favicon: str | Literal[False] | None = None,
    head_start: str = "",
    head_extra: str = "",
    scripts: Sequence[str] = (),
    dir: str | None = None,
) -> str:
    """The page. ``scripts`` load after the runtime, in order (client component modules).

    ``head_start`` and ``head_extra`` are trusted markup, placed right after ``<meta charset>``
    and at the end of ``<head>``. ``favicon=False`` writes no icon link."""
    if dir not in (None, "ltr", "rtl", "auto"):
        raise ValueError(f'dir must be "ltr", "rtl" or "auto", not {dir!r}')
    nonce_attr = f' nonce="{escape_attr(nonce)}"' if nonce else ""
    html_attrs = f' lang="{escape_attr(lang)}"'
    if dir:
        html_attrs += f' dir="{dir}"'
    if data_theme:
        html_attrs += f' data-theme="{escape_attr(data_theme)}"'
    head = [
        '<meta charset="utf-8">',
        head_start,
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>{escape_text(title)}</title>",
    ]
    if description:
        head.append(f'<meta name="description" content="{escape_attr(description)}">')
    if favicon is not False:  # an explicit (possibly empty) icon stops requests for /favicon.ico
        head.append(f'<link rel="icon" href="{escape_attr(favicon or "data:,")}">')
    if theme_href is not None:
        head.append(f'<link rel="stylesheet" href="{escape_attr(theme_href)}">')
    if page_css or manifest is not None:  # the runtime adds the styles of later updates here
        head.append(f'<style id="rw-styles"{nonce_attr}>{page_css}</style>')
    head.append(head_extra)
    tail = ""
    if manifest is not None and runtime_src is not None:
        tail = (
            f'<script type="application/json" id="rw-manifest">{json_for_script(manifest)}</script>'
            f'<script src="{escape_attr(runtime_src)}" defer{nonce_attr}></script>'
        )
        tail += "".join(f'<script src="{escape_attr(src)}" defer data-rw-load{nonce_attr}></script>' for src in scripts)
    return f"<!doctype html><html{html_attrs}><head>{''.join(head)}</head><body>{body}{tail}</body></html>"
