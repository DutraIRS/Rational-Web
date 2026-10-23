"""Event payloads and declarative browser-local operations.

Python never runs in the browser. ``js.*`` builds a small, closed set of
operations that the runtime executes locally, with no server round trip.
Targets are CSS selectors; ``None`` means the element itself and
``"closest:<selector>"`` searches its ancestors.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .styling.theme import ThemeMode


@dataclass(frozen=True, slots=True)
class Event:
    """Generic payload for handlers annotated with ``event: Event``."""

    name: str
    value: Any = None
    key: str | None = None
    form: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ClientOp:
    op: str
    args: tuple[str | None, ...]

    def to_json(self) -> list[str | None]:
        return [self.op, *self.args]


class js:  # noqa: N801 - used as a namespace: js.toggle_class(...)
    @staticmethod
    def toggle_class(cls: str, target: str | None = None) -> ClientOp:
        return ClientOp("toggle_class", (target, cls))

    @staticmethod
    def add_class(cls: str, target: str | None = None) -> ClientOp:
        return ClientOp("add_class", (target, cls))

    @staticmethod
    def remove_class(cls: str, target: str | None = None) -> ClientOp:
        return ClientOp("remove_class", (target, cls))

    @staticmethod
    def set_attr(name: str, value: str, target: str | None = None) -> ClientOp:
        return ClientOp("set_attr", (target, name, value))

    @staticmethod
    def toggle_attr(name: str, on: str = "true", off: str = "false", target: str | None = None) -> ClientOp:
        """Flip ``name`` between two values, e.g. ``aria-expanded``."""
        return ClientOp("toggle_attr", (target, name, on, off))

    @staticmethod
    def confirm(message: str) -> ClientOp:
        """Ask the user first; if they decline, the rest of the operations and the server event are skipped."""
        return ClientOp("confirm", (None, message))

    @staticmethod
    def focus(target: str) -> ClientOp:
        return ClientOp("focus", (target,))

    @staticmethod
    def set_theme(mode: ThemeMode) -> ClientOp:
        return ClientOp("set_theme", (None, mode))

    @staticmethod
    def toggle_theme() -> ClientOp:
        return ClientOp("toggle_theme", (None,))

    @staticmethod
    def show(target: str | None = None) -> ClientOp:
        """Un-hide the target (removes the ``hidden`` attribute)."""
        return ClientOp("show", (target,))

    @staticmethod
    def hide(target: str | None = None) -> ClientOp:
        return ClientOp("hide", (target,))

    @staticmethod
    def toggle(target: str | None = None) -> ClientOp:
        """Show the target if hidden, hide it otherwise."""
        return ClientOp("toggle", (target,))

    @staticmethod
    def remove(target: str | None = None) -> ClientOp:
        """Take the element out of the page (until the server next re-renders it)."""
        return ClientOp("remove", (target,))

    @staticmethod
    def set_text(text: str, target: str | None = None) -> ClientOp:
        return ClientOp("set_text", (target, text))

    @staticmethod
    def set_value(value: str, target: str | None = None) -> ClientOp:
        """Set a form control's value (``""`` clears it)."""
        return ClientOp("set_value", (target, value))

    @staticmethod
    def copy(text: str | None = None, target: str | None = None) -> ClientOp:
        """Copy ``text`` (or, if omitted, the target's text) to the clipboard."""
        return ClientOp("copy", (target, text))

    @staticmethod
    def scroll_to(target: str) -> ClientOp:
        return ClientOp("scroll_to", (target,))

    @staticmethod
    def open_dialog(target: str) -> ClientOp:
        """Open a ``<dialog>`` as a modal."""
        return ClientOp("open_dialog", (target,))

    @staticmethod
    def close_dialog(target: str | None = "closest:dialog") -> ClientOp:
        return ClientOp("close_dialog", (target,))
