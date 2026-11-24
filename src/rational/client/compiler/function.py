"""One method or helper function, compiled to a JavaScript function declaration."""

from __future__ import annotations

import ast

from .base import js_name
from .calls import Calls
from .expressions import Expressions
from .markup import Markup
from .source import bound_names, loop_targets
from .statements import Statements


class FunctionCompiler(Statements, Expressions, Calls, Markup):
    """Compiles one method or helper function to a JavaScript function declaration."""

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
        self.local_names = bound_names(self.node) | self.params
        self.loop_names = loop_targets(self.node)
        clash = self.loop_names & (self.local_names - self.params)
        if clash:
            raise self.error(
                self.node, f"{', '.join(sorted(clash))}: a for-loop variable cannot also be assigned elsewhere"
            )
        if self.loop_names & self.params:
            raise self.error(self.node, "a for-loop variable cannot reuse a parameter's name")
        js_params = ["$c"]
        for name, default in zip(params, defaults, strict=True):
            js_params.append(js_name(name) + ("" if default is None else f" = {self.constant(default)}"))
        body = self.node.body
        if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
            body = body[1:]  # docstring
        self.block(body)
        hoisted = sorted(self.local_names - self.params - self.loop_names)
        declared = [js_name(n) for n in hoisted] + self.temps[0]
        head = f"{'async ' if self.is_async else ''}function {self.js_name}({', '.join(js_params)}) {{"
        decl = [f"  let {', '.join(declared)};"] if declared else []
        return "\n".join([head, *decl, *self.lines, "}"])
