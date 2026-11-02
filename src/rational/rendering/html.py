"""Deterministic HTML serialization of resolved node trees."""

from __future__ import annotations

from typing import Any

from .nodes import Node, RawHTML, TextNode

VOID_TAGS = frozenset(
    {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
)

_TEXT_ESCAPES = str.maketrans({"&": "&amp;", "<": "&lt;", ">": "&gt;"})
_ATTR_ESCAPES = str.maketrans({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#x27;"})


def escape_text(text: str) -> str:
    return text.translate(_TEXT_ESCAPES)


def escape_attr(value: str) -> str:
    return value.translate(_ATTR_ESCAPES)


def to_html(node: Any, *, component_ids: bool = True) -> str:
    """``component_ids=False`` leaves out the markers meant for the browser runtime."""
    parts: list[str] = []
    _write(node, parts, component_ids)
    return "".join(parts)


def _write(node: Any, out: list[str], component_ids: bool) -> None:
    if isinstance(node, TextNode):
        out.append(escape_text(node.text))
    elif isinstance(node, RawHTML):
        out.append(node.html)
    elif isinstance(node, Node):
        if node.events or node.style is not None or node.client:
            raise ValueError(f"<{node.tag}> is unresolved; render it through the Renderer")
        out.append("<")
        out.append(node.tag)
        for name, value in node.attrs:
            if value is None or value is False or (name == "data-rw-c" and not component_ids):
                continue
            if value is True:
                out.append(f" {name}")
            else:
                out.append(f' {name}="{escape_attr(str(value))}"')
        out.append(">")
        if node.tag in VOID_TAGS:
            if node.children:
                raise ValueError(f"<{node.tag}> cannot have children")
            return
        for child in node.children:
            _write(child, out, component_ids)
        out.append(f"</{node.tag}>")
    elif isinstance(node, (list, tuple)):
        for child in node:
            _write(child, out, component_ids)
    else:
        raise TypeError(f"cannot serialize {type(node).__name__}; render it through the Renderer")
