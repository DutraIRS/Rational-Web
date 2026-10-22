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
