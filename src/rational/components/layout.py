"""Layout primitives: thin wrappers over flexbox and grid, with responsive defaults."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal

from .._tracking import dom_id
from ..rendering.builder import h
from ..rendering.nodes import Node
from ..styling.style import Length, Style, merge
from .basic import Heading

CARD = Style(
    background="surface",
    color="on_surface",
    border=True,
    border_radius="lg",
    padding="lg",
    shadow="sm",
    layout="vertical",
    gap="md",
    min_width=0,
)


def Stack(  # noqa: N802
    *children: Any,
    direction: Literal["vertical", "horizontal"] = "vertical",
    gap: Length | None = "md",
    align: str | None = None,
    justify: str | None = None,
    wrap: bool = False,
    collapse: str | None = None,
    tag: str = "div",
    style: Style | None = None,
    key: str | int | None = None,
    **attrs: Any,
) -> Node:
    """Flex container. ``collapse="mobile"`` turns a horizontal stack vertical at that breakpoint."""
    own = Style(
        layout=direction,
        gap=gap,
        align=align,
        justify=justify,
        wrap=True if wrap else None,
        viewport={collapse: Style(layout="vertical", align="stretch")} if collapse else None,
    )
    return h(tag, *children, key=key, style=merge(own, style), **attrs)


def Row(*children: Any, align: str | None = "center", **kwargs: Any) -> Node:  # noqa: N802
    return Stack(*children, direction="horizontal", align=align, **kwargs)


def Column(*children: Any, **kwargs: Any) -> Node:  # noqa: N802
    return Stack(*children, direction="vertical", **kwargs)


def Grid(  # noqa: N802
    *children: Any,
    columns: int | None = None,
    min_column_width: int = 240,
    gap: Length = "md",
    tag: str = "div",
    style: Style | None = None,
    key: str | int | None = None,
    **attrs: Any,
) -> Node:
    """With ``columns=n``: n equal columns, one column on mobile.
    Without: as many columns of at least ``min_column_width`` px as fit (no media queries)."""
    if columns is not None:
        own = Style(
            display="grid", gap=gap, columns=columns, viewport={"mobile": Style(columns=1)} if columns > 1 else None
        )
    else:
        own = Style(display="grid", gap=gap, columns=f"repeat(auto-fit,minmax(min({min_column_width}px,100%),1fr))")
    return h(tag, *children, key=key, style=merge(own, style), **attrs)


def Card(  # noqa: N802
    *children: Any,
    title: str | None = None,
    style: Style | None = None,
    key: str | int | None = None,
    **attrs: Any,
) -> Node:
    if title is None:
        return h("div", *children, key=key, style=merge(CARD, style), **attrs)
    heading_id = dom_id("card-title")
    return h(
        "section",
        Heading(title, level=3, id=heading_id),
        *children,
        key=key,
        style=merge(CARD, style),
        aria_labelledby=heading_id,
        **attrs,
    )


def Container(  # noqa: N802
    *children: Any,
    max_width: Length = 1120,
    tag: str = "div",
    style: Style | None = None,
    key: str | int | None = None,
    **attrs: Any,
) -> Node:
    own = Style(width="100%", max_width=max_width, margin_x="auto", padding_x="md")
    return h(tag, *children, key=key, style=merge(own, style), **attrs)


def Spacer(*, style: Style | None = None) -> Node:  # noqa: N802
    """Takes the remaining space in a Row/Column."""
    return h("div", style=merge(Style(grow=1), style), aria_hidden="true")


def Divider(*, style: Style | None = None) -> Node:  # noqa: N802
    return h("hr", style=merge(Style(border=False, border_top=True, margin_y="md", width="100%"), style))


def _region(tag: str) -> Callable[..., Node]:
    def build(*children: Any, style: Style | None = None, key: str | int | None = None, **attrs: Any) -> Node:
        return h(tag, *children, key=key, style=style, **attrs)

    build.__name__ = build.__qualname__ = tag.capitalize()
    build.__doc__ = f"A semantic <{tag}> element."
    return build


Header = _region("header")
Main = _region("main")
Footer = _region("footer")
Nav = _region("nav")
Section = _region("section")
Article = _region("article")
Aside = _region("aside")
