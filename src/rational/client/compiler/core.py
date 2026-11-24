"""What every part of compiling one function shares: its state, errors, output lines, and the
names and constants it can resolve at compile time."""

from __future__ import annotations

import ast
import builtins
import enum
import json
import linecache
from collections.abc import Callable
from types import FunctionType
from typing import TYPE_CHECKING, Any

from ...rendering.nodes import Node, RawHTML, TextNode
from ...styling.style import Style
from ..templates import TraceFrame, string_js
from .base import ClientCompileError, js_name, number
from .source import definition, namespace_of
from .tables import BINARY, NATIVE, PURE, is_op

if TYPE_CHECKING:
    from .module import ModuleCompiler


def _literal_js(value: Any, frame: TraceFrame | None) -> str | None:
    """``None``, a bool, a number or a string as JavaScript; ``None`` for any other value."""
    if value is None:
        return "null"
    if value is True or value is False:
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return number(value)
    if isinstance(value, str):
        return string_js(value, frame)
    return None


class FunctionCore:
    """The state of one function being compiled. The mixins built on it compile its parts."""

    # Set by FunctionCompiler.compile(), from the function's parameters and body.
    params: set[str]
    local_names: set[str]
    loop_names: set[str]

    def __init__(self, module: ModuleCompiler, fn: FunctionType, js_name: str, *, method: bool) -> None:
        self.module = module
        self.fn = fn
        self.js_name = js_name
        self.method = method
        self.node = definition(fn)
        self.filename = fn.__code__.co_filename
        self.namespace = namespace_of(fn)
        self.is_async = isinstance(self.node, ast.AsyncFunctionDef)
        self.where = f"{module.cls.__name__}.{fn.__name__}" if method else fn.__name__
        self.lines: list[str] = []
        self.depth = 1
        self.temps: list[list[str]] = [[]]  # one list per JavaScript function scope
        self.counter = 0
        self.scopes: list[set[str]] = []  # names bound by lambdas and comprehensions being compiled
        self.loops: list[set[str]] = []  # names bound by the for loops around the current statement
        self.async_ok = [self.is_async]  # False inside lambdas and comprehensions (JS arrow functions)

    # -- errors ----------------------------------------------------------------------------------

    def error(self, node: ast.AST, message: str) -> ClientCompileError:
        line = getattr(node, "lineno", self.node.lineno)
        text = linecache.getline(self.filename, line).strip()
        return ClientCompileError(f'{message}\n  File "{self.filename}", line {line}, in {self.where}\n    {text}')

    # -- output ----------------------------------------------------------------------------------

    def temp(self, kind: str) -> str:
        self.counter += 1
        name = f"${kind}{self.counter}"
        self.temps[-1].append(name)
        return name

    def emit(self, line: str) -> None:
        self.lines.append("  " * self.depth + line)

    def block(self, body: list[ast.stmt]) -> None:
        for stmt in body:
            self.statement(stmt)

    def indented(self, body: list[ast.stmt]) -> None:
        self.depth += 1
        self.block(body)
        self.depth -= 1

    def binding(self, target: ast.expr) -> str:
        """A loop or unpacking target as a JavaScript binding pattern."""
        if isinstance(target, ast.Name):
            return js_name(target.id)
        if isinstance(target, (ast.Tuple, ast.List)):
            return "[" + ", ".join(self.binding(t) for t in target.elts) + "]"
        raise self.error(target, "loop variables must be names or tuples of names")

    def operator(self, op: ast.operator, node: ast.AST) -> Callable[[str, str], str]:
        helper = BINARY.get(type(op))
        if helper is not None:
            return lambda a, b: f"{helper}({a}, {b})"
        native = NATIVE.get(type(op))
        if native is not None:
            return lambda a, b: f"({a} {native} {b})"
        raise self.error(node, f"operator {type(op).__name__} is not supported in client code")

    # -- names and constants ----------------------------------------------------------------------

    def is_self(self, node: ast.AST) -> bool:
        return self.method and isinstance(node, ast.Name) and node.id == "self" and not self.is_local("self")

    def is_local(self, name: str) -> bool:
        if any(name in scope for scope in self.scopes):
            return True
        if name in self.loop_names:
            return any(name in loop for loop in self.loops)
        return name in self.local_names and not (self.method and name == "self")

    def is_static(self, node: ast.AST) -> bool:
        """True if ``node`` can be evaluated now, at compile time: no locals, no self, no side effects."""
        for n in ast.walk(node):
            if isinstance(n, ast.Name) and (self.is_local(n.id) or (self.method and n.id == "self")):
                return False
            if isinstance(n, (ast.Await, ast.Lambda, ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
                return False
            if isinstance(n, ast.NamedExpr):
                return False
            if isinstance(n, ast.Call):
                fn = self.lookup(n.func)
                if not (isinstance(fn, type) and issubclass(fn, Style)) and fn not in PURE and not is_op(fn):
                    return False
        return True

    def lookup(self, node: ast.AST) -> Any:
        """The compile-time value of a name or attribute chain, or ``None`` if it is not one."""
        if isinstance(node, ast.Name):
            if self.is_local(node.id) or (self.method and node.id == "self"):
                return None
            if node.id in self.namespace:
                return self.namespace[node.id]
            return getattr(builtins, node.id, None)
        if isinstance(node, ast.Attribute):
            base = self.lookup(node.value)
            return None if base is None else getattr(base, node.attr, None)
        return None

    def evaluate(self, node: ast.expr) -> Any:
        try:
            code = compile(ast.Expression(body=node), self.filename, "eval")
            return eval(code, self.namespace)  # noqa: S307 - the developer's own constant expression
        except Exception as e:
            raise self.error(node, f"could not evaluate {ast.unparse(node)} at compile time: {e}") from None

    def constant(self, node: ast.expr) -> str:
        if not self.is_static(node):
            raise self.error(node, "default values must be constants")
        return self.value_js(self.evaluate(node), node)

    def value_js(self, value: Any, node: ast.AST, frame: TraceFrame | None = None) -> str:
        """A compile-time Python value as JavaScript."""
        if isinstance(value, enum.Enum):
            if isinstance(value, (str, int)):
                return self.value_js(value.value, node)
            raise self.error(node, f"{value!r}: only str and int enums (StrEnum, IntEnum) are available in client code")
        literal = _literal_js(value, frame)
        if literal is not None:
            return literal
        if isinstance(value, (list, tuple)):
            return "[" + ", ".join(self.value_js(v, node, frame) for v in value) + "]"
        if isinstance(value, dict):
            if not all(isinstance(k, str) for k in value):
                raise self.error(node, "dictionaries in client code need string keys")
            return "{" + ", ".join(f"{json.dumps(k)}: {self.value_js(v, node, frame)}" for k, v in value.items()) + "}"
        if isinstance(value, (Node, TextNode, RawHTML)):
            return self.tree_js(value, frame, node)
        if isinstance(value, Style):
            raise self.error(node, "a Style can only be passed to an element (style=...) in client code")
        raise self.error(node, f"{type(value).__name__} values are not available in client code")

    def element(self, node: ast.expr) -> str:
        return f"...$rt.iter({self.expr(node.value)})" if isinstance(node, ast.Starred) else self.expr(node)

    def static(self, node: ast.expr) -> str:
        if isinstance(node, ast.Name) and node.id not in self.namespace and not hasattr(builtins, node.id):
            raise self.error(node, f"name {node.id!r} is not defined")
        return self.value_js(self.evaluate(node), node)

    # -- implemented by the mixins, declared here for the type checker -------------------------------

    if TYPE_CHECKING:

        def statement(self, node: ast.stmt) -> None: ...
        def expr(self, node: ast.expr) -> str: ...
        def condition(self, node: ast.expr) -> str: ...
        def lambda_(self, node: ast.Lambda) -> str: ...
        def call(self, node: ast.Call) -> str: ...
        def template(self, node: ast.Call, fn: Callable[..., Any]) -> str: ...
        def handler(self, node: ast.expr) -> str: ...
        def tree_js(self, value: Any, frame: TraceFrame | None, node: ast.AST) -> str: ...
