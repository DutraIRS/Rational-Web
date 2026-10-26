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
    """A handler takes at most one *required* positional parameter (the payload).

    Defaulted positional parameters are the documented idiom for capturing values in
    lambdas (``lambda i=i: ...``), so they are not counted; ``*args`` is rejected.
    """
    try:
        sig = inspect.signature(handler)
    except (TypeError, ValueError):
        return
    for p in sig.parameters.values():
        if p.kind is p.VAR_POSITIONAL:
            raise TypeError(f"event handler {handler!r} must not take *args")
    required = [
        p
        for p in sig.parameters.values()
        if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD) and p.default is p.empty
    ]
    if len(required) > 1:
        raise TypeError(f"event handler {handler!r} must take at most one argument (the value/form/event)")


def _payload_param(handler: Callable[..., Any]) -> inspect.Parameter | None:
    """The required positional parameter that receives the payload, if there is one."""
    try:
        sig = inspect.signature(handler)
    except (TypeError, ValueError):
        return None
    for p in sig.parameters.values():
        if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD) and p.default is p.empty:
            return p
    return None


def bind_payload(handler: Callable[..., Any], event: str, payload: dict[str, Any]) -> list[Any]:
    param = _payload_param(handler)
    if param is None:
        return []
    annotation = _annotation(getattr(handler, "__func__", handler), param.name)
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
