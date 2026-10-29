"""Compile :class:`~rational.client.ClientComponent` classes to JavaScript.

The input is ordinary Python, read from the source file with :mod:`ast`; the output is one JavaScript
module per class that registers itself with the browser runtime (``islands.js``). Python semantics that
JavaScript does not share (truthiness of empty lists, ``==`` on lists, ``//`` and ``%``, negative
indexes, ``str()`` of ``True``...) go through small helpers on ``$rt``. Calls to the primitives
(``Text``, ``Button``, ``h``...) are traced at compile time (:mod:`rational.client.templates`).

Anything outside the supported subset raises :class:`ClientCompileError` naming the file, the line and
the construct, when the component is first rendered.
"""

from __future__ import annotations

import ast
import asyncio
import builtins
import contextlib
import enum
import hashlib
import inspect
import json
import linecache
import math
import random
import time
from collections.abc import Callable
from dataclasses import dataclass
from types import FunctionType
from typing import TYPE_CHECKING, Any, cast

from ..component import Component
from ..events import ClientOp
from ..rendering.builder import h
from ..rendering.nodes import Node, RawHTML, TextNode, is_url_attribute
from ..state import MISSING, State, computed
from ..styling.style import Style
from .templates import HandlerRef, Hole, HoleError, TraceFrame, has_placeholder, string_js, tracing

if TYPE_CHECKING:
    from ..styling.compiler import StyleCompiler

MAX_TRACES = 32  # per call: a primitive traced once per combination of constant choices

_RESERVED = frozenset(
    [
        "await",
        "break",
        "case",
        "catch",
        "class",
        "const",
        "continue",
        "debugger",
        "default",
        "delete",
        "do",
        "else",
        "enum",
        "export",
        "extends",
        "false",
        "finally",
        "for",
        "function",
        "if",
        "implements",
        "import",
        "in",
        "instanceof",
        "interface",
        "let",
        "new",
        "null",
        "package",
        "private",
        "protected",
        "public",
        "return",
        "static",
        "super",
        "switch",
        "this",
        "throw",
        "true",
        "try",
        "typeof",
        "var",
        "void",
        "while",
        "with",
        "yield",
        "arguments",
        "eval",
        "undefined",
        "NaN",
        "Infinity",
    ]
)

# name -> (javascript function, parameter names). Keywords map onto the positions.
_BUILTINS: dict[str, tuple[str, tuple[str, ...]]] = {
    "len": ("$rt.len", ("obj",)),
    "str": ("$rt.str", ("object",)),
    "repr": ("$rt.repr", ("obj",)),
    "int": ("$rt.int", ("x", "base")),
    "float": ("$rt.float", ("x",)),
    "bool": ("$rt.truthy", ("x",)),
    "abs": ("$rt.abs", ("x",)),
    "round": ("$rt.round", ("number", "ndigits")),
    "sum": ("$rt.sum", ("iterable", "start")),
    "range": ("$rt.range", ("start", "stop", "step")),
    "enumerate": ("$rt.enumerate", ("iterable", "start")),
    "sorted": ("$rt.sorted", ("iterable", "key", "reverse")),
    "reversed": ("$rt.reversed", ("sequence",)),
    "list": ("$rt.list", ("iterable",)),
    "tuple": ("$rt.list", ("iterable",)),
    "any": ("$rt.any", ("iterable",)),
    "all": ("$rt.all", ("iterable",)),
    "chr": ("$rt.chr", ("i",)),
    "ord": ("$rt.ord", ("c",)),
}
_VARARGS = {"zip": "$rt.zip", "print": "$rt.print"}

# Methods of str, list and dict, dispatched on the runtime type by ``$rt.m``.
_METHODS: dict[str, tuple[str, ...]] = {
    # str
    "upper": (),
    "lower": (),
    "title": (),
    "capitalize": (),
    "swapcase": (),
    "casefold": (),
    "strip": ("chars",),
    "lstrip": ("chars",),
    "rstrip": ("chars",),
    "split": ("sep", "maxsplit"),
    "rsplit": ("sep", "maxsplit"),
    "splitlines": ("keepends",),
    "join": ("iterable",),
    "replace": ("old", "new", "count"),
    "startswith": ("prefix", "start", "end"),
    "endswith": ("suffix", "start", "end"),
    "find": ("sub", "start", "end"),
    "rfind": ("sub", "start", "end"),
    "isdigit": (),
    "isalpha": (),
    "isalnum": (),
    "isspace": (),
    "isupper": (),
    "islower": (),
    "isnumeric": (),
    "zfill": ("width",),
    "center": ("width", "fillchar"),
    "ljust": ("width", "fillchar"),
    "rjust": ("width", "fillchar"),
    "partition": ("sep",),
    "rpartition": ("sep",),
    "removeprefix": ("prefix",),
    "removesuffix": ("suffix",),
    # str and list
    "index": ("value", "start", "end"),
    "count": ("value", "start", "end"),
    # list
    "append": ("object",),
    "extend": ("iterable",),
    "insert": ("index", "object"),
    "pop": ("index", "default"),
    "remove": ("value",),
    "sort": ("key", "reverse"),
    "reverse": (),
    "copy": (),
    "clear": (),
    # dict
    "get": ("key", "default"),
    "keys": (),
    "values": (),
    "items": (),
    "setdefault": ("key", "default"),
    "update": ("other",),
}

