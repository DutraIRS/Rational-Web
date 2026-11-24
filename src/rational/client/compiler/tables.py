"""What the compiler knows: JavaScript's reserved words, and the builtins, methods, functions,
operators and exceptions of Python that client code may use, with what each becomes."""

from __future__ import annotations

import ast
import asyncio
import math
import random
import time
from types import FunctionType
from typing import Any

from ...rendering.builder import h

MAX_TRACES = 32  # per call: a primitive traced once per combination of constant choices

RESERVED = frozenset(
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
BUILTINS: dict[str, tuple[str, tuple[str, ...]]] = {
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
VARARGS = {"zip": "$rt.zip", "print": "$rt.print"}

# Methods of str, list and dict, dispatched on the runtime type by ``$rt.m``.
METHODS: dict[str, tuple[str, ...]] = {
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

FUNCTIONS: dict[Any, tuple[str, tuple[str, ...]]] = {
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

EXCEPTIONS = frozenset(
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
TYPES = {int: "int", float: "float", str: "str", bool: "bool", list: "list", tuple: "list", dict: "dict"}
CONVERSIONS: dict[Any, str] = {int: "int", float: "float", str: "str", bool: "bool"}
BINARY = {
    ast.Add: "$rt.add",
    ast.Mult: "$rt.mul",
    ast.Div: "$rt.div",
    ast.FloorDiv: "$rt.floordiv",
    ast.Mod: "$rt.mod",
}
NATIVE = {
    ast.Sub: "-",
    ast.Pow: "**",
    ast.BitAnd: "&",
    ast.BitOr: "|",
    ast.BitXor: "^",
    ast.LShift: "<<",
    ast.RShift: ">>",
}
ORDER = {ast.Lt: "<", ast.LtE: "<=", ast.Gt: ">", ast.GtE: ">="}


# Methods of a component that exist on the server only.
SERVER_ONLY = frozenset({"context", "app", "use", "t", "run_task", "request", "provide", "inject"})

PURE: frozenset[Any] = frozenset(
    {len, str, int, float, bool, abs, round, min, max, sum, sorted, list, tuple, dict, range, enumerate, zip, any, all}
)


def is_template_function(fn: Any) -> bool:
    if fn is h:
        return True
    module = getattr(fn, "__module__", "") or ""
    return isinstance(fn, FunctionType) and module.startswith("rational.components")


def is_user_function(fn: Any) -> bool:
    module = getattr(fn, "__module__", "") or ""
    return isinstance(fn, FunctionType) and not module.startswith("rational") and not stdlib(module)


def stdlib(module: str) -> bool:
    return module.split(".")[0] in {"asyncio", "math", "random", "time", "builtins", "json", "typing", "enum"}


def callable_name(fn: Any) -> str:
    return getattr(fn, "__name__", repr(fn))


def is_op(fn: Any) -> bool:
    return getattr(fn, "__qualname__", "").startswith("js.")
