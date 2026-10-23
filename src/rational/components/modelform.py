"""``ModelForm``: a form generated from a Pydantic model."""

from __future__ import annotations

import enum
import types
from collections.abc import Mapping
from typing import Any, Literal, Union, get_args, get_origin

from pydantic import BaseModel
from pydantic.fields import FieldInfo

from ..rendering.builder import EventValue
from ..rendering.nodes import Node
from ..styling.style import Style
from .basic import Button
from .forms import Checkbox, Form, Input, Select, Textarea

LONG_TEXT = 200  # a max_length above this gets a textarea


def _unwrap(annotation: Any) -> Any:
    """``X | None`` and ``Optional[X]`` become ``X``."""
    if get_origin(annotation) in (Union, types.UnionType):
        args = [a for a in get_args(annotation) if a is not type(None)]
        if len(args) == 1:
            return args[0]
    return annotation


def _constraint(info: FieldInfo, *names: str) -> Any:
    for item in info.metadata:
        for name in names:
            value = getattr(item, name, None)
            if value is not None:
                return value
    return None


def _label(name: str, info: FieldInfo) -> str:
    return info.title or name.replace("_", " ").strip().capitalize()


def _options(annotation: Any) -> list[tuple[str, str]] | None:
    if isinstance(annotation, type) and issubclass(annotation, enum.Enum):
        if all(isinstance(m.value, str) for m in annotation):
            return [(m.value, m.name.replace("_", " ").capitalize()) for m in annotation]
        return None
    if get_origin(annotation) is Literal:
        values = get_args(annotation)
        if values and all(isinstance(v, str) for v in values):
            return [(v, v) for v in values]
    return None


def _initial(values: Mapping[str, Any] | BaseModel | None, name: str, info: FieldInfo) -> Any:
    if isinstance(values, BaseModel):
        value = getattr(values, name, None)
    elif values is not None and name in values:
        value = values[name]
    elif info.is_required() or info.default is None or callable(info.default_factory):
        return None
    else:
        value = info.default
    return value.value if isinstance(value, enum.Enum) else value


def _control(
    name: str,
    info: FieldInfo,
    value: Any,
    error: str | None,
    disabled: bool,
) -> Node:
    annotation = _unwrap(info.annotation)
    label = _label(name, info)
    required = info.is_required()
    common: dict[str, Any] = {"name": name, "help": info.description, "error": error}

    if annotation is bool:
        return Checkbox(label, name=name, checked=bool(value), disabled=disabled)
    options = _options(annotation)
    if options is not None:
        if not required:
            options = [("", "")] + options
        return Select(label, options, value=value, required=required, **common)
    max_length = _constraint(info, "max_length")
    extra = info.json_schema_extra
    widget = extra.get("widget") if isinstance(extra, dict) else None
    if annotation is str and (widget == "textarea" or (max_length and max_length > LONG_TEXT)):
        return Textarea(label, value=value, required=required, maxlength=max_length, **common)
    attrs: dict[str, Any] = {"disabled": disabled}
    lowered = name.lower()
    if annotation in (int, float):
        input_type = "number"
        attrs["min"] = _constraint(info, "ge", "gt")
        attrs["max"] = _constraint(info, "le", "lt")
        if annotation is float:
            attrs["step"] = "any"
    elif widget in ("password", "email", "url", "tel", "date", "time", "search"):
        input_type = str(widget)
    elif "password" in lowered:
        input_type, attrs["autocomplete"] = "password", "current-password"
    elif "email" in lowered:
        input_type, attrs["autocomplete"] = "email", "email"
    else:
        input_type = "text"
    if annotation is str:
        attrs["minlength"] = _constraint(info, "min_length")
        attrs["maxlength"] = max_length
    if input_type == "password":
        value = None  # never echo a password back into the page
    return Input(label, value=value, type=input_type, required=required, **common, **attrs)


def ModelForm(  # noqa: N802
    model: type[BaseModel],
    *,
    on_submit: EventValue = None,
    values: Mapping[str, Any] | BaseModel | None = None,
    errors: Mapping[str, str] | None = None,
    submit_label: str = "Submit",
    exclude: tuple[str, ...] = (),
    disabled: bool = False,
    style: Style | None = None,
    key: str | int | None = None,
    **attrs: Any,
) -> Node:
    """A form with one labelled control per field of a Pydantic ``model``.

    Control choice follows the annotation: ``str`` is a text input (a textarea for
    ``json_schema_extra={"widget": "textarea"}`` or a large ``max_length``), ``int`` and
    ``float`` are number inputs, ``bool`` a checkbox, and ``Literal[...]``/``Enum`` of
    strings a select. ``Field(title=, description=)`` give the label and help text, and
    ``min_length``/``max_length``/``ge``/``le`` become the matching HTML attributes. Fields named
    ``*password*`` and ``*email*`` get the right input type. Annotate the handler's parameter with the
    same model and a failed validation is shown under the right field automatically.
    """
    errors = errors or {}
    controls = [
        _control(name, info, _initial(values, name, info), errors.get(name), disabled)
        for name, info in model.model_fields.items()
        if name not in exclude and not info.exclude
    ]
    return Form(
        *controls,
        Button(submit_label, type="submit", disabled=disabled),
        on_submit=on_submit,
        style=style,
        key=key,
        **attrs,
    )
