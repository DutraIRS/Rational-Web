"""Reading a function: its syntax tree from the source file, its names, and the names it binds."""

from __future__ import annotations

import ast
import contextlib
import linecache
from types import FunctionType
from typing import Any

from .base import ClientCompileError

_trees: dict[str, ast.Module] = {}


def definition(fn: FunctionType) -> ast.FunctionDef | ast.AsyncFunctionDef:
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


def namespace_of(fn: FunctionType) -> dict[str, Any]:
    names = dict(fn.__globals__)
    for name, cell in zip(fn.__code__.co_freevars, fn.__closure__ or (), strict=True):
        with contextlib.suppress(ValueError):  # an empty cell: defined later in the enclosing function
            names[name] = cell.cell_contents
    return names


def bound_names(node: ast.AST) -> set[str]:
    """Names a function body assigns, outside nested lambdas and comprehensions (their own scopes) and
    outside for-loop targets (bound per iteration, see ``loop_targets``)."""
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


def loop_targets(node: ast.AST) -> set[str]:
    out: set[str] = set()
    for n in ast.walk(node):
        if isinstance(n, ast.For):
            out.update(t.id for t in ast.walk(n.target) if isinstance(t, ast.Name))
    return out
