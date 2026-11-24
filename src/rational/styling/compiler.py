"""Compile ``Style`` objects into hashed, deduplicated CSS classes."""

from __future__ import annotations

import hashlib
from collections import OrderedDict
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from .responsive import DEFAULT_BREAKPOINTS, DEFAULT_CONTAINERS, Breakpoint
from .style import UNSAFE_VALUE, Style, StyleError
from .theme import Theme, get_theme

_ALIGN = {"between": "space-between", "around": "space-around", "evenly": "space-evenly"}
_PSEUDO: dict[str, tuple[str, ...]] = {
    "hover": (":hover",),
    "focus": (":focus",),
    "focus_visible": (":focus-visible",),
    "active": (":active",),
    "disabled": (":disabled", "[aria-disabled=true]"),
    "placeholder": ("::placeholder",),
}
_HOVER_MEDIA = "@media (hover: hover)"
_DEFAULT_TRANSITION = (
    "color var(--rw-motion) ease,background-color var(--rw-motion) ease,"
    "border-color var(--rw-motion) ease,box-shadow var(--rw-motion) ease,"
    "transform var(--rw-motion) ease,opacity var(--rw-motion) ease"
)


@dataclass(frozen=True, slots=True)
class CompiledStyle:
    class_name: str
    rules: tuple[str, ...]


Rule = tuple[tuple[str, ...], tuple[str, ...], str]  # (at-rules, selector suffixes, declarations)


