"""One client component class: its state, methods and getters, compiled into one JavaScript module."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from types import FunctionType
from typing import TYPE_CHECKING, Any, cast

from ...component import Component
from ...state import MISSING, State, computed
from ...styling.style import Style
from ..templates import has_placeholder
from .base import ClientCompileError, ClientModule, json_value, module_key
from .function import FunctionCompiler

if TYPE_CHECKING:
    from ...styling.compiler import StyleCompiler


def compile_component(
    cls: type[Component], styles: StyleCompiler, modules: Callable[[type[Component]], ClientModule | None]
) -> ClientModule:
    """Compile ``cls``. ``modules`` returns the module of another client component (``None`` while it is
    itself being compiled), so a parent can check that the children it creates in the browser can mount."""
    return ModuleCompiler(cls, styles, modules).build()


class ModuleCompiler:
    """One client component class and everything its compiled code needs."""

    def __init__(
        self,
        cls: type[Component],
        styles: StyleCompiler,
        modules: Callable[[type[Component]], ClientModule | None],
    ) -> None:
        self.cls = cls
        self.key = module_key(cls)
        self.style_compiler = styles
        self.modules = modules
        self.props = list(cls._rw_props)
        self.states = self._states()
        self.methods = self._methods()
        self.computed = {
            name: value.fn
            for klass in reversed(cls.__mro__)
            for name, value in vars(klass).items()
            if isinstance(value, computed)
        }
        self.computed_names: dict[str, str] = {}
        self.functions: dict[str, str] = {}  # js name -> source, in first-use order
        self.method_names: dict[str, str] = {}
        self.helper_names: dict[FunctionType, str] = {}
        self.styles: dict[str, Style] = {}
        self.children: dict[type, None] = {}  # ordered set

    def _states(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for klass in reversed(self.cls.__mro__):
            for name, value in vars(klass).items():
                if isinstance(value, State):
                    if value.query is not None:
                        raise ClientCompileError(
                            f"{self.cls.__name__}.{name}: State(query=...) works in server components; "
                            "keep the search state in the server component around this one"
                        )
                    initial = value.default if value.factory is None else value.factory()
                    if initial is MISSING or not json_value(initial):
                        raise ClientCompileError(
                            f"{self.cls.__name__}.{name}: client component state must start as JSON data "
                            f"(numbers, strings, booleans, None, lists and dicts), not {initial!r}"
                        )
                    out[name] = initial
        return out

    def _methods(self) -> dict[str, FunctionType]:
        from ..component import ClientComponent

        out: dict[str, FunctionType] = {}
        for klass in reversed(self.cls.__mro__):
            if not (isinstance(klass, type) and issubclass(klass, ClientComponent)) or klass is ClientComponent:
                continue
            for name, value in vars(klass).items():
                if isinstance(value, FunctionType) and not name.startswith("__"):
                    out[name] = value
        return out

    # -- functions --------------------------------------------------------------------------------

    def method(self, name: str) -> str:
        """The JavaScript name of method ``name``, compiling it on first use."""
        js = self.method_names.get(name)
        if js is None:
            fn = self.methods.get(name)
            if fn is None:
                raise ClientCompileError(f"{self.cls.__name__} has no method {name}()")
            js = self.method_names[name] = f"$m_{name}"
            try:
                self.functions[js] = FunctionCompiler(self, fn, js, method=True).compile()
            except BaseException:
                del self.method_names[name]
                raise
        return js

    def getter(self, name: str) -> str:
        """The JavaScript name of ``@computed`` ``name`` (recomputed on each read in the browser)."""
        js = self.computed_names.get(name)
        if js is None:
            js = self.computed_names[name] = f"$g_{name}"
            try:
                getter = cast(FunctionType, self.computed[name])
                self.functions[js] = FunctionCompiler(self, getter, js, method=True).compile()
            except BaseException:
                del self.computed_names[name]
                raise
        return js

    def helper(self, fn: FunctionType) -> str:
        """A module-level function called from client code, compiled to JavaScript too."""
        js = self.helper_names.get(fn)
        if js is None:
            js = self.helper_names[fn] = f"$f{len(self.helper_names)}_{fn.__name__}"
            try:
                self.functions[js] = FunctionCompiler(self, fn, js, method=False).compile()
            except BaseException:
                del self.helper_names[fn]
                raise
        return js

    def style_class(self, style: Style) -> str:
        compiled = self.style_compiler.compile(style)
        if any(has_placeholder(rule) for rule in compiled.rules) or has_placeholder(compiled.class_name):
            raise ClientCompileError("a style depends on a value only known in the browser; styles must be constant")
        self.styles.setdefault(compiled.class_name, style)
        return compiled.class_name

    def build(self) -> ClientModule:
        if "render" not in self.methods:
            raise ClientCompileError(f"{self.cls.__name__} has no render() method")
        render = self.method("render")
        mount, mount_error = "null", None
        if "mount" in self.methods:
            try:
                mount = self.method("mount")
            except ClientCompileError as e:
                mount_error = str(e)
        hydrated = self.method("hydrated") if "hydrated" in self.methods else "null"
        watchers = getattr(self.cls, "_rw_watchers", {})
        watch = ", ".join(
            f"{json.dumps(name)}: [{', '.join(self.method(m) for m in methods)}]" for name, methods in watchers.items()
        )
        definition = (
            f"{{props: {json.dumps(self.props)}, init: () => ({json.dumps(self.states)}), "
            f"render: {render}, mount: {mount}, hydrated: {hydrated}, watch: {{{watch}}}}}"
        )
        body = "\n".join(self.functions.values())
        js = f'"use strict";\nrational.island({json.dumps(self.key)}, ($rt) => {{\n{body}\nreturn {definition};\n}});\n'
        if has_placeholder(js) or "\\ue000" in js or "\\ue001" in js:  # raw, or escaped by json.dumps
            raise ClientCompileError(f"{self.cls.__name__}: a value only known in the browser was mangled")
        digest = hashlib.sha256(js.encode()).hexdigest()[:12]
        return ClientModule(self.key, js, tuple(self.styles.values()), digest, mount_error, tuple(self.children))
