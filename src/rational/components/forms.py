"""Accessible form controls.

Every control has a visible (or screen-reader-only) ``<label>``, a stable id,
and an error slot wired through ``aria-describedby`` that the browser runtime
fills when a submit handler's payload fails validation.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

from .._tracking import dom_id
from ..rendering.builder import EventValue, h
from ..rendering.nodes import Node
from ..styling.style import Style, merge

FORM = Style(layout="vertical", gap="md")
FIELD = Style(layout="vertical", gap=6, min_width=0)
LABEL = Style(font_size="sm", font_weight=600)
HELP = Style(font_size="sm", color="muted")
ERROR = Style(font_size="sm", color="danger")
CONTROL = Style(
    width="100%",
    padding_y=9,
    padding_x=12,
    border=True,
    border_radius="md",
    background="surface",
    color="on_surface",
    font_size="md",
    line_height=1.4,
    transition=True,
    focus=Style(
        border_color="primary",
        outline="none",
        shadow="0 0 0 3px color-mix(in srgb, var(--rw-color-primary) 25%, transparent)",
    ),
    placeholder=Style(color="muted"),
    disabled=Style(opacity=0.6, cursor="not-allowed"),
)
CHECK_ROW = Style(display="inline-flex", align="center", gap="sm", cursor="pointer")
CHECKBOX = Style(width=18, height=18, margin=0, raw={"accent-color": "var(--rw-color-primary)"})

_NAME_RE = re.compile(r"[^a-zA-Z0-9_]+")


def _name_from(label: str) -> str:
    return _NAME_RE.sub("_", label.strip().lower()).strip("_") or "field"


def Form(  # noqa: N802
    *children: Any,
    on_submit: EventValue = None,
    style: Style | None = None,
    key: str | int | None = None,
    **attrs: Any,
) -> Node:
    """A form whose submit sends all named fields to ``on_submit`` (no page reload).

    Annotate the handler parameter with a Pydantic model to validate the data.
    """
    return h("form", *children, on_submit=on_submit, key=key, style=merge(FORM, style), **attrs)


def _field(
    label: str,
    control_id: str,
    name: str,
    control: Node,
    *,
    help: str | None,
    error: str | None,
    hide_label: bool,
    style: Style | None,
    key: str | int | None,
) -> Node:
    label_node = h(
        "label",
        label,
        for_=control_id,
        class_="rw-sr-only" if hide_label else None,
        style=None if hide_label else LABEL,
    )
    return h("div", label_node, control, *_messages(control_id, name, help, error), key=key, style=merge(FIELD, style))


def _messages(control_id: str, name: str, help: str | None, error: str | None) -> list[Node]:  # noqa: A002
    """The help text, if any, and the error slot that the runtime fills when validation fails."""
    slot = h(
        "p",
        error or "",
        id=f"{control_id}-error",
        hidden=not error,
        data_rw_error_for=name,
        aria_live="polite",
        style=ERROR,
    )
    return [h("p", help, id=f"{control_id}-help", style=HELP), slot] if help else [slot]


def _a11y(control_id: str, help: str | None, error: str | None) -> dict[str, str | None]:
    """ARIA wiring shared by every labelled control: invalid state + help/error descriptions."""
    described = [f"{control_id}-help"] if help else []
    return {
        "aria_invalid": "true" if error else None,
        "aria_describedby": " ".join([*described, f"{control_id}-error"]),
    }


def Input(  # noqa: N802
    label: str,
    *,
    name: str | None = None,
    value: str | int | float | None = None,
    type: str = "text",  # noqa: A002
    placeholder: str | None = None,
    required: bool = False,
    disabled: bool = False,
    autocomplete: str | None = None,
    help: str | None = None,  # noqa: A002
    error: str | None = None,
    hide_label: bool = False,
    on_input: EventValue = None,
    on_change: EventValue = None,
    on_enter: EventValue = None,
    style: Style | None = None,
    key: str | int | None = None,
    **attrs: Any,
) -> Node:
    """A labelled text-like input. ``on_input`` handlers receive the value (debounced)."""
    name = name or _name_from(label)
    control_id = dom_id(name)
    control = h(
        "input",
        id=control_id,
        name=name,
        type=type,
        value=value,
        placeholder=placeholder,
        required=required,
        disabled=disabled,
        autocomplete=autocomplete,
        **_a11y(control_id, help, error),
        on_input=on_input,
        on_change=on_change,
        on_enter=on_enter,
        style=CONTROL,
        **attrs,
    )
    return _field(label, control_id, name, control, help=help, error=error, hide_label=hide_label, style=style, key=key)


def Textarea(  # noqa: N802
    label: str,
    *,
    name: str | None = None,
    value: str | None = None,
    rows: int = 4,
    placeholder: str | None = None,
    required: bool = False,
    help: str | None = None,  # noqa: A002
    error: str | None = None,
    hide_label: bool = False,
    on_input: EventValue = None,
    on_change: EventValue = None,
    style: Style | None = None,
    key: str | int | None = None,
    **attrs: Any,
) -> Node:
    name = name or _name_from(label)
    control_id = dom_id(name)
    control = h(
        "textarea",
        value or "",
        id=control_id,
        name=name,
        rows=rows,
        placeholder=placeholder,
        required=required,
        **_a11y(control_id, help, error),
        on_input=on_input,
        on_change=on_change,
        style=merge(CONTROL, Style(raw={"resize": "vertical"})),
        **attrs,
    )
    return _field(label, control_id, name, control, help=help, error=error, hide_label=hide_label, style=style, key=key)


def Select(  # noqa: N802
    label: str,
    options: Sequence[str | tuple[str, str]],
    *,
    name: str | None = None,
    value: str | None = None,
    required: bool = False,
    help: str | None = None,  # noqa: A002
    error: str | None = None,
    hide_label: bool = False,
    on_change: EventValue = None,
    style: Style | None = None,
    key: str | int | None = None,
    **attrs: Any,
) -> Node:
    """``options`` are values or ``(value, label)`` pairs."""
    name = name or _name_from(label)
    control_id = dom_id(name)
    option_nodes = []
    for option in options:
        opt_value, opt_label = option if isinstance(option, tuple) else (option, option)
        option_nodes.append(h("option", opt_label, value=opt_value, selected=opt_value == value))
    control = h(
        "select",
        *option_nodes,
        id=control_id,
        name=name,
        required=required,
        **_a11y(control_id, help, error),
        on_change=on_change,
        style=CONTROL,
        **attrs,
    )
    return _field(label, control_id, name, control, help=help, error=error, hide_label=hide_label, style=style, key=key)


def Checkbox(  # noqa: N802
    label: str,
    *,
    name: str | None = None,
    checked: bool = False,
    disabled: bool = False,
    help: str | None = None,  # noqa: A002
    error: str | None = None,
    on_change: EventValue = None,
    style: Style | None = None,
    key: str | int | None = None,
    **attrs: Any,
) -> Node:
    """``on_change`` handlers receive ``True``/``False``."""
    name = name or _name_from(label)
    control_id = dom_id(name)
    box = h(
        "input",
        type="checkbox",
        id=control_id,
        name=name,
        value="true",
        checked=checked,
        disabled=disabled,
        **_a11y(control_id, help, error),
        on_change=on_change,
        style=CHECKBOX,
        **attrs,
    )
    row = h("label", box, h("span", label), for_=control_id, style=CHECK_ROW)
    return h("div", row, *_messages(control_id, name, help, error), key=key, style=merge(FIELD, style))