class StyleCompiler:
    """Resolves tokens against a theme; caches compiled styles by value."""

    def __init__(
        self,
        theme: str | Theme = "modern",
        breakpoints: Mapping[str, Breakpoint] | None = None,
        containers: Mapping[str, Breakpoint] | None = None,
    ) -> None:
        self.theme = get_theme(theme)
        self.breakpoints = {**DEFAULT_BREAKPOINTS, **(breakpoints or {})}
        self.containers = {**DEFAULT_CONTAINERS, **(containers or {})}
        self._cache: OrderedDict[tuple[Any, ...], CompiledStyle] = OrderedDict()  # bounded LRU
        self._max_cache = 10_000  # styles derived from changing data must not grow memory forever
        self._props: dict[str, Callable[[Style, Any], list[tuple[str, str]]]] = self._property_table()

    def compile(self, style: Style) -> CompiledStyle:
        key = style.key()
        cached = self._cache.get(key)
        if cached is not None:
            self._cache.move_to_end(key)
            return cached
        rules: list[Rule] = []
        self._collect(style, (), ("",), rules)
        canonical = "|".join(f"{at}{sfx}{decls}" for at, sfx, decls in rules)
        name = "rw-" + hashlib.sha256(canonical.encode()).hexdigest()[:8]
        compiled = CompiledStyle(name, tuple(self._render(name, r) for r in rules))
        self._cache[key] = compiled
        while len(self._cache) > self._max_cache:
            self._cache.popitem(last=False)
        return compiled

    def declarations(self, style: Style) -> str:
        out: list[tuple[str, str]] = []
        for name, value in style.items():
            handler = self._props.get(name)
            if handler is not None:
                out.extend(handler(style, value))
        if style.raw:
            out.extend((prop, _safe(str(value))) for prop, value in style.raw.items())
        return "".join(f"{p}:{v};" for p, v in out)

    # -- internals -----------------------------------------------------------------

    def _collect(self, style: Style, at: tuple[str, ...], suffixes: tuple[str, ...], rules: list[Rule]) -> None:
        decls = self.declarations(style)
        if decls:
            rules.append((at, suffixes, decls))
        for pseudo, alternatives in _PSEUDO.items():
            sub = getattr(style, pseudo)
            if sub is not None:
                nested = tuple(s + a for s in suffixes for a in alternatives)
                inner_at = (*at, _HOVER_MEDIA) if pseudo == "hover" and _HOVER_MEDIA not in at else at
                self._collect(sub, inner_at, nested, rules)
        if style.viewport:
            for name, sub in self._ordered(style.viewport, self.breakpoints, "breakpoint"):
                self._collect(sub, (*at, f"@media {name}"), suffixes, rules)
        if style.container:
            for name, sub in self._ordered(style.container, self.containers, "container size"):
                self._collect(sub, (*at, f"@container {name}"), suffixes, rules)

    @staticmethod
    def _ordered(
        variants: Mapping[str, Style], registry: Mapping[str, Breakpoint], what: str
    ) -> list[tuple[str, Style]]:
        out = []
        for name, sub in variants.items():
            if name not in registry:
                raise StyleError(f"unknown {what} {name!r}; known: {sorted(registry)}")
            out.append((registry[name], sub))
        out.sort(key=lambda pair: pair[0].sort_key())
        return [(bp.condition(), sub) for bp, sub in out]

    @staticmethod
    def _render(name: str, rule: Rule) -> str:
        at, suffixes, decls = rule
        text = ",".join(f".{name}{s}" for s in suffixes) + "{" + decls + "}"
        for wrapper in reversed(at):
            text = f"{wrapper}{{{text}}}"
        return text

    def _token(self, scale: Mapping[str, str], var: str, value: Any, *, px: bool = True) -> str:
        if isinstance(value, bool):
            raise StyleError(f"unexpected boolean {value!r}")
        if isinstance(value, (int, float)):
            if value == 0:
                return "0"
            return f"{value:g}px" if px else f"{value:g}"
        if value in scale:
            return f"var(--rw-{var}-{value})"
        return _safe(value)

    def _property_table(self) -> dict[str, Handler]:
        h = _Handlers(self)
        table: dict[str, Handler] = {
            "display": h.plain("display"),
            "layout": h.layout,
            "direction": h.plain("flex-direction"),
            "wrap": h.wrap,
            "justify": h.plain("justify-content", _ALIGN),
            "align": h.plain("align-items", _ALIGN),
            "align_self": h.plain("align-self"),
            "gap": h.space("gap"),
            "row_gap": h.space("row-gap"),
            "column_gap": h.space("column-gap"),
            "grow": h.plain("flex-grow"),
            "shrink": h.plain("flex-shrink"),
            "basis": h.length("flex-basis"),
            "columns": h.tracks("grid-template-columns"),
            "rows": h.tracks("grid-template-rows"),
            "column_span": h.span,
            "position": h.plain("position"),
            "z_index": h.plain("z-index"),
            "overflow": h.plain("overflow"),
            "overflow_x": h.plain("overflow-x"),
            "overflow_y": h.plain("overflow-y"),
            "padding_x": h.space("padding-inline"),
            "padding_y": h.space("padding-block"),
            "margin_x": h.space("margin-inline"),
            "margin_y": h.space("margin-block"),
            "aspect_ratio": h.plain("aspect-ratio"),
            "font_family": h.font_family,
            "font_size": h.length("font-size", self.theme.font_size, "font-size"),
            "font_weight": h.plain("font-weight"),
            "line_height": h.plain("line-height"),
            "letter_spacing": h.length("letter-spacing"),
            "text_align": h.plain("text-align"),
            "text_transform": h.plain("text-transform"),
            "text_decoration": h.plain("text-decoration"),
            "white_space": h.plain("white-space"),
            "color": h.color("color"),
            "background": h.color("background"),
            "border_color": h.color("border-color"),
            "border_width": h.length("border-width"),
            "border_style": h.plain("border-style"),
            "border_radius": h.length("border-radius", self.theme.radius, "radius"),
            "outline": h.plain("outline"),
            "shadow": h.shadow,
            "opacity": h.plain("opacity"),
            "cursor": h.plain("cursor"),
            "transition": h.transition,
            "transform": h.plain("transform"),
            "pointer_events": h.plain("pointer-events"),
            "user_select": h.plain("user-select"),
            "list_style": h.plain("list-style"),
            "object_fit": h.plain("object-fit"),
            "container_type": h.plain("container-type"),
            "container_name": h.plain("container-name"),
        }
        for side in ("", "_top", "_right", "_bottom", "_left"):
            table[f"padding{side}"] = h.space(f"padding{side.replace('_', '-')}")
            table[f"margin{side}"] = h.space(f"margin{side.replace('_', '-')}")
        for prop in ("top", "right", "bottom", "left", "inset"):
            table[prop] = h.space(prop)
        for prop in ("width", "height", "min_width", "max_width", "min_height", "max_height"):
            table[prop] = h.length(prop.replace("_", "-"))
        for prop in ("border", "border_top", "border_right", "border_bottom", "border_left"):
            table[prop] = h.border(prop.replace("_", "-"))
        return table