_FUNCTIONS: dict[Any, tuple[str, tuple[str, ...]]] = {
    asyncio.sleep: ("$rt.sleep", ("delay",)),
    math.floor: ("Math.floor", ("x",)),
    math.ceil: ("Math.ceil", ("x",)),
    math.trunc: ("Math.trunc", ("x",)),
    math.sqrt: ("$rt.sqrt", ("x",)),
    math.isnan: ("Number.isNaN", ("x",)),
    math.isfinite: ("Number.isFinite", ("x",)),
    time.time: ("$rt.time", ()),
    random.random: ("Math.random", ()),
    random.randint: ("$rt.randint", ("a", "b")),
    random.choice: ("$rt.choice", ("seq",)),
}

_EXCEPTIONS = frozenset(
    {
        "Exception",
        "RemoteError",
        "ValueError",
        "TypeError",
        "KeyError",
        "IndexError",
        "ZeroDivisionError",
        "AttributeError",
        "RuntimeError",
        "AssertionError",
    }
)
_TYPES = {int: "int", float: "float", str: "str", bool: "bool", list: "list", tuple: "list", dict: "dict"}
_CONVERSIONS: dict[Any, str] = {int: "int", float: "float", str: "str", bool: "bool"}
_BINARY = {
    ast.Add: "$rt.add",
    ast.Mult: "$rt.mul",
    ast.Div: "$rt.div",
    ast.FloorDiv: "$rt.floordiv",
    ast.Mod: "$rt.mod",
}
_NATIVE = {
    ast.Sub: "-",
    ast.Pow: "**",
    ast.BitAnd: "&",
    ast.BitOr: "|",
    ast.BitXor: "^",
    ast.LShift: "<<",
    ast.RShift: ">>",
}
_ORDER = {ast.Lt: "<", ast.LtE: "<=", ast.Gt: ">", ast.GtE: ">="}

# Methods every client component has, and what they become in the browser.
_OWN = frozenset({"remote", "navigate", "run_js", "touch"})
_SERVER_ONLY = frozenset({"context", "app", "use", "t", "run_task", "request", "provide", "inject"})


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


def compile_component(
    cls: type[Component], styles: StyleCompiler, modules: Callable[[type[Component]], ClientModule | None]
) -> ClientModule:
    """Compile ``cls``. ``modules`` returns the module of another client component (``None`` while it is
    itself being compiled), so a parent can check that the children it creates in the browser can mount."""
    return _Module(cls, styles, modules).build()


# -- source --------------------------------------------------------------------------------------


_trees: dict[str, ast.Module] = {}


def _definition(fn: FunctionType) -> ast.FunctionDef | ast.AsyncFunctionDef:
    """The AST of ``fn``, from its source file (exact line numbers, any indentation)."""
    code = fn.__code__
    filename = code.co_filename
    tree = _trees.get(filename)
    if tree is None:
        source = "".join(linecache.getlines(filename, fn.__globals__))
        if not source:
            raise ClientCompileError(f"cannot read the source of {fn.__qualname__} ({filename})")
        tree = _trees[filename] = ast.parse(source, filename)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == fn.__name__:
            first = min([node.lineno, *(d.lineno for d in node.decorator_list)])
            if first == code.co_firstlineno:
                return node
    raise ClientCompileError(f"cannot find the source of {fn.__qualname__} in {filename}")


def _namespace(fn: FunctionType) -> dict[str, Any]:
    names = dict(fn.__globals__)
    for name, cell in zip(fn.__code__.co_freevars, fn.__closure__ or (), strict=True):
        with contextlib.suppress(ValueError):  # an empty cell: defined later in the enclosing function
            names[name] = cell.cell_contents
    return names


