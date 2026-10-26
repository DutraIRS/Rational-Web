"""Event payloads and declarative browser-local operations.

Python never runs in the browser. ``js.*`` builds a small, closed set of
operations that the runtime executes locally, with no server round trip.
Targets are CSS selectors; ``None`` means the element itself and
``"closest:<selector>"`` searches its ancestors.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from .rendering.nodes import validate_attr
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
    def optimistic(*ops: ClientOp) -> ClientOp:
        """Apply ``ops`` at once and keep them until the server's patches arrive.

        If the event fails (or the network does) and the server did not re-render the surrounding
        component, the component is restored to how it looked before. Put it before the server handler:
        ``on_click=[js.optimistic(js.set_text("Saved")), self.save]``.
        """
        if not ops:
            raise ValueError("js.optimistic needs at least one operation")
        if any(op.op in ("confirm", "optimistic", "set_locale") for op in ops):
            raise ValueError("js.optimistic cannot wrap confirm, set_locale or another optimistic")
        return ClientOp("optimistic", (None, json.dumps([op.to_json() for op in ops], separators=(",", ":"))))

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
        """Set an attribute. The renderer's rules apply: no ``on*``/``srcdoc``, no ``javascript:`` URLs."""
        validate_attr(name, value)
        return ClientOp("set_attr", (target, name, value))

    @staticmethod
    def toggle_attr(name: str, on: str = "true", off: str = "false", target: str | None = None) -> ClientOp:
        """Flip ``name`` between two values, e.g. ``aria-expanded``."""
        validate_attr(name, on)
        validate_attr(name, off)
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
        if mode not in ("light", "dark", "system"):
            raise ValueError(f"unknown theme mode {mode!r}; use 'light', 'dark' or 'system'")
        return ClientOp("set_theme", (None, mode))

    @staticmethod
    def set_locale(tag: str) -> ClientOp:
        """Remember the language in a cookie and reload so the server renders it."""
        return ClientOp("set_locale", (None, tag))

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
