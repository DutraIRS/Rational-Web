"""``Style``: an immutable, typed bundle of CSS declarations.

``None`` means "unspecified" (never CSS ``none``). ``a | b`` merges right-biased:
every property set in ``b`` wins; nested pseudo-state and responsive styles are
merged recursively.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Literal, TypeAlias

Length: TypeAlias = int | float | str
Color: TypeAlias = str

UNSAFE_VALUE = re.compile(r"[;{}<>]|/\*")
RAW_PROPERTY = re.compile(r"^-{0,2}[a-zA-Z][a-zA-Z0-9-]*$")


class StyleError(ValueError):
    """An invalid or unsafe style value."""


PSEUDO_FIELDS = ("hover", "focus", "focus_visible", "active", "disabled", "placeholder")
MAPPING_FIELDS = ("viewport", "container", "raw")


@dataclass(frozen=True, eq=True, repr=False)
class Style:
    # layout
    display: str | None = None
    layout: Literal["vertical", "horizontal"] | None = None
    direction: str | None = None
    wrap: bool | str | None = None
    justify: str | None = None
    align: str | None = None
    align_self: str | None = None
    gap: Length | None = None
    row_gap: Length | None = None
    column_gap: Length | None = None
    grow: int | float | None = None
    shrink: int | float | None = None
    basis: Length | None = None
    columns: int | str | None = None
    rows: int | str | None = None
    column_span: int | str | None = None
    position: str | None = None
    top: Length | None = None
    right: Length | None = None
    bottom: Length | None = None
    left: Length | None = None
    inset: Length | None = None
    z_index: int | None = None
    overflow: str | None = None
    overflow_x: str | None = None
    overflow_y: str | None = None
    # spacing
    padding: Length | None = None
    padding_x: Length | None = None
    padding_y: Length | None = None
    padding_top: Length | None = None
    padding_right: Length | None = None
    padding_bottom: Length | None = None
    padding_left: Length | None = None
    margin: Length | None = None
    margin_x: Length | None = None
    margin_y: Length | None = None
    margin_top: Length | None = None
    margin_right: Length | None = None
    margin_bottom: Length | None = None
    margin_left: Length | None = None
    # sizing
    width: Length | None = None
    height: Length | None = None
    min_width: Length | None = None
    max_width: Length | None = None
    min_height: Length | None = None
    max_height: Length | None = None
    aspect_ratio: str | float | None = None
    # typography
    font_family: str | None = None
    font_size: Length | None = None
    font_weight: int | str | None = None
    line_height: float | str | None = None
    letter_spacing: Length | None = None
    text_align: str | None = None
    text_transform: str | None = None
    text_decoration: str | None = None
    white_space: str | None = None
    color: Color | None = None
    # surface
    background: Color | None = None
    border: bool | str | None = None
    border_top: bool | str | None = None
    border_right: bool | str | None = None
    border_bottom: bool | str | None = None
    border_left: bool | str | None = None
    border_color: Color | None = None
    border_width: Length | None = None
    border_style: str | None = None
    border_radius: Length | None = None
    outline: str | None = None
    shadow: str | None = None
    opacity: float | None = None
    # behavior
    cursor: str | None = None
    transition: bool | str | None = None
    transform: str | None = None
    pointer_events: str | None = None
    user_select: str | None = None
    list_style: str | None = None
    object_fit: str | None = None
    container_type: str | None = None
    container_name: str | None = None
    # nested
    hover: Style | None = None
    focus: Style | None = None
    focus_visible: Style | None = None
    active: Style | None = None
    disabled: Style | None = None
    placeholder: Style | None = None
    viewport: Mapping[str, Style] | None = None
    container: Mapping[str, Style] | None = None
    raw: Mapping[str, str] | None = None

    _items: tuple[tuple[str, Any], ...] = field(init=False, repr=False, compare=False)
    _key: tuple[Any, ...] = field(init=False, repr=False, compare=False)
    _hash: int = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        # One pass: validate eagerly (so errors point at the line that built the style),
        # freeze mappings, and cache the set fields and the value key. Styles are immutable,
        # so hashing, equality and compiler cache lookups never walk all fields again.
        items: list[tuple[str, Any]] = []
        for name, value in self.__dict__.items():
            if value is None:
                continue
            if isinstance(value, str) and UNSAFE_VALUE.search(value):
                raise StyleError(f"unsafe characters in {name}={value!r}")
            if name in MAPPING_FIELDS:
                value = MappingProxyType(dict(value))
                object.__setattr__(self, name, value)
            items.append((name, value))
        for prop, raw_value in (self.raw or {}).items():
            if not RAW_PROPERTY.match(prop):
                raise StyleError(f"invalid raw CSS property {prop!r}")
            if UNSAFE_VALUE.search(str(raw_value)):
                raise StyleError(f"unsafe characters in raw[{prop!r}]={raw_value!r}")
        key = tuple((name, _key_of(value)) for name, value in items)
        object.__setattr__(self, "_items", tuple(items))
        object.__setattr__(self, "_key", key)
        object.__setattr__(self, "_hash", hash(key))

    def __or__(self, other: Style | None) -> Style:
        if other is None:
            return self
        if not isinstance(other, Style):
            return NotImplemented
        cache_key = (self._key, other._key)
        cached = _MERGE_CACHE.get(cache_key)
        if cached is not None:
            return cached
        merged = dict(self._items)
        for name, b in other._items:
            a = merged.get(name)
            if a is None:
                merged[name] = b
            elif name in PSEUDO_FIELDS:
                merged[name] = a | b
            elif name in ("viewport", "container"):
                merged[name] = {k: (a[k] | b[k]) if k in a and k in b else b.get(k, a.get(k)) for k in {**a, **b}}
            elif name == "raw":
                merged[name] = {**a, **b}
            else:
                merged[name] = b
        result = Style(**merged)
        if len(_MERGE_CACHE) >= _MERGE_CACHE_SIZE:
            _MERGE_CACHE.clear()
        _MERGE_CACHE[cache_key] = result
        return result

    def __ror__(self, other: Style | None) -> Style:
        if other is None:
            return self
        return NotImplemented

    def items(self) -> tuple[tuple[str, Any], ...]:
        """The set (non-``None``) fields, in declaration order."""
        return self._items

    def key(self) -> tuple[Any, ...]:
        """A hashable value identity: equal styles have equal keys."""
        return self._key

    def __hash__(self) -> int:
        return self._hash

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Style) and self._key == other._key

    def __repr__(self) -> str:
        return "Style(" + ", ".join(f"{k}={v!r}" for k, v in self._items) + ")"

    def __bool__(self) -> bool:
        return bool(self._items)


_MERGE_CACHE: dict[tuple[Any, Any], Style] = {}
_MERGE_CACHE_SIZE = 4096


def _key_of(value: Any) -> Any:
    if isinstance(value, Style):
        return value._key
    if isinstance(value, Mapping):
        return tuple(sorted((k, _key_of(v)) for k, v in value.items()))
    return value


def merge(*styles: Style | None) -> Style | None:
    out: Style | None = None
    for s in styles:
        if s is not None:
            out = s if out is None else out | s
    return out
