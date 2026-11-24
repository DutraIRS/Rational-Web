"""Statements: assignments, control flow, exceptions."""

from __future__ import annotations

import ast
import json

from .base import js_name
from .core import FunctionCore
from .tables import EXCEPTIONS


class Statements(FunctionCore):
    def statement(self, node: ast.stmt) -> None:
        kind = STATEMENT_KINDS.get(type(node))
        if kind is None:
            raise self.error(node, f"{type(node).__name__} statements are not supported in client code")
        getattr(self, kind)(node)

    def expression_statement(self, node: ast.Expr) -> None:
        if not isinstance(node.value, ast.Constant):  # a bare string is a comment
            self.emit(f"{self.expr(node.value)};")

    def return_(self, node: ast.Return) -> None:
        self.emit("return null;" if node.value is None else f"return {self.expr(node.value)};")

    def assignment(self, node: ast.Assign) -> None:
        value = self.expr(node.value)
        if len(node.targets) > 1:
            tmp = self.temp("v")
            self.emit(f"{tmp} = {value};")
            value = tmp
        for target in node.targets:
            self.assign(target, value)

    def annotated(self, node: ast.AnnAssign) -> None:
        if node.value is not None:
            self.assign(node.target, self.expr(node.value))

    def if_(self, node: ast.If) -> None:
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

    def for_(self, node: ast.For) -> None:
        if node.orelse:
            raise self.error(node, "for ... else is not supported in client code")
        names = {t.id for t in ast.walk(node.target) if isinstance(t, ast.Name)}
        self.emit(f"for (let {self.binding(node.target)} of $rt.iter({self.expr(node.iter)})) {{")
        self.loops.append(names)
        self.indented(node.body)
        self.loops.pop()
        self.emit("}")

    def while_(self, node: ast.While) -> None:
        if node.orelse:
            raise self.error(node, "while ... else is not supported in client code")
        self.emit(f"while ({self.condition(node.test)}) {{")
        self.indented(node.body)
        self.emit("}")

    def break_(self, node: ast.Break) -> None:
        self.emit("break;")

    def continue_(self, node: ast.Continue) -> None:
        self.emit("continue;")

    def pass_(self, node: ast.Pass) -> None:
        """Nothing to emit."""

    def assert_(self, node: ast.Assert) -> None:
        message = "null" if node.msg is None else self.expr(node.msg)
        self.emit(f'if (!{self.condition(node.test)}) throw $rt.error("AssertionError", {message});')

    def delete(self, node: ast.Delete) -> None:
        for target in node.targets:
            if not isinstance(target, ast.Subscript) or isinstance(target.slice, ast.Slice):
                raise self.error(node, "del works on items (del d[key], del items[i]) in client code")
            self.emit(f"$rt.del({self.expr(target.value)}, {self.expr(target.slice)});")

    def assign(self, target: ast.expr, value: str) -> None:
        if isinstance(target, ast.Name):
            if target.id in self.loop_names:
                raise self.error(target, f"{target.id} is a for-loop variable; assign to another name")
            self.emit(f"{js_name(target.id)} = {value};")
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
            name = js_name(target.id)
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

    def raise_(self, node: ast.Raise) -> None:
        if node.exc is None:
            self.emit(
                "throw $e;"
                if any("$e" in line for line in self.lines)
                else 'throw $rt.error("RuntimeError", "no active exception");'
            )
            return
        exc = node.exc
        if isinstance(exc, ast.Call) and isinstance(exc.func, ast.Name) and exc.func.id in EXCEPTIONS:
            message = self.expr(exc.args[0]) if exc.args else '""'
            self.emit(f"throw $rt.error({json.dumps(exc.func.id)}, {message});")
        elif isinstance(exc, ast.Name) and exc.id in EXCEPTIONS:
            self.emit(f'throw $rt.error({json.dumps(exc.id)}, "");')
        elif isinstance(exc, ast.Name):
            self.emit(f"throw {self.expr(exc)};")
        else:
            raise self.error(node, f"client code can raise {', '.join(sorted(EXCEPTIONS))} (with a message)")

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
                    self.emit(f"{js_name(handler.name)} = $e;")
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
            if not (isinstance(n, ast.Name) and n.id in EXCEPTIONS):
                raise self.error(handler, f"client code can catch {', '.join(sorted(EXCEPTIONS))}")
            if n.id == "Exception":
                return None
            out.append(n.id)
        return out


STATEMENT_KINDS: dict[type[ast.stmt], str] = {  # node type -> the method that compiles it
    ast.Expr: "expression_statement",
    ast.Return: "return_",
    ast.Assign: "assignment",
    ast.AnnAssign: "annotated",
    ast.AugAssign: "augmented",
    ast.If: "if_",
    ast.For: "for_",
    ast.While: "while_",
    ast.Break: "break_",
    ast.Continue: "continue_",
    ast.Pass: "pass_",
    ast.Raise: "raise_",
    ast.Try: "try_",
    ast.Assert: "assert_",
    ast.Delete: "delete",
}
