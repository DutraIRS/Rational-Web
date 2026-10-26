"""The Python-to-JavaScript compiler for client components.

What the compiled code computes is checked against Python in a real browser
(tests/browser/test_client_components.py); here, every construct compiles, the output is valid JavaScript
(checked with Node when it is installed) and unsupported code is reported precisely.
"""

import asyncio
import shutil
import subprocess
from collections.abc import Callable

import pytest

from rational import Button, Column, Input, Row, State, Style, Text, h, js
from rational.client import ClientCompileError, ClientComponent, compile_component
from rational.client.templates import HandlerRef, Hole, HoleError, TraceFrame, placeholder, string_js, tracing
from rational.styling.compiler import StyleCompiler
from tests.clientapp import Counter, Echo, Item, Semantics, TodoList, Todos, make_app

BOLD = Style(font_weight=700)


def describe(words):
    """A module-level helper: compiled to JavaScript too."""
    return ", ".join(sorted(words))


class Kitchen(ClientComponent):
    """Touches every statement and expression kind the compiler supports."""

    title: str = "Kitchen"
    on_pick: Callable[[str], None] | None = None
    rows = State(factory=lambda: [{"name": "a", "n": 1}, {"name": "b", "n": 9}])
    counter = State(0)
    note = State("")
    flag = State(False)

    def mount(self):
        self.counter = len(self.rows)

    def hydrated(self):
        self.run_js(js.focus("#note"))

    def write(self, value: str):
        self.note = value

    def pick(self, name: str):
        if self.on_pick is not None:
            self.on_pick(name)
        self.navigate("/picked")

    async def work(self):
        total, i = 0, 0
        while i < 3:
            i += 1
            if i == 2:
                continue
            total += i
        for row in self.rows:
            if row["n"] > 5:
                break
        try:
            reply = await self.remote(Todos.add, title=self.note)
            self.note = reply["title"]
        except (ValueError, KeyError) as e:
            self.note = e.message
        except Exception:
            raise
        finally:
            self.flag = not self.flag
        a, b = 1, 2
        a, b = b, a
        data = {"x": a, **{"y": b}}
        del data["x"]
        data["z"] = [n * 2 for n in range(3)]
        data["z"][0] += 5
        self.counter += total
        assert self.counter >= 0, "never negative"
        self.touch()
        nums = [3, 1, 2]
        top = max(nums, key=lambda v: -v, default=0)
        low = min(4, 5)
        names = [r["name"].upper() for r in self.rows if r["name"] not in ("x", "y")]
        merged = dict(a=1, b=2)
        parts = self.note.split(maxsplit=1)
        ok = 0 <= self.counter < 10 and isinstance(self.counter, int) and self.note is not None
        squares = {n: n * n for n in nums if n % 2}
        self.note = f"{describe(names)} {top} {low} {merged} {parts} {ok!r} {self.counter:>4} {squares}"
        await asyncio.sleep(0.01)
        if not ok:
            raise ValueError("bad")

    def render(self):
        rows = [
            Row(Text(r["name"]), Button("Pick", on_click=lambda name=r["name"]: self.pick(name)), key=r["name"])
            for r in self.rows
        ]
        return Column(
            h("h2", self.title, id="title"),
            Input("Note", value=self.note, on_input=self.write),
            *rows,
            Item(title="nested", on_remove=self.pick, key="k"),
            Text("on" if self.flag else "off", style=BOLD if self.flag else None),
            Button("Work", on_click=[js.confirm("Sure?"), self.work]),
            h("a", "Link", href=f"/items/{self.counter}"),
            self.children,
        )


@pytest.fixture(scope="module")
def app():
    return make_app()  # registers the Todos service, so self.remote(Todos.add) resolves


@pytest.mark.parametrize("cls", [Kitchen, Counter, Echo, Semantics, TodoList, Item])
def test_every_construct_compiles_to_valid_javascript(app, cls, tmp_path):
    module = app.client_module(cls)
    assert module is not None and module.js.startswith('"use strict";\nrational.island(')
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is not installed: the syntax check needs it")
    path = tmp_path / "module.js"
    path.write_text(module.js, encoding="utf-8")
    check = subprocess.run([node, "--check", str(path)], capture_output=True, text=True, check=False)
    assert check.returncode == 0, check.stderr + "\n" + module.js


def test_the_kitchen_sink_compiles_what_it_should(app):
    code = app.client_module(Kitchen).js
    assert "$rt.remote(" in code and "$rt.sleep($c, 0.01)" in code  # remote calls and asyncio.sleep
    assert "$rt.url(" in code  # a URL attribute built from state is checked in the browser
    assert '"data-rw-js-click": "[[\\"confirm\\",null,\\"Sure?\\"]]"' in code  # js.* operations stay data
    assert '$rt.island($c, "tests.clientapp.Item"' in code and "$f0_describe($c" in code
    assert app.client_module(Kitchen).children == (Item,)


# -- unsupported code -----------------------------------------------------------------------------------


