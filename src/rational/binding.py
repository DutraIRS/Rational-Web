"""Turn an untrusted event payload into validated handler arguments.

A handler takes zero or one argument; its annotation decides the validation:
``Event`` (raw event), a Pydantic model (form), any other type (the value),
or no annotation (the raw value).
"""

from __future__ import annotations

import functools
import inspect
import logging
import typing
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, TypeAdapter, ValidationError

from .errors import InvalidInput
from .events import Event

log = logging.getLogger("rational")


class EventValidationError(InvalidInput):
    def __init__(self, exc: ValidationError) -> None:
        details = [
            {"field": ".".join(str(p) for p in err["loc"]), "message": _message(err)}
            for err in exc.errors(include_url=False)
        ]
        super().__init__("Please correct the highlighted fields", details=details)


def _message(err: Any) -> str:
    # Messages raised in custom validators come prefixed with "Value error, "; users don't need that.
    if err.get("type") == "value_error" and "error" in err.get("ctx", {}):
        return str(err["ctx"]["error"])
    return str(err["msg"])


@dataclass(frozen=True)
class _Shape:
    """What binding needs to know about a handler: inspecting one on every render would be slow."""

    problem: str | None = None  # why it cannot be a handler
    takes_payload: bool = False
    annotation: Any = Any


_shapes: dict[tuple[Any, ...], _Shape] = {}


def _shape(handler: Callable[..., Any]) -> _Shape:
    func = getattr(handler, "__func__", handler)
    code = getattr(func, "__code__", None)
    if code is None:
        return _inspect(handler, func)
    # By code object: lambdas recreated on every render share a shape. A decorator's wrappers all
    # have one code object too, so what they wrap counts as well.
    key = (code, getattr(inspect.unwrap(func), "__code__", None), func is not handler)
    shape = _shapes.get(key)
    if shape is None:
        shape = _shapes[key] = _inspect(handler, func)
    return shape


def _inspect(handler: Callable[..., Any], func: Callable[..., Any]) -> _Shape:
    """Defaulted positional parameters are the documented idiom for capturing values in lambdas
    (``lambda i=i: ...``), so only a required one receives the payload."""
    try:
        parameters = inspect.signature(handler).parameters.values()
    except (TypeError, ValueError):
        return _Shape()
    if any(p.kind is p.VAR_POSITIONAL for p in parameters):
        return _Shape("must not take *args")
    required = [
        p for p in parameters if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD) and p.default is p.empty
    ]
    if len(required) > 1:
        return _Shape("must take at most one argument (the value/form/event)")
    if not required:
        return _Shape()
    return _Shape(takes_payload=True, annotation=_annotation(func, required[0].name))


def _annotation(func: Callable[..., Any], name: str) -> Any:
    try:
        return typing.get_type_hints(func).get(name, Any)
    except NameError as e:  # an annotation that only exists for type checkers, or a local class
        log.warning("%r takes unvalidated input: its annotations cannot be resolved (%s)", func, e)
    except Exception:  # no annotations to read: a callable object, say
        pass
    return Any


def check_signature(handler: Callable[..., Any]) -> None:
    """A handler takes at most one *required* positional parameter (the payload), and no ``*args``."""
    problem = _shape(handler).problem
    if problem is not None:
        raise TypeError(f"event handler {handler!r} {problem}")


def bind_payload(handler: Callable[..., Any], event: str, payload: dict[str, Any]) -> list[Any]:
    shape = _shape(handler)
    if not shape.takes_payload:
        return []
    annotation = shape.annotation
    if annotation is Event:
        return [
            Event(name=event, value=payload.get("value"), key=payload.get("key"), form=dict(payload.get("form") or {}))
        ]
    raw = payload.get("form") if event == "submit" else payload.get("value")
    if annotation is Any:
        return [raw]
    if raw is None and isinstance(annotation, type) and issubclass(annotation, BaseModel):
        raw = {}
    try:
        return [_adapter(annotation).validate_python(raw)]
    except ValidationError as exc:
        raise EventValidationError(exc) from None


@functools.lru_cache(maxsize=1024)
def _adapter(annotation: Any) -> TypeAdapter[Any]:
    return TypeAdapter(annotation)
