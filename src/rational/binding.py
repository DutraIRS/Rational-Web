"""Turn an untrusted event payload into validated handler arguments.

A handler takes zero or one argument; its annotation decides the validation:
``Event`` (raw event), a Pydantic model (form), any other type (the value),
or no annotation (the raw value).
"""

from __future__ import annotations

import functools
import inspect
import typing
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, TypeAdapter, ValidationError

from .errors import InvalidInput
from .events import Event


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


def check_signature(handler: Callable[..., Any]) -> None:
    if len(_required_positional(handler)) > 1:
        raise TypeError(f"event handler {handler!r} must take at most one argument (the value/form/event)")


def bind_payload(handler: Callable[..., Any], event: str, payload: dict[str, Any]) -> list[Any]:
    params = _required_positional(handler)
    if not params:
        return []
    annotation = _annotation(getattr(handler, "__func__", handler), params[0].name)
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


def _required_positional(handler: Callable[..., Any]) -> list[inspect.Parameter]:
    try:
        sig = inspect.signature(handler)
    except (TypeError, ValueError):
        return []
    return [
        p
        for p in sig.parameters.values()
        if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD) and p.default is p.empty
    ]


_hints_by_code: dict[Any, dict[str, Any]] = {}


def _annotation(func: Callable[..., Any], name: str) -> Any:
    # Keyed by code object: lambdas recreated on every render share their hints.
    code = getattr(func, "__code__", None)
    hints = _hints_by_code.get(code) if code is not None else None
    if hints is None:
        try:
            hints = typing.get_type_hints(func)
        except Exception:
            hints = {}
        if code is not None:
            _hints_by_code[code] = hints
    return hints.get(name, Any)


@functools.lru_cache(maxsize=1024)
def _adapter(annotation: Any) -> TypeAdapter[Any]:
    return TypeAdapter(annotation)
