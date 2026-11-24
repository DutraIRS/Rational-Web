"""Calls: builtins, methods of str, list and dict, the component's own methods, ``self.remote()``,
module-level helpers, and client components created in the browser."""

from __future__ import annotations

import ast
import asyncio
import builtins
import inspect
import json

from ...component import Component
from ...events import ClientOp
from .base import js_name, module_key
from .core import FunctionCore
from .tables import BUILTINS, FUNCTIONS, METHODS, SERVER_ONLY, TYPES, VARARGS, is_template_function, is_user_function


class Calls(FunctionCore):
    def call(self, node: ast.Call) -> str:
        func = node.func
        if isinstance(func, ast.Attribute):
            if self.is_self(func.value):
                return self.self_call(func.attr, node)
            if not self.is_static(func.value) or (
                func.attr in METHODS and isinstance(self.evaluate(func.value), (str, list, tuple, dict))
            ):
                return self.method_call(func, node)  # of a local value, or of constant data: ", ".join(names)
        elif isinstance(func, ast.Name) and self.is_local(func.id):
            return f"$rt.callable({js_name(func.id)})({', '.join(self.positional(node))})"
        return self.known_call(node)

    def known_call(self, node: ast.Call) -> str:
        """A call of something the compiler can look up now: a builtin, a known function, a component..."""
        func = node.func
        target = self.lookup(func)
        if target is None and isinstance(func, ast.Name) and func.id not in self.namespace:
            raise self.error(node, f"name {func.id!r} is not defined")
        if isinstance(func, ast.Name) and target is getattr(builtins, func.id, None) and func.id not in self.namespace:
            return self.builtin(func.id, node)
        if target in FUNCTIONS:
            js, params = FUNCTIONS[target]
            args = self.arguments(node, params)
            return f"$rt.sleep($c, {args})" if target is asyncio.sleep else f"{js}({args})"
        if isinstance(target, type) and issubclass(target, Component):
            return self.island(target, node)
        if is_template_function(target):
            return self.template(node, target)
        if is_user_function(target):
            name = self.module.helper(target)
            return f"{name}($c, {self.arguments(node, tuple(inspect.signature(target).parameters))})"
        if self.is_static(node):
            return self.static(node)
        raise self.error(node, f"{ast.unparse(func)}() cannot be called in client code")

    def positional(self, node: ast.Call) -> list[str]:
        if node.keywords:
            raise self.error(node, "keyword arguments need a function whose signature the compiler knows")
        return [self.element(a) for a in node.args]

    def arguments(self, node: ast.Call, params: tuple[str, ...]) -> str:
        """Positional and keyword arguments mapped onto ``params``' positions, as a JavaScript argument list."""
        return ", ".join(self.argument_values(node, params))

    def argument_values(self, node: ast.Call, params: tuple[str, ...]) -> list[str]:
        """One JavaScript expression per parameter (``undefined`` where nothing was passed), trailing gaps dropped."""
        if any(isinstance(a, ast.Starred) for a in node.args):
            raise self.error(node, "*arguments are not supported in this call")
        if len(node.args) > len(params):
            raise self.error(node, f"too many arguments (at most {len(params)})")
        values = [self.expr(a) for a in node.args] + ["undefined"] * (len(params) - len(node.args))
        for kw in node.keywords:
            if kw.arg is None or kw.arg not in params:
                raise self.error(kw, f"unexpected keyword argument {kw.arg!r}")
            index = params.index(kw.arg)
            if index < len(node.args):
                raise self.error(kw, f"{kw.arg} given twice")
            values[index] = self.expr(kw.value)
        while values and values[-1] == "undefined":
            values.pop()
        return values

    def builtin(self, name: str, node: ast.Call) -> str:
        if name in BUILTINS:
            js, params = BUILTINS[name]
            return f"{js}({self.arguments(node, params)})"
        if name in VARARGS:
            if node.keywords:
                raise self.error(node, f"{name}() keyword arguments are not supported in client code")
            return f"{VARARGS[name]}({', '.join(self.element(a) for a in node.args)})"
        if name in ("min", "max"):
            options = {kw.arg: self.expr(kw.value) for kw in node.keywords if kw.arg in ("key", "default")}
            if len(options) != len(node.keywords):
                raise self.error(node, f"{name}() takes key= and default= keywords")
            items = (
                self.expr(node.args[0])
                if len(node.args) == 1
                else "[" + ", ".join(self.expr(a) for a in node.args) + "]"
            )
            opts = "{" + ", ".join(f"{k}: {v}" for k, v in options.items()) + "}"
            return f"$rt.{name}({items}, {opts})"
        if name == "dict":
            parts = [f"...$rt.dict({self.expr(a)})" for a in node.args]
            parts += [f"{json.dumps(kw.arg)}: {self.expr(kw.value)}" for kw in node.keywords if kw.arg]
            return "{" + ", ".join(parts) + "}"
        if name == "isinstance":
            if len(node.args) != 2:
                raise self.error(node, "isinstance() takes two arguments")
            kinds = self.type_names(node.args[1])
            return f"$rt.isinstance({self.expr(node.args[0])}, {json.dumps(kinds)})"
        raise self.error(node, f"{name}() is not available in client code")

    def type_names(self, node: ast.expr) -> list[str]:
        targets = node.elts if isinstance(node, ast.Tuple) else [node]
        out = []
        for t in targets:
            found = self.lookup(t)
            kind = TYPES.get(found) if isinstance(found, type) else None
            if kind is None:
                raise self.error(t, "isinstance() in client code checks int, float, str, bool, list, tuple and dict")
            out.append(kind)
        return out

    def method_call(self, func: ast.Attribute, node: ast.Call) -> str:
        params = METHODS.get(func.attr)
        if params is None:
            raise self.error(func, f".{func.attr}() is not available in client code")
        args = self.arguments(node, params)
        return f"$rt.m({self.expr(func.value)}, {json.dumps(func.attr)}{', ' + args if args else ''})"

    def self_call(self, name: str, node: ast.Call) -> str:
        module = self.module
        if name == "remote":
            return self.remote(node)
        if name == "navigate":
            return f"$rt.navigate({self.arguments(node, ('url',))})"
        if name == "touch":
            return "$rt.touch($c)"
        if name == "run_js":
            ops = [self.evaluate(a) for a in node.args if self.is_static(a)]
            if len(ops) != len(node.args) or not all(isinstance(op, ClientOp) for op in ops):
                raise self.error(node, "run_js() takes constant js.* operations")
            payload = json.dumps([op.to_json() for op in ops], separators=(",", ":"))
            return f"$rt.runjs($c, {payload})"
        if name in module.methods:
            fn = module.methods[name]
            params = tuple(inspect.signature(fn).parameters)[1:]
            return (
                f"{module.method(name)}($c{', ' if node.args or node.keywords else ''}{self.arguments(node, params)})"
            )
        if name in module.props:
            return f"$rt.callable($c.p.{name})({', '.join(self.positional(node))})"
        if name in SERVER_ONLY:
            raise self.error(node, f"self.{name}() is only available on the server, not in client code")
        raise self.error(node, f"{module.cls.__name__} has no method {name}()")

    def remote(self, node: ast.Call) -> str:
        if not node.args:
            raise self.error(node, "self.remote() takes the service method first: self.remote(Service.method, ...)")
        method = self.lookup(node.args[0])
        spec = getattr(method, "__rw_remote__", None)
        service = getattr(method, "__rw_service__", None)
        if spec is None or service is None:
            raise self.error(node, f"{ast.unparse(node.args[0])} is not a @remote method of a registered service")
        from ...backend.services import service_slug

        params = tuple(inspect.signature(method).parameters)[1:]
        call = ast.Call(func=node.func, args=node.args[1:], keywords=node.keywords)
        ast.copy_location(call, node)
        values = self.argument_values(call, params)
        named = []
        for param, value in zip(params, values, strict=False):
            if value != "undefined":
                named.append(f"{json.dumps(param)}: {value}")
        target = {
            "service": service_slug(service),
            "method": method.__name__.replace("_", "-"),
            "verb": spec.method,
            "path": spec.path,
        }
        return f"$rt.remote({json.dumps(target)}, {{{', '.join(named)}}})"

    # -- islands -------------------------------------------------------------------------------------

    def island(self, cls: type[Component], node: ast.Call) -> str:
        """A client component created by this one, in the browser."""
        if not getattr(cls, "_rw_client", False):
            raise self.error(
                node,
                f"{cls.__name__} is a server component; a client component can only create client components "
                "(pass server components in as children instead)",
            )
        self.module.children[cls] = None
        child = self.module.modules(cls)
        if child is not None and child.mount_error:
            raise self.error(
                node,
                f"{cls.__name__} is created in the browser here, but its mount() cannot run there:\n"
                f"{child.mount_error}",
            )
        props: list[str] = []
        key = style = "null"
        for kw in node.keywords:
            if kw.arg is None:
                raise self.error(kw, "**props are not supported in client code")
            if kw.arg == "key":
                key = f"$rt.str({self.expr(kw.value)})"
            elif kw.arg == "style":
                if not self.is_static(kw.value):
                    raise self.error(kw, "style= must be a constant Style in client code")
                value = self.evaluate(kw.value)
                style = "null" if value is None else json.dumps(self.module.style_class(value))
            elif kw.arg in cls._rw_props:
                props.append(f"{json.dumps(kw.arg)}: {self.prop_value(kw.value)}")
            else:
                raise self.error(kw, f"{cls.__name__} has no prop {kw.arg!r}")
        given = {kw.arg for kw in node.keywords}
        missing = [n for n, d in cls._rw_props.items() if n not in given and repr(d) == "REQUIRED"]
        if missing:
            raise self.error(node, f"{cls.__name__}() is missing required prop(s): {', '.join(missing)}")
        slot = "[" + ", ".join(self.element(a) for a in node.args) + "]"
        return f"$rt.island($c, {json.dumps(module_key(cls))}, {{{', '.join(props)}}}, {slot}, {key}, {style})"

    def prop_value(self, node: ast.expr) -> str:
        if isinstance(node, ast.Attribute) and self.is_self(node.value) and node.attr in self.module.methods:
            return self.handler(node)
        return self.expr(node)