Handler = Callable[[Style, Any], list[tuple[str, str]]]  # a Style attribute's value -> CSS declarations


class _Handlers:
    """How each kind of Style attribute becomes CSS declarations, with the compiler's theme."""

    def __init__(self, compiler: StyleCompiler) -> None:
        self.compiler = compiler
        self.theme = compiler.theme

    def plain(self, css: str, mapping: Mapping[str, str] | None = None) -> Handler:
        def fn(_s: Style, v: Any) -> list[tuple[str, str]]:
            text = str(v)
            if mapping is not None and text in mapping:
                return [(css, mapping[text])]
            return [(css, _safe(text))]  # anything else is checked, whatever type it came as

        return fn

    def length(self, css: str, scale: Mapping[str, str] | None = None, var: str = "space") -> Handler:
        def fn(_s: Style, v: Any) -> list[tuple[str, str]]:
            return [(css, self.compiler._token(scale or {}, var, v))]

        return fn

    def space(self, *props: str) -> Handler:
        def fn(_s: Style, v: Any) -> list[tuple[str, str]]:
            value = self.compiler._token(self.theme.space, "space", v)
            return [(p, value) for p in props]

        return fn

    def color(self, css: str) -> Handler:
        def fn(_s: Style, v: Any) -> list[tuple[str, str]]:
            if v in self.theme.color_names:
                return [(css, f"var(--rw-color-{v.replace('_', '-')})")]
            return [(css, _safe(str(v)))]

        return fn

    def border(self, css: str) -> Handler:
        def fn(_s: Style, v: Any) -> list[tuple[str, str]]:
            if v is True:
                return [(css, "1px solid var(--rw-color-border)")]
            if v is False:
                return [(css, "0")]
            return [(css, _safe(str(v)))]

        return fn

    def layout(self, s: Style, v: Any) -> list[tuple[str, str]]:
        if v not in ("vertical", "horizontal"):
            raise StyleError(f"layout must be 'vertical' or 'horizontal', not {v!r}")
        out = [] if s.display is not None else [("display", "flex")]
        return [*out, ("flex-direction", "column" if v == "vertical" else "row")]

    def wrap(self, _s: Style, v: Any) -> list[tuple[str, str]]:
        return [("flex-wrap", "wrap" if v is True else "nowrap" if v is False else _safe(str(v)))]

    def tracks(self, css: str) -> Handler:
        def fn(_s: Style, v: Any) -> list[tuple[str, str]]:
            if isinstance(v, int):
                return [(css, f"repeat({v},minmax(0,1fr))")]
            return [(css, _safe(str(v)))]

        return fn

    def span(self, _s: Style, v: Any) -> list[tuple[str, str]]:
        return [("grid-column", f"span {v}/span {v}" if isinstance(v, int) else _safe(str(v)))]

    def transition(self, _s: Style, v: Any) -> list[tuple[str, str]]:
        if v is True:
            return [("transition", _DEFAULT_TRANSITION)]
        return [("transition", "none" if v is False else _safe(str(v)))]

    def font_family(self, _s: Style, v: Any) -> list[tuple[str, str]]:
        if v in self.theme.fonts:
            return [("font-family", f"var(--rw-font-{v})")]
        return [("font-family", _safe(str(v)))]

    def shadow(self, _s: Style, v: Any) -> list[tuple[str, str]]:
        if v in self.theme.shadows:
            return [("box-shadow", f"var(--rw-shadow-{v})")]
        return [("box-shadow", _safe(str(v)))]


def _safe(value: str) -> str:
    if UNSAFE_VALUE.search(value):  # defense in depth; Style() validates on construction
        raise StyleError(f"unsafe characters in CSS value {value!r}")
    return value


class StyleSheet:
    """Collects the rules a page uses; remembers what the browser already has."""

    def __init__(self, compiler: StyleCompiler) -> None:
        self.compiler = compiler
        self._seen: set[str] = set()
        self._pending: list[str] = []

    def use(self, style: Style) -> str:
        compiled = self.compiler.compile(style)
        if compiled.class_name not in self._seen:
            self._seen.add(compiled.class_name)
            self._pending.extend(compiled.rules)
        return compiled.class_name

    def drain(self) -> list[str]:
        """Rules added since the last drain (to ship with an event response)."""
        pending, self._pending = self._pending, []
        return pending