def _bound_names(node: ast.AST) -> set[str]:
    """Names a function body assigns, outside nested lambdas and comprehensions (their own scopes) and
    outside for-loop targets (bound per iteration, see ``_loop_targets``)."""
    out: set[str] = set()

    def visit(n: ast.AST) -> None:
        if isinstance(n, (ast.Lambda, ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            return
        if isinstance(n, ast.For):
            for part in (n.iter, *n.body, *n.orelse):
                visit(part)
            return
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
            out.add(n.id)
        elif isinstance(n, ast.ExceptHandler) and n.name:
            out.add(n.name)
        for child in ast.iter_child_nodes(n):
            visit(child)

    for stmt in getattr(node, "body", []):
        visit(stmt)
    return out


def _loop_targets(node: ast.AST) -> set[str]:
    out: set[str] = set()
    for n in ast.walk(node):
        if isinstance(n, ast.For):
            out.update(t.id for t in ast.walk(n.target) if isinstance(t, ast.Name))
    return out


def _js_name(name: str) -> str:
    return name + "$" if name in _RESERVED else name


def _number(value: float) -> str:
    if math.isnan(value):
        return "NaN"
    if math.isinf(value):
        return "Infinity" if value > 0 else "-Infinity"
    return repr(value)


def _is_template_function(fn: Any) -> bool:
    if fn is h:
        return True
    module = getattr(fn, "__module__", "") or ""
    return isinstance(fn, FunctionType) and module.startswith("rational.components")


def _is_user_function(fn: Any) -> bool:
    module = getattr(fn, "__module__", "") or ""
    return isinstance(fn, FunctionType) and not module.startswith("rational") and not _stdlib(module)


def _stdlib(module: str) -> bool:
    return module.split(".")[0] in {"asyncio", "math", "random", "time", "builtins", "json", "typing", "enum"}


# -- the module ----------------------------------------------------------------------------------


class _Module:
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
                    if initial is MISSING or not _json_value(initial):
                        raise ClientCompileError(
                            f"{self.cls.__name__}.{name}: client component state must start as JSON data "
                            f"(numbers, strings, booleans, None, lists and dicts), not {initial!r}"
                        )
                    out[name] = initial
        return out

    def _methods(self) -> dict[str, FunctionType]:
        from .component import ClientComponent

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
                self.functions[js] = _Function(self, fn, js, method=True).compile()
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
                self.functions[js] = _Function(self, getter, js, method=True).compile()
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
                self.functions[js] = _Function(self, fn, js, method=False).compile()
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


def _json_value(value: Any) -> bool:
    try:
        return bool(json.loads(json.dumps(value)) == value)
    except (TypeError, ValueError):
        return False


# -- one function --------------------------------------------------------------------------------


class _Function:
    """Compiles one method or helper function to a JavaScript function declaration."""

    def __init__(self, module: _Module, fn: FunctionType, js_name: str, *, method: bool) -> None:
        self.module = module
        self.fn = fn
        self.js_name = js_name
        self.method = method
        self.node = _definition(fn)
        self.filename = fn.__code__.co_filename
        self.namespace = _namespace(fn)
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

    # -- driver ----------------------------------------------------------------------------------

    def compile(self) -> str:
        args = self.node.args
        if args.vararg or args.kwarg or args.posonlyargs or args.kwonlyargs:
            raise self.error(self.node, "client code supports plain positional parameters only (no *, ** or /)")
        params = [a.arg for a in args.args]
        if self.method:
            if not params or params[0] != "self":
                raise self.error(self.node, "a method's first parameter must be self")
            params = params[1:]
        defaults = [None] * (len(params) - len(args.defaults)) + list(args.defaults)
        self.params = set(params)
        self.local_names = _bound_names(self.node) | self.params
        self.loop_names = _loop_targets(self.node)
        clash = self.loop_names & (self.local_names - self.params)
        if clash:
            raise self.error(
                self.node, f"{', '.join(sorted(clash))}: a for-loop variable cannot also be assigned elsewhere"
            )
        if self.loop_names & self.params:
            raise self.error(self.node, "a for-loop variable cannot reuse a parameter's name")
        js_params = ["$c"]
        for name, default in zip(params, defaults, strict=True):
            js_params.append(_js_name(name) + ("" if default is None else f" = {self.constant(default)}"))
        body = self.node.body
        if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
            body = body[1:]  # docstring
        self.block(body)
        hoisted = sorted(self.local_names - self.params - self.loop_names)
        declared = [_js_name(n) for n in hoisted] + self.temps[0]
        head = f"{'async ' if self.is_async else ''}function {self.js_name}({', '.join(js_params)}) {{"
        decl = [f"  let {', '.join(declared)};"] if declared else []
        return "\n".join([head, *decl, *self.lines, "}"])

    def temp(self, kind: str) -> str:
        self.counter += 1
        name = f"${kind}{self.counter}"
        self.temps[-1].append(name)
        return name

    def emit(self, line: str) -> None:
        self.lines.append("  " * self.depth + line)

    # -- statements ------------------------------------------------------------------------------

    def block(self, body: list[ast.stmt]) -> None:
        for stmt in body:
            self.statement(stmt)

    def indented(self, body: list[ast.stmt]) -> None:
        self.depth += 1
        self.block(body)
        self.depth -= 1

    def statement(self, node: ast.stmt) -> None:  # noqa: C901 - one branch per statement kind
        if isinstance(node, ast.Expr):
            if isinstance(node.value, ast.Constant):
                return  # a bare string (comment-like)
            self.emit(f"{self.expr(node.value)};")
        elif isinstance(node, ast.Return):
            self.emit("return null;" if node.value is None else f"return {self.expr(node.value)};")
        elif isinstance(node, ast.Assign):
            value = self.expr(node.value)
            if len(node.targets) > 1:
                tmp = self.temp("v")
                self.emit(f"{tmp} = {value};")
                value = tmp
            for target in node.targets:
                self.assign(target, value)
        elif isinstance(node, ast.AnnAssign):
            if node.value is not None:
                self.assign(node.target, self.expr(node.value))
        elif isinstance(node, ast.AugAssign):
            self.augmented(node)
        elif isinstance(node, ast.If):
            self.emit(f"if ({self.condition(node.test)}) {{")
            self.indented(node.body)
            orelse = node.orelse
            while len(orelse) == 1 and isinstance(orelse[0], ast.If):
                self.emit(f"}} else if ({self.condition(orelse[0].test)}) {{")
                self.indented(orelse[0].body)
                orelse = orelse[0].orelse
            if orelse:
                self.emit("} else {")
                self.indented(orelse)
            self.emit("}")
        elif isinstance(node, ast.For):
            if node.orelse:
                raise self.error(node, "for ... else is not supported in client code")
            names = {t.id for t in ast.walk(node.target) if isinstance(t, ast.Name)}
            self.emit(f"for (let {self.binding(node.target)} of $rt.iter({self.expr(node.iter)})) {{")
            self.loops.append(names)
            self.indented(node.body)
            self.loops.pop()
            self.emit("}")
        elif isinstance(node, ast.While):
            if node.orelse:
                raise self.error(node, "while ... else is not supported in client code")
            self.emit(f"while ({self.condition(node.test)}) {{")
            self.indented(node.body)
            self.emit("}")
        elif isinstance(node, ast.Break):
            self.emit("break;")
        elif isinstance(node, ast.Continue):
            self.emit("continue;")
        elif isinstance(node, ast.Pass):
            pass
        elif isinstance(node, ast.Raise):
            self.raise_(node)
        elif isinstance(node, ast.Try):
            self.try_(node)
        elif isinstance(node, ast.Assert):
            message = "null" if node.msg is None else self.expr(node.msg)
            self.emit(f'if (!{self.condition(node.test)}) throw $rt.error("AssertionError", {message});')
        elif isinstance(node, ast.Delete):
            for target in node.targets:
                if not isinstance(target, ast.Subscript) or isinstance(target.slice, ast.Slice):
                    raise self.error(node, "del works on items (del d[key], del items[i]) in client code")
                self.emit(f"$rt.del({self.expr(target.value)}, {self.expr(target.slice)});")
        else:
            raise self.error(node, f"{type(node).__name__} statements are not supported in client code")

    def binding(self, target: ast.expr) -> str:
        """A loop or unpacking target as a JavaScript binding pattern."""
        if isinstance(target, ast.Name):
            return _js_name(target.id)
        if isinstance(target, (ast.Tuple, ast.List)):
            return "[" + ", ".join(self.binding(t) for t in target.elts) + "]"
        raise self.error(target, "loop variables must be names or tuples of names")

    def assign(self, target: ast.expr, value: str) -> None:
        if isinstance(target, ast.Name):
            if target.id in self.loop_names:
                raise self.error(target, f"{target.id} is a for-loop variable; assign to another name")
            self.emit(f"{_js_name(target.id)} = {value};")
        elif isinstance(target, ast.Attribute) and self.is_self(target.value):
            self.emit(f"{self.state_ref(target)} = {value};")
        elif isinstance(target, ast.Subscript):
            if isinstance(target.slice, ast.Slice):
                raise self.error(target, "slice assignment is not supported in client code")
            self.emit(f"$rt.set({self.expr(target.value)}, {self.expr(target.slice)}, {value});")
        elif isinstance(target, (ast.Tuple, ast.List)):
            tmp = self.temp("v")
            self.emit(f"{tmp} = $rt.unpack({value}, {len(target.elts)});")
            for i, element in enumerate(target.elts):
                self.assign(element, f"{tmp}[{i}]")
        else:
            raise self.error(target, "this assignment target is not supported in client code")

    def state_ref(self, target: ast.Attribute) -> str:
        name = target.attr
        if name in self.module.states:
            return f"$c.s.{name}"
        if name in self.module.props:
            raise self.error(target, f"{name} is a prop; props are read-only (copy it into a State to change it)")
        raise self.error(target, f"{self.module.cls.__name__}.{name} is not a State attribute")

    def augmented(self, node: ast.AugAssign) -> None:
        op = self.operator(node.op, node)
        value = self.expr(node.value)
        target = node.target
        if isinstance(target, ast.Name):
            name = _js_name(target.id)
            self.emit(f"{name} = {op(name, value)};")
        elif isinstance(target, ast.Attribute) and self.is_self(target.value):
            ref = self.state_ref(target)
            self.emit(f"{ref} = {op(ref, value)};")
        elif isinstance(target, ast.Subscript) and not isinstance(target.slice, ast.Slice):
            obj, key = self.temp("v"), self.temp("v")
            self.emit(f"{obj} = {self.expr(target.value)}; {key} = {self.expr(target.slice)};")
            self.emit(f"$rt.set({obj}, {key}, {op(f'$rt.get({obj}, {key})', value)});")
        else:
            raise self.error(node, "this augmented assignment is not supported in client code")

    def operator(self, op: ast.operator, node: ast.AST) -> Callable[[str, str], str]:
        helper = _BINARY.get(type(op))
        if helper is not None:
            return lambda a, b: f"{helper}({a}, {b})"
        native = _NATIVE.get(type(op))
        if native is not None:
            return lambda a, b: f"({a} {native} {b})"
        raise self.error(node, f"operator {type(op).__name__} is not supported in client code")

    def raise_(self, node: ast.Raise) -> None:
        if node.exc is None:
            self.emit(
                "throw $e;"
                if any("$e" in line for line in self.lines)
                else 'throw $rt.error("RuntimeError", "no active exception");'
            )
            return
        exc = node.exc
        if isinstance(exc, ast.Call) and isinstance(exc.func, ast.Name) and exc.func.id in _EXCEPTIONS:
            message = self.expr(exc.args[0]) if exc.args else '""'
            self.emit(f"throw $rt.error({json.dumps(exc.func.id)}, {message});")
        elif isinstance(exc, ast.Name) and exc.id in _EXCEPTIONS:
            self.emit(f'throw $rt.error({json.dumps(exc.id)}, "");')
        elif isinstance(exc, ast.Name):
            self.emit(f"throw {self.expr(exc)};")
        else:
            raise self.error(node, f"client code can raise {', '.join(sorted(_EXCEPTIONS))} (with a message)")

    def try_(self, node: ast.Try) -> None:
        if node.orelse:
            raise self.error(node, "try ... else is not supported in client code")
        self.emit("try {")
        self.indented(node.body)
        if node.handlers:
            self.emit("} catch ($e) {")
            self.depth += 1
            first = True
            for handler in node.handlers:
                types = self.exception_types(handler)
                test = "true" if types is None else f"$rt.caught($e, {json.dumps(types)})"
                self.emit(f"{'if' if first else '} else if'} ({test}) {{")
                first = False
                self.depth += 1
                if handler.name:
                    self.emit(f"{_js_name(handler.name)} = $e;")
                self.block(handler.body)
                self.depth -= 1
            self.emit("} else {")
            self.emit("  throw $e;")
            self.emit("}")
            self.depth -= 1
        if node.finalbody:
            self.emit("} finally {")
            self.indented(node.finalbody)
        self.emit("}")

    def exception_types(self, handler: ast.ExceptHandler) -> list[str] | None:
        if handler.type is None:
            return None
        names = handler.type.elts if isinstance(handler.type, ast.Tuple) else [handler.type]
        out = []
        for n in names:
            if not (isinstance(n, ast.Name) and n.id in _EXCEPTIONS):
                raise self.error(handler, f"client code can catch {', '.join(sorted(_EXCEPTIONS))}")
            if n.id == "Exception":
                return None
            out.append(n.id)
        return out

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
                if not (isinstance(fn, type) and issubclass(fn, Style)) and fn not in _PURE and not _is_op(fn):
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
        if value is None:
            return "null"
        if value is True or value is False:
            return "true" if value else "false"
        if isinstance(value, enum.Enum):
            if isinstance(value, (str, int)):
                return self.value_js(value.value, node)
            raise self.error(node, f"{value!r}: only str and int enums (StrEnum, IntEnum) are available in client code")
        if isinstance(value, int):
            return str(value)
        if isinstance(value, float):
            return _number(value)
        if isinstance(value, str):
            return string_js(value, frame)
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

    # -- expressions -------------------------------------------------------------------------------

    def condition(self, node: ast.expr) -> str:
        """``node`` as a JavaScript boolean, with Python truthiness."""
        if isinstance(node, ast.BoolOp):
            joiner = " && " if isinstance(node.op, ast.And) else " || "
            return "(" + joiner.join(self.condition(v) for v in node.values) + ")"
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            return f"!{self.condition(node.operand)}"
        if isinstance(node, ast.Compare):
            return self.expr(node)
        if isinstance(node, ast.Constant) and isinstance(node.value, bool):
            return "true" if node.value else "false"
        return f"$rt.truthy({self.expr(node)})"

    def expr(self, node: ast.expr) -> str:  # noqa: C901 - one branch per expression kind
        if isinstance(node, ast.Constant):
            return self.value_js(node.value, node)
        if isinstance(node, ast.Name):
            if self.is_local(node.id):
                return _js_name(node.id)
            if self.method and node.id == "self":
                raise self.error(node, "self can only be used for its attributes and methods in client code")
            return self.static(node)
        if isinstance(node, ast.Attribute):
            if self.is_self(node.value):
                return self.self_attribute(node)
            if self.is_static(node):
                return self.static(node)
            base = self.expr(node.value)  # reports a problem with the object itself first (self.context...)
            if node.attr in ("message", "args"):
                return f"{base}.{node.attr}"
            raise self.error(node, f'.{node.attr}: use item["{node.attr}"] for dictionaries in client code')
        if isinstance(node, ast.Call):
            return self.call(node)
        if isinstance(node, ast.BinOp):
            return self.operator(node.op, node)(self.expr(node.left), self.expr(node.right))
        if isinstance(node, ast.UnaryOp):
            if isinstance(node.op, ast.Not):
                return f"!{self.condition(node.operand)}"
            symbol = {ast.USub: "-", ast.UAdd: "+", ast.Invert: "~"}[type(node.op)]
            return f"({symbol}{self.expr(node.operand)})"
        if isinstance(node, ast.BoolOp):
            helper = "$rt.and" if isinstance(node.op, ast.And) else "$rt.or"
            out = self.expr(node.values[-1])
            for value in reversed(node.values[:-1]):
                out = f"{helper}({self.expr(value)}, () => {out})"
            return out
        if isinstance(node, ast.Compare):
            return self.compare(node)
        if isinstance(node, ast.IfExp):
            return f"({self.condition(node.test)} ? {self.expr(node.body)} : {self.expr(node.orelse)})"
        if isinstance(node, ast.Subscript):
            if isinstance(node.slice, ast.Slice):
                s = node.slice
                bounds = [self.expr(b) if b is not None else "null" for b in (s.lower, s.upper, s.step)]
                return f"$rt.slice({self.expr(node.value)}, {', '.join(bounds)})"
            return f"$rt.get({self.expr(node.value)}, {self.expr(node.slice)})"
        if isinstance(node, (ast.List, ast.Tuple)):
            return "[" + ", ".join(self.element(e) for e in node.elts) + "]"
        if isinstance(node, ast.Dict):
            items = []
            for key, value in zip(node.keys, node.values, strict=True):
                items.append(
                    f"...$rt.dict({self.expr(value)})" if key is None else f"[{self.expr(key)}]: {self.expr(value)}"
                )
            return "{" + ", ".join(items) + "}"
        if isinstance(node, ast.JoinedStr):
            return self.fstring(node)
        if isinstance(node, (ast.ListComp, ast.GeneratorExp)):
            return self.comprehension(node.generators, lambda: f"$out.push({self.expr(node.elt)});")
        if isinstance(node, ast.DictComp):
            return self.comprehension(
                node.generators, lambda: f"$rt.set($out, {self.expr(node.key)}, {self.expr(node.value)});", "{}"
            )
        if isinstance(node, ast.Lambda):
            return self.lambda_(node)
        if isinstance(node, ast.Await):
            if not self.async_ok[-1]:
                raise self.error(
                    node, "await is only allowed directly in an async method (not in a lambda or comprehension)"
                )
            return f"(await {self.expr(node.value)})"
        raise self.error(node, f"{type(node).__name__} expressions are not supported in client code")

    def element(self, node: ast.expr) -> str:
        return f"...$rt.iter({self.expr(node.value)})" if isinstance(node, ast.Starred) else self.expr(node)

    def static(self, node: ast.expr) -> str:
        if isinstance(node, ast.Name) and node.id not in self.namespace and not hasattr(builtins, node.id):
            raise self.error(node, f"name {node.id!r} is not defined")
        return self.value_js(self.evaluate(node), node)

    def self_attribute(self, node: ast.Attribute) -> str:
        name = node.attr
        module = self.module
        if name in module.states:
            return f"$c.s.{name}"
        if name in module.props:
            return f"$c.p.{name}"
        if name == "children":
            return "$c.slot"
        if name in module.computed:
            return f"{module.getter(name)}($c)"
        if name in module.methods:
            fn = module.method(name)
            return f"((...a) => {fn}($c, ...a))"
        if name in _SERVER_ONLY:
            raise self.error(node, f"self.{name} is only available on the server, not in client code")
        raise self.error(node, f"{module.cls.__name__} has no prop, state or method named {name}")

    def compare(self, node: ast.Compare) -> str:
        operands = [node.left, *node.comparators]
        if len(operands) > 2 and any(
            not isinstance(o, (ast.Name, ast.Constant, ast.Attribute)) for o in operands[1:-1]
        ):
            raise self.error(node, "chained comparisons may only have names and constants in the middle")
        parts = []
        for op, left, right in zip(node.ops, operands[:-1], operands[1:], strict=True):
            a, b = self.expr(left), self.expr(right)
            if isinstance(op, ast.Eq):
                parts.append(f"$rt.eq({a}, {b})")
            elif isinstance(op, ast.NotEq):
                parts.append(f"!$rt.eq({a}, {b})")
            elif isinstance(op, (ast.Is, ast.IsNot)):
                negate = isinstance(op, ast.IsNot)
                if isinstance(right, ast.Constant) and right.value is None:
                    parts.append(f"({a} {'!=' if negate else '=='} null)")
                else:
                    parts.append(f"({a} {'!==' if negate else '==='} {b})")
            elif isinstance(op, ast.In):
                parts.append(f"$rt.contains({b}, {a})")
            elif isinstance(op, ast.NotIn):
                parts.append(f"!$rt.contains({b}, {a})")
            else:
                parts.append(f"($rt.cmp({a}, {b}) {_ORDER[type(op)]} 0)")
        return parts[0] if len(parts) == 1 else "(" + " && ".join(parts) + ")"

    def fstring(self, node: ast.JoinedStr) -> str:
        parts = []
        for value in node.values:
            if isinstance(value, ast.Constant):
                parts.append(json.dumps(value.value))
                continue
            assert isinstance(value, ast.FormattedValue)
            inner = self.expr(value.value)
            if value.conversion == ord("r"):
                inner = f"$rt.repr({inner})"
            elif value.conversion == ord("a"):
                raise self.error(node, "!a conversions are not supported in client code")
            spec = value.format_spec
            if isinstance(spec, ast.JoinedStr):
                if all(isinstance(v, ast.Constant) for v in spec.values):
                    text = "".join(str(v.value) for v in spec.values if isinstance(v, ast.Constant))
                    parts.append(f"$rt.fmt({inner}, {json.dumps(text)})")
                else:
                    parts.append(f"$rt.fmt({inner}, {self.fstring(spec)})")
            else:
                parts.append(f"$rt.str({inner})")
        if not parts:
            return '""'
        return "(" + " + ".join(['""', *parts] if len(parts) == 1 else parts) + ")"

    def comprehension(self, generators: list[ast.comprehension], body: Callable[[], str], start: str = "[]") -> str:
        names: set[str] = set()
        for gen in generators:
            if gen.is_async:
                raise self.error(gen.target, "async comprehensions are not supported in client code")
            names.update(t.id for t in ast.walk(gen.target) if isinstance(t, ast.Name))
        self.temps.append([])
        self.async_ok.append(False)
        lines: list[str] = []
        opened = 0
        try:
            for gen in generators:
                lines.append(f"for (let {self.binding(gen.target)} of $rt.iter({self.expr(gen.iter)})) {{")
                self.scopes.append({t.id for t in ast.walk(gen.target) if isinstance(t, ast.Name)})
                opened += 1
                for test in gen.ifs:
                    lines.append(f"if (!{self.condition(test)}) continue;")
            lines.append(body())
        finally:
            for _ in range(opened):
                self.scopes.pop()
            self.async_ok.pop()
            temps = self.temps.pop()
        decl = f"let {', '.join(temps)}; " if temps else ""
        return f"(() => {{ {decl}const $out = {start}; {' '.join(lines)}{' }' * opened} return $out; }})()"

    def lambda_(self, node: ast.Lambda) -> str:
        args = node.args
        if args.vararg or args.kwarg or args.posonlyargs or args.kwonlyargs:
            raise self.error(node, "lambdas in client code take plain positional parameters only")
        params = [a.arg for a in args.args]
        defaults = [None] * (len(params) - len(args.defaults)) + list(args.defaults)
        js_params = [
            _js_name(p) + ("" if d is None else f" = {self.expr(d)}") for p, d in zip(params, defaults, strict=True)
        ]
        self.scopes.append(set(params))
        self.temps.append([])
        self.async_ok.append(False)
        try:
            body = self.expr(node.body)
        finally:
            self.scopes.pop()
            self.async_ok.pop()
            temps = self.temps.pop()
        if temps:
            return f"(({', '.join(js_params)}) => {{ let {', '.join(temps)}; return {body}; }})"
        return f"(({', '.join(js_params)}) => {body})"

    # -- calls -----------------------------------------------------------------------------------------

    def call(self, node: ast.Call) -> str:  # noqa: C901 - one branch per kind of callee
        func = node.func
        if isinstance(func, ast.Attribute) and self.is_self(func.value):
            return self.self_call(func.attr, node)
        if isinstance(func, ast.Attribute) and not self.is_static(func.value):
            return self.method_call(func, node)
        if isinstance(func, ast.Name) and self.is_local(func.id):
            return f"$rt.callable({_js_name(func.id)})({', '.join(self.positional(node))})"
        if (
            isinstance(func, ast.Attribute)
            and func.attr in _METHODS
            and isinstance(self.evaluate(func.value), (str, list, tuple, dict))
        ):
            return self.method_call(func, node)  # a method of constant data: ", ".join(names)
        target = self.lookup(func)
        if target is None and isinstance(func, ast.Name) and func.id not in self.namespace:
            raise self.error(node, f"name {func.id!r} is not defined")
        if isinstance(func, ast.Name) and target is getattr(builtins, func.id, None) and func.id not in self.namespace:
            return self.builtin(func.id, node)
        if target in _FUNCTIONS:
            js, params = _FUNCTIONS[target]
            args = self.arguments(node, params)
            return f"$rt.sleep($c, {args})" if target is asyncio.sleep else f"{js}({args})"
        if isinstance(target, type) and issubclass(target, Component):
            if not getattr(target, "_rw_client", False):
                raise self.error(
                    node,
                    f"{target.__name__} is a server component; a client component can only create client components "
                    "(pass server components in as children instead)",
                )
            return self.island(target, node)
        if _is_template_function(target):
            return self.template(node, target)
        if _is_user_function(target):
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
        if name in _BUILTINS:
            js, params = _BUILTINS[name]
            return f"{js}({self.arguments(node, params)})"
        if name in _VARARGS:
            if node.keywords:
                raise self.error(node, f"{name}() keyword arguments are not supported in client code")
            return f"{_VARARGS[name]}({', '.join(self.element(a) for a in node.args)})"
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
            kind = _TYPES.get(found) if isinstance(found, type) else None
            if kind is None:
                raise self.error(t, "isinstance() in client code checks int, float, str, bool, list, tuple and dict")
            out.append(kind)
        return out

    def method_call(self, func: ast.Attribute, node: ast.Call) -> str:
        params = _METHODS.get(func.attr)
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
        if name in _SERVER_ONLY:
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
        from ..backend.services import service_slug

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

    # -- templates ----------------------------------------------------------------------------------

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
        return _Bound(value, handler)

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
            kind = annotation if isinstance(annotation, str) else _CONVERSIONS.get(annotation, "")
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
            raise self.error(node, f"{_name(fn)}() varies in too many ways; split it with if statements")
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
                    f"{_name(fn)}() needs to know `{e.hole.label}` while it builds the element, but that value is only "
                    "known in the browser. Pass a constant, or choose between constants with `A if condition else B`.",
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
            raise self.error(node, f"{_name(fn)}(): {e}") from None

    def tree_js(self, value: Any, frame: TraceFrame | None, node: ast.AST) -> str:
        """A traced tree (or part of one) as a JavaScript vnode expression."""
        if value is None or value is True or value is False:
            return "null"
        if isinstance(value, Hole):
            return value.js
        if isinstance(value, str):
            return string_js(value, frame)
        if isinstance(value, (int, float)):
            return _number(value)
        if isinstance(value, TextNode):
            return string_js(value.text, frame)
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
        attrs: list[tuple[str, str]] = []
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
        if classes:
            attrs.append(("class", classes[0] if len(classes) == 1 else f"$rt.cls({', '.join(classes)})"))
        for name, value in element.attrs:
            if name == "class" or value is None or value is False:
                continue
            attrs.append((name, self.attr_js(name, value, frame, node)))
        for event, handler in element.events:
            if not isinstance(handler, HandlerRef):
                raise self.error(node, "event handlers in client code are methods, lambdas or js.* operations")
            attrs.append((f"data-rw-x-{event}", f"$rt.on($c, {handler.js})"))
        for event, ops in element.client:
            payload = json.dumps([op.to_json() for op in ops], separators=(",", ":"))
            if has_placeholder(payload):
                raise self.error(node, "js.* operations need constant arguments in client code")
            attrs.append((f"data-rw-js-{event}", json.dumps(payload)))
        if element.key is not None:
            attrs.append(("data-rw-key", string_js(element.key, frame)))
        attrs_js = "{" + ", ".join(f"{json.dumps(n)}: {v}" for n, v in attrs) + "}"
        children = ", ".join(self.tree_js(c, frame, node) for c in element.children)
        return f"{{t: {json.dumps(element.tag)}, a: {attrs_js}, c: [{children}]}}"

    def attr_js(self, name: str, value: Any, frame: TraceFrame | None, node: ast.AST) -> str:
        url = is_url_attribute(name)
        if value is True:
            return "true"
        if isinstance(value, Hole):
            return f"$rt.url({value.js})" if url else value.js
        if isinstance(value, str):
            js = string_js(value, frame)
            return f"$rt.url({js})" if url and has_placeholder(value) else js
        if isinstance(value, (int, float)):
            return _number(value)
        raise self.error(node, f"attribute {name}= cannot hold {type(value).__name__} in client code")


def _name(fn: Any) -> str:
    return getattr(fn, "__name__", repr(fn))


def _is_op(fn: Any) -> bool:
    return getattr(fn, "__qualname__", "").startswith("js.")


_PURE: frozenset[Any] = frozenset(
    {len, str, int, float, bool, abs, round, min, max, sum, sorted, list, tuple, dict, range, enumerate, zip, any, all}
)


class _Bound:
    """What a traced primitive sees for ``bind=``: ``value`` to show and ``set`` to call on input."""

    __slots__ = ("set", "value")

    def __init__(self, value: Hole, handler: HandlerRef) -> None:
        self.value = value
        self.set = handler
