"""Dialogs, tabs, tables and toasts. Modal and tabs run in the browser, with no round trip."""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any, Literal

from ..events import js
from ..rendering.builder import h
from ..rendering.nodes import Node
from ..styling.style import Style, merge
from .basic import Button, Heading

SAFE_ID = re.compile(r"[A-Za-z][\w-]*\Z")


def _check_id(value: str) -> str:
    if not SAFE_ID.match(value):
        raise ValueError(f"id {value!r} must start with a letter and use only letters, digits, '-' and '_'")
    return value


MODAL = Style(
    border="1px solid var(--rw-color-border)",
    border_radius="lg",
    padding=0,
    background="surface",
    color="on_surface",
    max_width="min(32rem, calc(100vw - 2rem))",
    width="100%",
    shadow="0 20px 50px rgba(0,0,0,.3)",
)
MODAL_BODY = Style(display="flex", direction="column", gap="md", padding="lg")
TAB_LIST = Style(display="flex", gap="xs", border_bottom=True, overflow_x="auto")
TAB = Style(
    background="transparent",
    color="muted",
    border="0",
    border_bottom="2px solid transparent",
    padding_x="md",
    padding_y="sm",
    font_weight=600,
    cursor="pointer",
    white_space="nowrap",
    hover=Style(color="on_surface"),
)
TABLE_WRAP = Style(overflow_x="auto", border=True, border_radius="md")
TABLE = Style(width="100%", raw={"border-collapse": "collapse"}, font_size="sm")
CELL = Style(padding_y="sm", padding_x="md", text_align="left", border_bottom=True)
HEAD_CELL = merge(CELL, Style(background="surface_alt", font_weight=650))
TOASTS = Style(
    position="fixed",
    bottom="md",
    right="md",
    z_index=1000,
    display="flex",
    direction="column",
    gap="sm",
    max_width="min(24rem, calc(100vw - 2rem))",
)
TOAST = Style(
    display="flex",
    align="center",
    gap="md",
    padding="md",
    border_radius="md",
    border=True,
    background="surface",
    color="on_surface",
    shadow="0 8px 24px rgba(0,0,0,.2)",
)
TOAST_TONES: dict[str, Style] = {
    "neutral": Style(),
    **{tone: Style(border_left=f"4px solid var(--rw-color-{tone})") for tone in ("success", "warning", "danger")},
}

ToastTone = Literal["neutral", "success", "warning", "danger"]


def Modal(  # noqa: N802
    *children: Any,
    id: str,  # noqa: A002
    title: str,
    style: Style | None = None,
    **attrs: Any,
) -> Node:
    """A modal dialog. Open it with ``js.open_dialog("#<id>")``; Escape and the close button close it.

    The browser provides focus trapping, the backdrop and Escape. It is hidden until opened.
    """
    _check_id(id)
    title_id = f"{id}-title"
    return h(
        "dialog",
        h(
            "div",
            h(
                "div",
                Heading(title, level=3, id=title_id),
                Button("\u00d7", on_click=js.close_dialog(), variant="ghost", size="sm", aria_label="Close"),
                style=Style(display="flex", justify="space-between", align="center", gap="md"),
            ),
            *children,
            style=MODAL_BODY,
        ),
        id=id,
        aria_labelledby=title_id,
        style=merge(MODAL, style),
        **attrs,
    )


def Tabs(  # noqa: N802
    tabs: Sequence[tuple[str, Any]],
    *,
    id: str,  # noqa: A002
    selected: int = 0,
    style: Style | None = None,
    **attrs: Any,
) -> Node:
    """Switch between ``(label, content)`` panels in the browser, with no round trip.

    All panels are rendered; only the selected one is visible. Use ``selected`` for the initial tab.
    """
    _check_id(id)
    if not tabs:
        raise ValueError("Tabs needs at least one tab")
    if not 0 <= selected < len(tabs):
        raise ValueError("selected is out of range")
    buttons = []
    panels = []
    for i, (label, content) in enumerate(tabs):
        panel_id = f"{id}-panel-{i}"
        buttons.append(
            h(
                "button",
                label,
                type="button",
                role="tab",
                id=f"{id}-tab-{i}",
                aria_selected="true" if i == selected else "false",
                aria_controls=panel_id,
                style=TAB,
                on_click=[
                    js.set_attr("aria-selected", "false", f"#{id} [role=tab]"),
                    js.set_attr("aria-selected", "true"),
                    js.hide(f"#{id} [role=tabpanel]"),
                    js.show(f"#{panel_id}"),
                ],
            )
        )
        panels.append(
            h("div", content, role="tabpanel", id=panel_id, aria_labelledby=f"{id}-tab-{i}", hidden=i != selected)
        )
    return h(
        "div",
        h("div", *buttons, role="tablist", style=TAB_LIST),
        h("div", *panels, style=Style(padding_y="md")),
        id=id,
        style=style,
        **attrs,
    )


def Table(  # noqa: N802
    headers: Sequence[Any],
    rows: Sequence[Sequence[Any]],
    *,
    caption: str | None = None,
    empty: Any = None,
    style: Style | None = None,
    **attrs: Any,
) -> Node:
    """A semantic data table. Cells may be text or any node."""
    width = len(headers)
    for row in rows:
        if len(row) != width:
            raise ValueError(f"every row needs {width} cells, got {len(row)}")
    body = [h("tr", *(h("td", cell, style=CELL) for cell in row)) for row in rows]
    if not body and empty is not None:
        body = [h("tr", h("td", empty, colspan=width, style=merge(CELL, Style(text_align="center", color="muted"))))]
    return h(
        "div",
        h(
            "table",
            h("caption", caption, class_="rw-sr-only") if caption else None,
            h("thead", h("tr", *(h("th", head, scope="col", style=HEAD_CELL) for head in headers))),
            h("tbody", *body),
            style=TABLE,
        ),
        style=merge(TABLE_WRAP, style),
        **attrs,
    )


def Toast(  # noqa: N802
    *children: Any,
    tone: ToastTone = "neutral",
    dismissible: bool = True,
    style: Style | None = None,
    key: str | int | None = None,
    **attrs: Any,
) -> Node:
    """A transient message. Put toasts inside ``Toasts``; the close button removes it in the browser."""
    if tone not in TOAST_TONES:
        raise ValueError(f"unknown toast tone {tone!r}; use one of {sorted(TOAST_TONES)}")
    role = "alert" if tone == "danger" else "status"
    return h(
        "div",
        h("div", *children, style=Style(grow=1)),
        Button(
            "\u00d7",
            on_click=js.remove("closest:[data-toast]"),
            variant="ghost",
            size="sm",
            aria_label="Dismiss",
        )
        if dismissible
        else None,
        key=key,
        role=role,
        data_toast=True,
        style=merge(TOAST, TOAST_TONES[tone], style),
        **attrs,
    )


def Toasts(*toasts: Any, style: Style | None = None, **attrs: Any) -> Node:  # noqa: N802
    """The fixed corner region that stacks toasts. Announced politely to screen readers."""
    return h("div", *toasts, aria_live="polite", style=merge(TOASTS, style), **attrs)
