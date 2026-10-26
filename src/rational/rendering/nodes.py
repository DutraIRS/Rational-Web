"""Immutable intermediate representation of rendered markup.

A tree built by components is *unresolved*: elements may still carry a
``Style`` and event bindings, and may contain ``Component`` instances as
children. The renderer turns it into a *resolved* tree in which styles are
class names, events are ``data-rw-*`` attributes and components are expanded.
Only resolved trees are serialized.
"""

from __future__ import annotations

import functools
import re
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, TypeAlias

if TYPE_CHECKING:
    from ..events import ClientOp
    from ..styling.style import Style

AttrValue: TypeAlias = str | int | float | bool | None

EVENT_NAMES = frozenset({"click", "input", "change", "submit", "keydown", "enter", "blur"})

_TAG_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9-]*$")
_ATTR_RE = re.compile(r"^[a-zA-Z_:][-a-zA-Z0-9_:.]*$")
_FORBIDDEN_TAGS = frozenset({"script", "style"})
_FORBIDDEN_ATTRS = frozenset({"srcdoc"})
_URL_ATTRS = frozenset({"href", "src", "action", "formaction", "poster", "cite", "data", "xlink:href"})
_UNSAFE_SCHEMES = ("javascript:", "vbscript:", "data:")
_CONTROL_RE = re.compile(r"[\x00-\x20\x7f]+")


class UnsafeMarkupError(ValueError):
    """Raised when markup would allow script injection."""


@dataclass(frozen=True, slots=True)
class TextNode:
    text: str


@dataclass(frozen=True, slots=True)
class RawHTML:
    """Pre-built markup that bypasses escaping. Create it only via ``unsafe_html``."""

    html: str


@dataclass(frozen=True, slots=True)
class Node:
    tag: str
    attrs: tuple[tuple[str, AttrValue], ...] = ()
    children: tuple[Any, ...] = ()
    key: str | None = None
    style: Style | None = None
    events: tuple[tuple[str, Callable[..., Any]], ...] = ()
    client: tuple[tuple[str, tuple[ClientOp, ...]], ...] = field(default=())

    def __post_init__(self) -> None:
        validate_tag(self.tag)
        for name, value in self.attrs:
            validate_attr(name, value)

    def attr(self, name: str) -> AttrValue:
        for n, v in self.attrs:
            if n == name:
                return v
        return None


def unsafe_html(html: str) -> RawHTML:
    """Insert ``html`` verbatim. The caller is responsible for sanitizing it."""
    return RawHTML(html)


@functools.lru_cache(maxsize=512)
def validate_tag(tag: str) -> None:
    # Cached: an app uses a small set of tag names, and only valid ones get cached (errors raise).
    if not _TAG_RE.match(tag):
        raise UnsafeMarkupError(f"invalid tag name {tag!r}")
    if tag.lower() in _FORBIDDEN_TAGS:
        raise UnsafeMarkupError(f"<{tag}> elements are not allowed; use unsafe_html() deliberately")


def validate_attr(name: str, value: AttrValue) -> None:
    """Reject attribute names and values that could run script (``on*``, ``srcdoc``, ``javascript:`` URLs)."""
    if _is_url_attr(name) and isinstance(value, str):
        check_url(value)


@functools.lru_cache(maxsize=1024)
def _is_url_attr(name: str) -> bool:
    """Validate an attribute *name* (cached) and report whether its value is a URL."""
    if not _ATTR_RE.match(name):
        raise UnsafeMarkupError(f"invalid attribute name {name!r}")
    lowered = name.lower()
    if lowered.startswith("on"):
        raise UnsafeMarkupError(f"inline handler attribute {name!r} is not allowed; pass on_<event>=handler instead")
    if lowered in _FORBIDDEN_ATTRS:
        raise UnsafeMarkupError(f"attribute {name!r} can carry script; use unsafe_html() deliberately")
    return lowered in _URL_ATTRS


def check_url(value: str) -> None:
    normalized = _CONTROL_RE.sub("", value).lower()
    if normalized.startswith("data:image/") and not normalized.startswith("data:image/svg"):
        return
    if normalized.startswith(_UNSAFE_SCHEMES):
        raise UnsafeMarkupError(f"unsafe URL scheme in {value[:40]!r}")


def flatten(items: Iterable[Any]) -> list[Any]:
    """Flatten nested lists/tuples and drop ``None``/``False``; numbers become strings."""
    out: list[Any] = []
    for item in items:
        if item is None or item is False or item is True:
            continue
        if isinstance(item, (list, tuple, Iterator)):
            out.extend(flatten(item))
        elif isinstance(item, (int, float)):
            out.append(str(item))
        else:
            out.append(item)
    return out
