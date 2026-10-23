"""Loading states: ``Suspense`` (deferred content) and ``Skeleton`` (a placeholder block)."""

from __future__ import annotations

import inspect
import logging
from collections.abc import Callable
from typing import Any

from ..component import Component
from ..rendering import h
from ..state import State
from ..styling import Style
from ..styling.style import merge
from .basic import Text

log = logging.getLogger("rational")


def Skeleton(*, width: str = "100%", height: str = "1em", style: Style | None = None) -> Any:
    """A shimmering placeholder block; give it the size of the thing it stands in for."""
    return h(
        "div",
        class_="rw-skeleton",
        aria_hidden="true",
        style=merge(Style(width=width, height=height), style),
    )


class Suspense(Component):
    """Send the page now with ``fallback``, then push the real content when ``load`` finishes.

        Suspense(load=self.load_report, fallback=Skeleton(height="12rem"))

    ``load`` is an async (or sync) callable returning anything a component may render. It runs as a
    background task, so the page responds immediately and the content arrives over the push stream.
    If it raises, ``error`` is shown (default: a short message) and the exception is logged. Without
    JavaScript, visitors see only the fallback.
    """

    load: Callable[[], Any]
    fallback: Any = None
    error: Any = None

    phase = State("loading")
    content = State(None)

    def mount(self) -> None:
        self.run_task(self._fetch)

    async def _fetch(self) -> None:
        try:
            value = self.load()
            if inspect.isawaitable(value):
                value = await value
        except Exception:
            log.exception("Suspense: load failed")
            self.phase = "failed"
            raise
        self.content = value
        self.phase = "ready"

    def render(self) -> Any:
        if self.phase == "ready":
            return h("div", self.content, data_rw_suspense="ready")
        if self.phase == "failed":
            return h("div", self.error or Text("Could not load this section."), role="alert", data_rw_suspense="failed")
        return h("div", self.fallback, aria_busy="true", data_rw_suspense="loading")
