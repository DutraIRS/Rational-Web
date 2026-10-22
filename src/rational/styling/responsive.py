"""Named viewport breakpoints and container sizes.

Names are conventions, not device detection: the browser evaluates the
generated media/container queries; Python never inspects the viewport.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Breakpoint:
    min: int | None = None
    max: int | None = None

    def condition(self) -> str:
        parts = []
        if self.min is not None:
            parts.append(f"(min-width: {self.min}px)")
        if self.max is not None:
            parts.append(f"(max-width: {self.max - 0.02:g}px)")
        if not parts:
            raise ValueError("a breakpoint needs min and/or max")
        return " and ".join(parts)

    def sort_key(self) -> tuple[int, int]:
        # Later rules win, so the most specific condition is emitted last:
        # max-only queries widest first, then bounded ranges, then min-only ascending.
        if self.min is None:
            return (0, -(self.max or 0))
        if self.max is not None:
            return (1, self.min)
        return (2, self.min)


DEFAULT_BREAKPOINTS: Mapping[str, Breakpoint] = {
    "mobile": Breakpoint(max=640),
    "tablet": Breakpoint(min=640, max=1024),
    "narrow": Breakpoint(max=1024),
    "desktop": Breakpoint(min=1024),
    "sm": Breakpoint(min=640),
    "md": Breakpoint(min=768),
    "lg": Breakpoint(min=1024),
    "xl": Breakpoint(min=1280),
}

DEFAULT_CONTAINERS: Mapping[str, Breakpoint] = {
    "compact": Breakpoint(max=480),
    "regular": Breakpoint(min=480),
    "wide": Breakpoint(min=900),
}