def for_else(self):
    for _x in self.rows:
        pass
    else:
        return Text("none")


def class_inside(self):
    class Local:
        pass

    return Text("x")


def star_lambda(self):
    return Button("x", on_click=lambda *a: None)


def slice_assignment(self):
    self.rows[1:2] = []
    return Text("x")


def system_exit(self):
    raise SystemExit("bye")


def odd_except(self):
    try:
        return Text("x")
    except OSError:
        return Text("y")


def bare_self(self):
    me = self
    return Text(me)


def unknown_method(self):
    return Text(self.nope())


def unknown_value_method(self):
    return Text(self.note.frobnicate())


def print_keywords(self):
    print("x", sep="")
    return Text("x")


def isinstance_set(self):
    return Text(str(isinstance(self.note, set)))


def loop_variable_reused(self):
    for row in self.rows:  # noqa: B007 - the point: the name is reused below
        pass
    row = 1
    return Text(row)


def unknown_prop(self):
    return Item(title="a", colour="red")


def missing_prop(self):
    return Item()


def splat_props(self):
    return Item(**{"title": "a"})


def match_statement(self):
    match self.note:
        case "a":
            return Text("a")
    return Text("b")


def delete_attribute(self):
    del self.note
    return Text("x")


def dynamic_tag(self):
    return h(self.note)


def dynamic_markup(self):
    from rational import unsafe_html

    return unsafe_html(self.note)


@pytest.mark.parametrize(
    ("render", "message"),
    [
        (for_else, "for ... else is not supported"),
        (class_inside, "ClassDef statements are not supported"),
        (star_lambda, "lambdas in client code take plain positional parameters only"),
        (slice_assignment, "slice assignment is not supported"),
        (system_exit, "client code can raise"),
        (odd_except, "client code can catch"),
        (bare_self, "self can only be used for its attributes and methods"),
        (unknown_method, "has no method nope()"),
        (unknown_value_method, ".frobnicate() is not available"),
        (print_keywords, "print() keyword arguments are not supported"),
        (isinstance_set, "isinstance() in client code checks"),
        (loop_variable_reused, "a for-loop variable cannot also be assigned elsewhere"),
        (unknown_prop, "Item has no prop 'colour'"),
        (missing_prop, "Item() is missing required prop(s): title"),
        (splat_props, "**props are not supported"),
        (match_statement, "Match statements are not supported"),
        (delete_attribute, "del works on items"),
        (dynamic_tag, "h() needs to know `self.note`"),
        (dynamic_markup, "ImportFrom statements are not supported"),
    ],
)
def test_unsupported_code_is_reported_with_its_location(render, message):
    component = type("Broken", (ClientComponent,), {"note": State(""), "rows": State(factory=list), "render": render})
    with pytest.raises(ClientCompileError) as info:
        compile_component(component, StyleCompiler("modern"), lambda _cls: None)
    text = str(info.value)
    assert message in text, text
    assert f'File "{render.__code__.co_filename}", line' in text and f"in Broken.{render.__name__}" in text


def test_a_component_needs_a_render_method():
    with pytest.raises(ClientCompileError, match="has no render"):
        compile_component(type("Empty", (ClientComponent,), {}), StyleCompiler("modern"), lambda _cls: None)


# -- tracing primitives -----------------------------------------------------------------------------------


def test_holes_refuse_inspection_but_compare_symbolically():
    hole = Hole("$h1", "self.kind")
    assert (hole == "primary").js == '$rt.eq($h1, "primary")'
    assert (hole != hole).js == "!$rt.eq($h1, $h1)"
    for inspect in (
        bool,
        hash,
        len,
        iter,
        abs,
        int,
        lambda x: x + 1,
        lambda x: 1 - x,
        lambda x: x | 1,
        lambda x: x.strip,
    ):
        with pytest.raises(HoleError):
            inspect(hole)
    with pytest.raises(AttributeError):
        hole.__wrapped__  # noqa: B018 - dunder lookups stay plain AttributeErrors (hasattr works)
    assert repr(hole) == "<browser value self.kind>"


def test_text_built_from_a_hole_becomes_javascript():
    names = iter(range(100))
    frame = TraceFrame(lambda kind: f"${kind}{next(names)}")
    hole = Hole("$h1", "self.name")
    with tracing(frame):
        text = f"Hello {hole}! {hole:>5}"
        element_id = frame.next_dom_id("Your Name")
    assert string_js(text, frame) == '("Hello " + $rt.str($h1) + "! " + $rt.fmt($h1, ">5"))'
    assert frame.steps == ['$d0 = $rt.id($c, "your-name")'] and string_js(element_id, frame) == "('' + $d0)"
    assert string_js("plain", None) == '"plain"'
    with pytest.raises(TypeError, match="outside a client component"):
        placeholder("$x")
    with pytest.raises(ValueError, match="mangled"):
        string_js(text.replace("", "", 1), frame)
    with pytest.raises(TypeError, match="was called"):
        HandlerRef("f")()
