"""Render-time context shared by state descriptors, components and primitives."""

from __future__ import annotations

import itertools
import re
from contextvars import ContextVar
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .component import Component
    from .runtime import PageRuntime

Cell = tuple[Any, ...]

_SLUG_RE = re.compile(r"[^a-zA-Z0-9]+")
_fallback_ids = itertools.count(1)


@dataclass(eq=False)
class Frame:
    """The component currently being rendered."""

    runtime: PageRuntime
    component: Component
    handler_seq: int = 0
    id_seq: int = 0

    def next_dom_id(self, hint: str = "el") -> str:
        """A DOM id that is unique on the page and stable across rerenders."""
        self.id_seq += 1
        return f"{self.component.cid}-{dom_slug(hint)}-{self.id_seq}"


def dom_slug(hint: str) -> str:
    """The readable part of a generated DOM id (client components build ids the same way)."""
    return _SLUG_RE.sub("-", hint).strip("-").lower()[:24] or "el"


current_frame: ContextVar[Frame | None] = ContextVar("rational_frame", default=None)


def track_read(cell: Cell) -> None:
    frame = current_frame.get()
    if frame is not None:
        frame.runtime.track(frame.component.cid, cell)


def dom_id(hint: str = "el") -> str:
    frame = current_frame.get()
    if frame is None:
        return f"rw-{hint}-{next(_fallback_ids)}"
    return frame.next_dom_id(hint)
