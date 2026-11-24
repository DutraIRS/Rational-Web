"""The compiler's output and errors, and the small helpers every part uses."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any

from ...styling.style import Style
from .tables import RESERVED


class ClientCompileError(TypeError):
    """Code in a client component that cannot run in the browser. The message says where and why."""


@dataclass(frozen=True)
class ClientModule:
    """The compiled JavaScript of one client component class."""

    key: str
    js: str
    styles: tuple[Style, ...]
    digest: str
    mount_error: str | None = None  # why mount() cannot run in the browser, if it cannot
    children: tuple[type, ...] = ()  # client components this one creates in the browser (their scripts are needed)

    @property
    def path(self) -> str:
        return f"/_rational/c/{self.digest}.js"


def module_key(cls: type) -> str:
    return f"{cls.__module__}.{cls.__qualname__}"


def js_name(name: str) -> str:
    return name + "$" if name in RESERVED else name


def number(value: float) -> str:
    if math.isnan(value):
        return "NaN"
    if math.isinf(value):
        return "Infinity" if value > 0 else "-Infinity"
    return repr(value)


def json_value(value: Any) -> bool:
    try:
        return bool(json.loads(json.dumps(value)) == value)
    except (TypeError, ValueError):
        return False
