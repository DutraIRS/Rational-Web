"""Expressions: names, attributes, operators, comparisons, literals, f-strings, comprehensions, lambdas."""

from __future__ import annotations

import ast
import json
from collections.abc import Callable

from .base import js_name
from .core import FunctionCore
from .tables import ORDER, SERVER_ONLY


class Expressions(FunctionCore):
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

    def expr(self, node: ast.expr) -> str:
        kind = EXPRESSION_KINDS.get(type(node))
        if kind is None:
            raise self.error(node, f"{type(node).__name__} expressions are not supported in client code")
        result: str = getattr(self, kind)(node)
        return result

    def literal(self, node: ast.Constant) -> str:
        return self.value_js(node.value, node)

    def name(self, node: ast.Name) -> str:
        if self.is_local(node.id):
            return js_name(node.id)
        if self.method and node.id == "self":
            raise self.error(node, "self can only be used for its attributes and methods in client code")
        return self.static(node)

    def attribute(self, node: ast.Attribute) -> str:
        if self.is_self(node.value):
            return self.self_attribute(node)
        if self.is_static(node):
            return self.static(node)
        base = self.expr(node.value)  # reports a problem with the object itself first (self.context...)
        if node.attr in ("message", "args"):
            return f"{base}.{node.attr}"
        raise self.error(node, f'.{node.attr}: use item["{node.attr}"] for dictionaries in client code')

    def binary(self, node: ast.BinOp) -> str:
        return self.operator(node.op, node)(self.expr(node.left), self.expr(node.right))

    def unary(self, node: ast.UnaryOp) -> str:
        if isinstance(node.op, ast.Not):
            return f"!{self.condition(node.operand)}"
        symbol = {ast.USub: "-", ast.UAdd: "+", ast.Invert: "~"}[type(node.op)]
        return f"({symbol}{self.expr(node.operand)})"

    def boolean(self, node: ast.BoolOp) -> str:
        helper = "$rt.and" if isinstance(node.op, ast.And) else "$rt.or"
        out = self.expr(node.values[-1])
        for value in reversed(node.values[:-1]):
            out = f"{helper}({self.expr(value)}, () => {out})"
        return out

    def conditional(self, node: ast.IfExp) -> str:
        return f"({self.condition(node.test)} ? {self.expr(node.body)} : {self.expr(node.orelse)})"

    def subscript(self, node: ast.Subscript) -> str:
        if isinstance(node.slice, ast.Slice):
            s = node.slice
            bounds = [self.expr(b) if b is not None else "null" for b in (s.lower, s.upper, s.step)]
            return f"$rt.slice({self.expr(node.value)}, {', '.join(bounds)})"
        return f"$rt.get({self.expr(node.value)}, {self.expr(node.slice)})"

    def sequence(self, node: ast.List | ast.Tuple) -> str:
        return "[" + ", ".join(self.element(e) for e in node.elts) + "]"

    def dictionary(self, node: ast.Dict) -> str:
        items = []
        for key, value in zip(node.keys, node.values, strict=True):
            items.append(
                f"...$rt.dict({self.expr(value)})" if key is None else f"[{self.expr(key)}]: {self.expr(value)}"
            )
        return "{" + ", ".join(items) + "}"

    def list_comprehension(self, node: ast.ListComp | ast.GeneratorExp) -> str:
        return self.comprehension(node.generators, lambda: f"$out.push({self.expr(node.elt)});")

    def dict_comprehension(self, node: ast.DictComp) -> str:
        return self.comprehension(
            node.generators, lambda: f"$rt.set($out, {self.expr(node.key)}, {self.expr(node.value)});", "{}"
        )

    def await_(self, node: ast.Await) -> str:
        if not self.async_ok[-1]:
            raise self.error(
                node, "await is only allowed directly in an async method (not in a lambda or comprehension)"
            )
        return f"(await {self.expr(node.value)})"

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
        if name in SERVER_ONLY:
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
                parts.append(f"($rt.cmp({a}, {b}) {ORDER[type(op)]} 0)")
        return parts[0] if len(parts) == 1 else "(" + " && ".join(parts) + ")"

    def fstring(self, node: ast.JoinedStr) -> str:
        parts = []
        for value in node.values:
            if isinstance(value, ast.Constant):
                parts.append(json.dumps(value.value))
                continue
            if not isinstance(value, ast.FormattedValue):
                raise self.error(node, "unexpected part in an f-string")
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
            js_name(p) + ("" if d is None else f" = {self.expr(d)}") for p, d in zip(params, defaults, strict=True)
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


EXPRESSION_KINDS: dict[type[ast.expr], str] = {  # node type -> the method that compiles it
    ast.Constant: "literal",
    ast.Name: "name",
    ast.Attribute: "attribute",
    ast.Call: "call",
    ast.BinOp: "binary",
    ast.UnaryOp: "unary",
    ast.BoolOp: "boolean",
    ast.Compare: "compare",
    ast.IfExp: "conditional",
    ast.Subscript: "subscript",
    ast.List: "sequence",
    ast.Tuple: "sequence",
    ast.Dict: "dictionary",
    ast.JoinedStr: "fstring",
    ast.ListComp: "list_comprehension",
    ast.GeneratorExp: "list_comprehension",
    ast.DictComp: "dict_comprehension",
    ast.Lambda: "lambda_",
    ast.Await: "await_",
}
