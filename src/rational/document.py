"""The HTML document shell around a rendered page."""

from __future__ import annotations

import json
from typing import Any

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
    theme_href: str,
    page_css: str,
    description: str | None = None,
    data_theme: str | None = None,
    manifest: dict[str, Any] | None = None,
    runtime_src: str | None = None,
    nonce: str | None = None,
    favicon: str | None = None,
    head_extra: str = "",
) -> str:
    nonce_attr = f' nonce="{escape_attr(nonce)}"' if nonce else ""
    html_attrs = f' lang="{escape_attr(lang)}"'
    if data_theme:
        html_attrs += f' data-theme="{escape_attr(data_theme)}"'
    head = [
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>{escape_text(title)}</title>",
    ]
    if description:
        head.append(f'<meta name="description" content="{escape_attr(description)}">')
    # An explicit (possibly empty) icon stops browsers from requesting /favicon.ico.
    head.append(f'<link rel="icon" href="{escape_attr(favicon or "data:,")}">')
    head.append(f'<link rel="stylesheet" href="{escape_attr(theme_href)}">')
    head.append(f'<style id="rw-styles"{nonce_attr}>{page_css}</style>')
    head.append(head_extra)
    tail = ""
    if manifest is not None and runtime_src is not None:
        tail = (
            f'<script type="application/json" id="rw-manifest">{json_for_script(manifest)}</script>'
            f'<script src="{escape_attr(runtime_src)}" defer{nonce_attr}></script>'
        )
    return f"<!doctype html><html{html_attrs}><head>{''.join(head)}</head><body>{body}{tail}</body></html>"
