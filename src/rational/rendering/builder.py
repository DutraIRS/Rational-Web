"""``h()``: the low-level element builder every primitive is made from."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from ..events import ClientOp
from .nodes import EVENT_NAMES, AttrValue, Node, TextNode, flatten

if TYPE_CHECKING:
    from ..styling.style import Style

EventValue = Callable[..., Any] | ClientOp | list[Callable[..., Any] | ClientOp] | None


def attr_name(py_name: str) -> str:
    """``class_`` -> ``class``, ``aria_label`` -> ``aria-label``, ``data_x`` -> ``data-x``."""
    return py_name.rstrip("_").replace("_", "-")


def h(
    tag: str,
    *children: Any,
    key: str | int | None = None,
    style: Style | None = None,
    **kwargs: Any,
) -> Node:
    """Build an element.

    ``on_<event>=`` accepts a server handler, a ``js.*`` client operation or a
    list mixing both. Every other keyword is an HTML attribute (see ``attr_name``).
    """
    attrs: list[tuple[str, AttrValue]] = []
    events: list[tuple[str, Callable[..., Any]]] = []
    client: list[tuple[str, tuple[ClientOp, ...]]] = []
    for py_name, value in kwargs.items():
        if py_name.startswith("on_"):
            event = py_name[3:]
            if event not in EVENT_NAMES:
                raise ValueError(f"unsupported event {event!r}; expected one of {sorted(EVENT_NAMES)}")
            handlers, ops = split_event_value(value)
            events.extend((event, fn) for fn in handlers)
            if ops:
                client.append((event, tuple(ops)))
            continue
        attrs.append((attr_name(py_name), value))
    return Node(
        tag,
        attrs=tuple(attrs),
        children=tuple(normalize_children(children)),
        key=None if key is None else str(key),
        style=style,
        events=tuple(events),
        client=tuple(client),
    )


def split_event_value(value: EventValue) -> tuple[list[Callable[..., Any]], list[ClientOp]]:
    items = value if isinstance(value, list) else [value]
    handlers: list[Callable[..., Any]] = []
    ops: list[ClientOp] = []
    for item in items:
        if item is None:
            continue
        if isinstance(item, ClientOp):
            ops.append(item)
        elif callable(item):
            handlers.append(item)
        else:
            raise TypeError(f"event handlers must be callables or js.* operations, got {item!r}")
    if len(handlers) > 1:
        raise ValueError("only one server handler per event; combine them in one method")
    return handlers, ops


def normalize_children(children: Any) -> list[Any]:
    out = []
    for child in flatten(children):
        if isinstance(child, str):
            out.append(TextNode(child))
        elif callable(child) and not hasattr(child, "render"):
            out.extend(normalize_children([child()]))
        else:
            out.append(child)
    return out
