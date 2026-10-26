"""Tracing the primitives (``h()``, ``Text``, ``Button``...) that client components call.

The compiler does not translate the primitives, and does not need to: they are plain Python functions
that build node trees. At compile time each call is *run* with stand-ins for what only the browser will
know: a ``Hole`` for a value, a ``HandlerRef`` for an event handler. The resulting tree is emitted as
JavaScript that rebuilds it with the real values.

Order matters, because generated DOM ids are numbered in the order they are created and the browser
must number them exactly as the server did. So every argument that only the browser knows is evaluated
into a temporary first, in Python's evaluation order, and every DOM id the primitive creates is
allocated in the same sequence (``TraceFrame.steps``).

A primitive that *inspects* a browser value (``if variant == "primary"``) cannot be traced with a hole.
When the value is a choice between constants (``"primary" if self.on else "ghost"``), the call is traced
once per choice instead; otherwise the compiler reports which argument must be constant.

Text is the one thing a primitive may build from a browser value: ``str(hole)``, ``f"{hole}"`` and DOM
ids become placeholder characters that survive concatenation and are turned back into JavaScript when
the tree is emitted. A placeholder that reaches a style, or gets mangled, is reported as an error.
"""

from __future__ import annotations

import contextlib
import contextvars
import json
import re
from collections.abc import Callable, Iterator
from typing import Any, cast

from .._tracking import Frame, current_frame, dom_slug

OPEN, CLOSE = "", ""
TOKEN = re.compile(f"{OPEN}(\\d+){CLOSE}")


class HoleError(AttributeError):
    """A traced primitive inspected a value that only exists in the browser."""

    def __init__(self, hole: Hole) -> None:
        super().__init__(f"{hole.label} is only known in the browser")
        self.hole = hole


class Hole:
    """A browser-side value passed through a primitive. Any inspection raises ``HoleError``."""

    __slots__ = ("js", "label")

    def __init__(self, js: str, label: str) -> None:
        self.js = js
        self.label = label

    def __repr__(self) -> str:
        return f"<browser value {self.label}>"

    # Comparing is allowed and stays symbolic (``selected=option == value``); using the result is not.
    def __eq__(self, other: object) -> Hole:  # type: ignore[override]
        return Hole(f"$rt.eq({self.js}, {_operand(other, self)})", self.label)

    def __ne__(self, other: object) -> Hole:  # type: ignore[override]
        return Hole(f"!$rt.eq({self.js}, {_operand(other, self)})", self.label)

    def __str__(self) -> str:
        return placeholder(f"$rt.str({self.js})")

    def __format__(self, spec: str) -> str:
        return placeholder(f"$rt.fmt({self.js}, {json.dumps(spec)})" if spec else f"$rt.str({self.js})")

    def __getattr__(self, name: str) -> Any:
        if name.startswith("__"):
            raise AttributeError(name)
        raise HoleError(self)

    def _refuse(self, *_: Any) -> Any:
        raise HoleError(self)

    __bool__ = __hash__ = __iter__ = __len__ = __contains__ = __getitem__ = (
        _refuse  # not __call__: children call callables
    )
    __lt__ = __le__ = __gt__ = __ge__ = _refuse
    __add__ = __radd__ = __sub__ = __rsub__ = __mul__ = __rmul__ = __truediv__ = __rtruediv__ = _refuse
    __floordiv__ = __rfloordiv__ = __mod__ = __rmod__ = __pow__ = __rpow__ = __neg__ = __pos__ = _refuse
    __or__ = __ror__ = __and__ = __rand__ = __xor__ = __rxor__ = __invert__ = _refuse
    __int__ = __float__ = __index__ = __round__ = __abs__ = _refuse


def _operand(value: object, hole: Hole) -> str:
    if isinstance(value, Hole):
        return value.js
    try:
        return json.dumps(value)
    except TypeError:
        raise HoleError(hole) from None


class HandlerRef:
    """An event handler that runs in the browser. Primitives only pass it on to ``h(on_...=)``."""

    __slots__ = ("js",)

    def __init__(self, js: str) -> None:
        self.js = js

    def __call__(self, *_: Any, **__: Any) -> Any:
        raise TypeError("an event handler of a client component was called while building the page")

    def __repr__(self) -> str:
        return "<browser handler>"


class _Stub:
    cid = None

    def track(self, *_: Any) -> None:
        return None


class TraceFrame(Frame):
    """Stands in for the render frame while one primitive call is compiled.

    ``steps`` are JavaScript assignments, in evaluation order: browser values into temporaries and DOM
    ids into variables. ``temp`` allocates a fresh variable name in the enclosing JavaScript function.
    """

    def __init__(self, temp: Callable[[str], str]) -> None:
        super().__init__(runtime=cast(Any, _Stub()), component=cast(Any, _Stub()))
        self.temp = temp
        self.steps: list[str] = []
        self.placeholders: list[str] = []

    def hole(self, js: str, label: str) -> Hole:
        """A browser value, evaluated once, now (in Python's argument order)."""
        name = self.temp("h")
        self.steps.append(f"{name} = {js}")
        return Hole(name, label)

    def next_dom_id(self, hint: str = "el") -> str:
        name = self.temp("d")
        self.steps.append(f"{name} = $rt.id($c, {json.dumps(dom_slug(hint))})")
        return self.add(name)

    def add(self, js: str) -> str:
        self.placeholders.append(js)
        return f"{OPEN}{len(self.placeholders) - 1}{CLOSE}"


_tracing: contextvars.ContextVar[TraceFrame | None] = contextvars.ContextVar("rational_tracing", default=None)


def placeholder(js: str) -> str:
    frame = _tracing.get()
    if frame is None:
        raise TypeError("a browser value was converted to text outside a client component template")
    return frame.add(js)


@contextlib.contextmanager
def tracing(frame: TraceFrame) -> Iterator[TraceFrame]:
    """Make ``frame`` the render frame while primitives run (DOM ids and text placeholders go to it)."""
    token = current_frame.set(frame)
    inner = _tracing.set(frame)
    try:
        yield frame
    finally:
        _tracing.reset(inner)
        current_frame.reset(token)


def has_placeholder(text: str) -> bool:
    return OPEN in text or CLOSE in text


def string_js(text: str, frame: TraceFrame | None) -> str:
    """A JavaScript string expression for ``text``, with placeholders replaced by what they stand for."""
    if not has_placeholder(text):
        return json.dumps(text)
    if frame is None:
        raise ValueError("a browser value was used outside the element that received it")
    parts: list[str] = []
    last = 0

    def literal(piece: str) -> None:
        if has_placeholder(piece):  # a marker without its partner: the primitive cut or rearranged the text
            raise ValueError("a browser value was mangled while building the element")
        parts.append(json.dumps(piece))

    for match in TOKEN.finditer(text):
        if match.start() > last:
            literal(text[last : match.start()])
        parts.append(frame.placeholders[int(match.group(1))])
        last = match.end()
    if last < len(text):
        literal(text[last:])
    return "(" + " + ".join(["''", *parts] if len(parts) == 1 else parts) + ")"
