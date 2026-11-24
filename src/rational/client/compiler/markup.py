"""Primitives (``Text``, ``Button``, ``h``...) called in client code: traced at compile time, and emitted
as code that rebuilds their tree in the browser (see :mod:`rational.client.templates`)."""

from __future__ import annotations

import ast
import inspect
import json
from collections.abc import Callable
from typing import Any

from ...component import Component
from ...events import ClientOp
from ...rendering.nodes import Node, RawHTML, TextNode, is_url_attribute
from ..templates import HandlerRef, Hole, HoleError, TraceFrame, has_placeholder, string_js, tracing
from .base import ClientCompileError, number
from .core import FunctionCore
from .tables import CONVERSIONS, MAX_TRACES, callable_name


class Markup(FunctionCore):
    def template(self, node: ast.Call, fn: Callable[..., Any]) -> str:
        """A call to a primitive, traced now and emitted as code that rebuilds its tree in the browser."""
        frame = TraceFrame(self.temp)
        choices: dict[int, tuple[str, list[Any]]] = {}
        args: list[Any] = []
        kwargs: dict[str, Any] = {}
        with tracing(frame):
            for arg in node.args:
                if isinstance(arg, ast.Starred):
                    if self.is_static(arg.value):
                        args.extend(self.evaluate(arg.value))
                    else:
                        args.append(frame.hole(f"$rt.list({self.expr(arg.value)})", ast.unparse(arg)))
                else:
                    args.append(self.argument(arg, frame, choices))
            for kw in node.keywords:
                if kw.arg is None:
                    raise self.error(kw, "**attributes are not supported in client code")
                if kw.arg.startswith("on_"):
                    kwargs[kw.arg] = self.handlers(kw.value)
                else:
                    kwargs[kw.arg] = self.argument(kw.value, frame, choices)
            tree = self.trace(node, fn, args, kwargs, frame, choices, budget=[MAX_TRACES])
        steps = frame.steps
        return f"({', '.join([*steps, tree])})" if steps else tree

    def argument(self, node: ast.expr, frame: TraceFrame, choices: dict[int, tuple[str, list[Any]]]) -> Any:
        """A template argument: a Python value when it is constant, otherwise a hole evaluated now."""
        label = ast.unparse(node)
        if self.is_static(node):
            return self.evaluate(node)
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and self.is_self(node.func.value)
            and node.func.attr == "bind"
        ):
            return self.bound_control(node, frame)
        if isinstance(node, ast.IfExp) and self.is_static(node.body) and self.is_static(node.orelse):
            values = [self.evaluate(node.body), self.evaluate(node.orelse)]
            test = frame.temp("a")
            frame.steps.append(f"{test} = {self.condition(node.test)}")
            try:
                js = f"({test} ? {self.value_js(values[0], node)} : {self.value_js(values[1], node)})"
            except ClientCompileError:
                js = "null"  # not representable (a Style...): only usable by tracing each choice
            hole = Hole(js, label)
            choices[id(hole)] = (test, values)
            return hole
        if isinstance(node, (ast.List, ast.Tuple)) and not any(isinstance(e, ast.Starred) for e in node.elts):
            items = [self.argument(e, frame, choices) for e in node.elts]
            return items if isinstance(node, ast.List) else tuple(items)
        return frame.hole(self.expr(node), label)

    def bound_control(self, node: ast.Call, frame: TraceFrame) -> Any:
        """``self.bind("name")`` as a form control argument: its value, and a handler storing input."""
        if len(node.args) != 1 or not isinstance(node.args[0], ast.Constant) or node.keywords:
            raise self.error(node, 'bind() takes the name of a State attribute: self.bind("name")')
        name = str(node.args[0].value)
        if name not in self.module.states:
            raise self.error(node, f"{self.module.cls.__name__}.{name} is not a State attribute; bind() needs one")
        initial = self.module.states[name]
        kind = next(
            (k for t, k in ((bool, "bool"), (int, "int"), (float, "float"), (str, "str")) if isinstance(initial, t)), ""
        )
        value = frame.hole(f"$c.s.{name}", f"self.{name}")
        handler = HandlerRef(f"((v) => $rt.bindset($c, {json.dumps(name)}, v, {json.dumps(kind)}))")
        return Bound(value, handler)

    def handlers(self, node: ast.expr) -> Any:
        """An ``on_<event>=`` value: handlers, ``js.*`` operations, or a list of both."""
        if isinstance(node, (ast.List, ast.Tuple)):
            return [self.handlers(e) for e in node.elts]
        if self.is_static(node):
            value = self.evaluate(node)
            if value is not None and not isinstance(value, ClientOp):
                raise self.error(node, "event handlers in client code are methods, lambdas or js.* operations")
            return value
        return HandlerRef(self.handler(node))

    def handler(self, node: ast.expr) -> str:
        if isinstance(node, ast.Attribute) and self.is_self(node.value) and node.attr in self.module.methods:
            fn = self.module.methods[node.attr]
            # Like the server's binding: the payload goes to the first parameter without a default, if any.
            params = [p for p in list(inspect.signature(fn).parameters.values())[1:] if p.default is p.empty]
            js = self.module.method(node.attr)
            if not params:
                return f"(() => {js}($c))"
            annotation = fn.__annotations__.get(params[0].name)  # a string under `from __future__ import annotations`
            kind = annotation if isinstance(annotation, str) else CONVERSIONS.get(annotation, "")
            if kind in ("int", "float", "str", "bool"):
                return f"((v) => {js}($c, $rt.convert(v, {json.dumps(kind)})))"
            return f"((v) => {js}($c, v))"
        if isinstance(node, ast.Lambda):
            return self.lambda_(node)
        return f"((v) => $rt.callable({self.expr(node)})(v))"

    def trace(
        self,
        node: ast.Call,
        fn: Callable[..., Any],
        args: list[Any],
        kwargs: dict[str, Any],
        frame: TraceFrame,
        choices: dict[int, tuple[str, list[Any]]],
        budget: list[int],
    ) -> str:
        budget[0] -= 1
        if budget[0] < 0:
            raise self.error(node, f"{callable_name(fn)}() varies in too many ways; split it with if statements")
        mark = len(frame.steps)
        try:
            result = fn(*args, **kwargs)
            return self.tree_js(result, frame, node)
        except HoleError as e:
            del frame.steps[mark:]
            choice = choices.get(id(e.hole))
            if choice is None:
                raise self.error(
                    node,
                    f"{callable_name(fn)}() needs to know `{e.hole.label}` while it builds the element, but that value "
                    "is only known in the browser. Pass a constant, or choose between constants with "
                    "`A if condition else B`.",
                ) from None
            test, values = choice
            branches = []
            for value in values:
                fixed_args = [value if a is e.hole else a for a in args]
                fixed_kwargs = {k: value if v is e.hole else v for k, v in kwargs.items()}
                start = len(frame.steps)
                tree = self.trace(node, fn, fixed_args, fixed_kwargs, frame, choices, budget)
                steps = frame.steps[start:]
                del frame.steps[start:]
                branches.append(f"({', '.join([*steps, tree])})" if steps else tree)
            return f"({test} ? {branches[0]} : {branches[1]})"
        except ClientCompileError:
            raise
        except Exception as e:
            raise self.error(node, f"{callable_name(fn)}(): {e}") from None

    def tree_js(self, value: Any, frame: TraceFrame | None, node: ast.AST) -> str:
        """A traced tree (or part of one) as a JavaScript vnode expression."""
        leaf = _leaf_js(value, frame)
        if leaf is not None:
            return leaf
        if isinstance(value, RawHTML):
            if not isinstance(value.html, str) or has_placeholder(value.html):
                raise self.error(node, "unsafe_html() needs constant markup in client code")
            return f"{{raw: {json.dumps(value.html)}}}"
        if isinstance(value, Node):
            return self.node_js(value, frame, node)
        if isinstance(value, Component):
            raise self.error(node, f"{type(value).__name__} cannot be nested in a primitive call in client code")
        if isinstance(value, (list, tuple)):
            return "[" + ", ".join(self.tree_js(v, frame, node) for v in value) + "]"
        raise self.error(node, f"cannot render {type(value).__name__} in client code")

    def node_js(self, element: Node, frame: TraceFrame | None, node: ast.AST) -> str:
        classes = self.classes_js(element, frame, node)
        attrs: list[tuple[str, str]] = [("class", classes)] if classes is not None else []
        for name, value in element.attrs:
            if name == "class" or value is None or value is False:
                continue
            attrs.append((name, self.attr_js(name, value, frame, node)))
        attrs += self.events_js(element, node)
        if element.key is not None:
            attrs.append(("data-rw-key", string_js(element.key, frame)))
        attrs_js = "{" + ", ".join(f"{json.dumps(n)}: {v}" for n, v in attrs) + "}"
        children = ", ".join(self.tree_js(c, frame, node) for c in element.children)
        return f"{{t: {json.dumps(element.tag)}, a: {attrs_js}, c: [{children}]}}"

    def classes_js(self, element: Node, frame: TraceFrame | None, node: ast.AST) -> str | None:
        """The element's ``class``: its own classes and its style's, or ``None`` without any."""
        classes = []
        own = element.attr("class")
        if isinstance(own, Hole):
            classes.append(own.js)
        elif own:
            classes.append(self.attr_js("class", own, frame, node))
        if isinstance(element.style, Hole):
            raise self.error(node, "style= must be a constant Style (or a choice of constants) in client code")
        if element.style is not None and element.style:
            classes.append(json.dumps(self.module.style_class(element.style)))
        if not classes:
            return None
        return classes[0] if len(classes) == 1 else f"$rt.cls({', '.join(classes)})"

    def events_js(self, element: Node, node: ast.AST) -> list[tuple[str, str]]:
        """The element's handlers and ``js.*`` operations, as the attributes the browser runtime reads."""
        attrs: list[tuple[str, str]] = []
        for event, handler in element.events:
            if not isinstance(handler, HandlerRef):
                raise self.error(node, "event handlers in client code are methods, lambdas or js.* operations")
            attrs.append((f"data-rw-x-{event}", f"$rt.on($c, {handler.js})"))
        for event, ops in element.client:
            payload = json.dumps([op.to_json() for op in ops], separators=(",", ":"))
            if has_placeholder(payload):
                raise self.error(node, "js.* operations need constant arguments in client code")
            attrs.append((f"data-rw-js-{event}", json.dumps(payload)))
        return attrs

    def attr_js(self, name: str, value: Any, frame: TraceFrame | None, node: ast.AST) -> str:
        url = is_url_attribute(name)
        if value is True:
            return "true"
        if isinstance(value, Hole):
            return f"$rt.url({value.js})" if url else value.js
        if isinstance(value, str):
            js = string_js(value, frame)
            return f"$rt.url({js})" if url and (has_placeholder(value) or value.startswith("/")) else js  # root path
        if isinstance(value, (int, float)):
            return number(value)
        raise self.error(node, f"attribute {name}= cannot hold {type(value).__name__} in client code")


def _leaf_js(value: Any, frame: TraceFrame | None) -> str | None:
    """Nothing, a hole, a string, a number or a text node as a vnode; ``None`` for any other value."""
    if value is None or value is True or value is False:
        return "null"
    if isinstance(value, Hole):
        return value.js
    if isinstance(value, (str, TextNode)):
        return string_js(value if isinstance(value, str) else value.text, frame)
    if isinstance(value, (int, float)):
        return number(value)
    return None


class Bound:
    """What a traced primitive sees for ``bind=``: ``value`` to show and ``set`` to call on input."""

    __slots__ = ("set", "value")

    def __init__(self, value: Hole, handler: HandlerRef) -> None:
        self.value = value
        self.set = handler
