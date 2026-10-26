"""Client components: compiled to JavaScript, rendered first by the server.

What runs in the browser is covered by tests/browser/test_client_components.py (including a check that
the compiled code computes exactly what Python does); these tests cover the server side and the
compiler's errors.
"""

import asyncio
import json
import re

import pytest

from rational import App, Button, Column, Component, Page, RemoteError, State, Style, Text, h
from rational.backend import Service, remote
from rational.client import ClientCompileError, ClientComponent, compile_component
from rational.diff import diff
from rational.rendering.nodes import Node
from rational.styling.compiler import StyleCompiler
from rational.testing import TestClient


class Counter(ClientComponent):
    start: int = 0
    count = State(0)

    def mount(self):
        self.count = self.start

    def inc(self):
        self.count += 1

    def render(self):
        return Button(f"Count: {self.count}", on_click=self.inc)


class Wrapper(ClientComponent):
    def render(self):
        return Column(Text("around"), self.children)


class Clicks(Component):
    clicks = State(0)

    def click(self):
        self.clicks += 1

    def render(self):
        return Button(f"Clicks: {self.clicks}", on_click=self.click)


def compiled(cls):
    return compile_component(cls, StyleCompiler("modern"), lambda _cls: None)


def page_app(render):
    app = App()

    @app.page("/")
    class Home(Page):
        def render(self):
            return render()

    return app


def manifest_of(html):
    return json.loads(re.search(r'id="rw-manifest">(.*?)</script>', html).group(1))


# -- the first render -------------------------------------------------------------------------------


def test_the_server_renders_the_first_html():
    app = page_app(lambda: Counter(start=3))
    response = TestClient(app).http.get("/")
    html = response.text
    module = app.client_module(Counter)

    assert '<rw-island data-rw-island="tests.test_client_components.Counter"' in html
    assert 'data-rw-props="{&quot;start&quot;:3}"' in html and "&quot;count&quot;:3" in html
    assert "Count: 3" in html and "data-rw-on-click" not in html  # no server handler: it runs in the browser
    assert f'src="{app.islands_src}"' in html and f'src="{module.path}"' in html
    assert "page" not in manifest_of(html)  # no server-side view to talk to
    assert "set-cookie" not in response.headers and response.headers["cache-control"] == "no-store"


def test_compiled_modules_are_served_with_long_caching():
    app = page_app(lambda: Counter())
    client = TestClient(app)
    client.http.get("/")
    module = app.client_module(Counter)
    response = client.http.get(module.path)
    assert response.status_code == 200 and response.text == module.js
    assert "immutable" in response.headers["cache-control"]
    assert response.headers["content-type"].startswith("text/javascript")
    assert client.http.get("/_rational/c/unknown.js").status_code == 404
    assert client.http.get(app.islands_src).status_code == 200


def test_compiling_is_deterministic():
    first, second = compiled(Counter), compiled(Counter)
    assert first.js == second.js and first.digest == second.digest
    assert 'rational.island("tests.test_client_components.Counter"' in first.js


def test_children_stay_on_the_server_in_a_slot():
    app = page_app(lambda: Wrapper(Clicks()))
    client = TestClient(app)
    view = client.open("/")
    assert "<rw-slot>" in view.html and "around" in view.text
    view.click("Clicks: 0")  # a server component inside a client component keeps its server events
    assert "Clicks: 1" in view.text


def test_a_client_component_added_by_an_event_loads_its_scripts():
    class Toggle(Component):
        shown = State(False)

        def show(self):
            self.shown = True

        def render(self):
            return Column(Button("Show", on_click=self.show), Counter() if self.shown else None)

    app = page_app(Toggle)
    view = TestClient(app).open("/")
    data = view.click("Show")
    module = app.client_module(Counter)
    assert data["load"] == [app.islands_src, module.path]
    assert "Count: 0" in view.text


def test_server_patches_send_islands_whole():
    old = Node("rw-island", attrs=(("data-rw-props", "{}"),), children=(Node("p"),))
    new = Node("rw-island", attrs=(("data-rw-props", '{"a":1}'),), children=(Node("p"),))
    edits = diff(Node("div", children=(old,)), Node("div", children=(new,)))
    assert edits is not None and [e[0] for e in edits] == ["h"]


def test_props_and_state_must_be_json():
    app = page_app(lambda: Counter(start=object()))
    with pytest.raises(TypeError, match="props must be JSON"):
        TestClient(app).http.get("/")

    with pytest.raises(TypeError, match="scope='component'"):

        class Shared(ClientComponent):
            n = State(0, scope="session")

            def render(self):
                return Text("x")

    class Odd(ClientComponent):
        n = State(factory=set)

        def render(self):
            return Text("x")

    with pytest.raises(ClientCompileError, match="JSON data"):
        compiled(Odd)


# -- remote calls on the server ---------------------------------------------------------------------


class Greetings(Service):
    @remote()
    def greet(self, name: str) -> dict:
        return {"text": f"Hello, {name}"}

    @remote(auth="required")
    def secret(self) -> str:
        return "s3cret"


class Greeter(ClientComponent):
    text = State("")

    async def mount(self):
        reply = await self.remote(Greetings.greet, name="Ada")
        try:
            await self.remote(Greetings.secret)
        except RemoteError as e:
            self.text = f"{reply['text']} / {e.message}"

    def render(self):
        return Text(self.text)


def test_remote_calls_during_the_first_render_go_straight_to_the_service():
    app = page_app(Greeter)
    app.service(Greetings)
    html = TestClient(app).http.get("/").text
    assert "Hello, Ada / Please sign in" in html
    js = app.client_module(Greeter).js
    assert '"service": "greetings", "method": "greet", "verb": "POST"' in js


# -- compile errors -----------------------------------------------------------------------------------


def unsupported_with(self):
    with open("x") as f:
        return f


def server_component(self):
    return Clicks()


def server_context(self):
    return Text(self.context.user)


def inspected_value(self):
    return Button("Go", variant=self.kind)


def prop_assignment(self):
    self.label = "changed"
    return Text("x")


def dynamic_style(self):
    return h("div", style=Style(width=self.kind))


async def await_in_comprehension(self):
    return Column(*[await self.remote(Greetings.greet, name=n) for n in ["a", "b"]])


def undefined_name(self):
    return Text(nope)  # noqa: F821


@pytest.mark.parametrize(
    ("render", "message"),
    [
        (unsupported_with, "With statements are not supported"),
        (server_component, "Clicks is a server component"),
        (server_context, "self.context is only available on the server"),
        (inspected_value, "Button() needs to know `self.kind`"),
        (prop_assignment, "label is a prop; props are read-only"),
        (dynamic_style, "style"),
        (await_in_comprehension, "await is only allowed"),
        (undefined_name, "name 'nope' is not defined"),
    ],
)
def test_compile_errors_say_what_and_where(render, message):
    component = type(
        "Broken",
        (ClientComponent,),
        {"__annotations__": {"label": "str"}, "label": "x", "kind": State("primary"), "render": render},
    )
    with pytest.raises(ClientCompileError) as info:
        compiled(component)
    text = str(info.value)
    assert message in text, text
    assert f'File "{render.__code__.co_filename}", line' in text and f"in Broken.{render.__name__}" in text


def test_a_component_created_in_the_browser_must_be_able_to_mount_there():
    class NeedsServer(ClientComponent):
        def mount(self):
            _ = self.context.user

        def render(self):
            return Text("child")

    class Parent(ClientComponent):
        def render(self):
            return Column(NeedsServer())

    app = App()
    with pytest.raises(ClientCompileError, match="created in the browser here, but its mount"):
        app.client_module(Parent)
    assert "only available on the server" in app.client_module(NeedsServer).mount_error


# -- static export --------------------------------------------------------------------------------------


def test_pages_with_only_client_components_can_be_exported(tmp_path):
    from rational.export import export_site

    app = page_app(lambda: Counter(start=1))
    report = asyncio.run(export_site(app, tmp_path))
    module = app.client_module(Counter)
    assert report.pages == ["/"]
    assert (tmp_path / "_rational" / "islands.js").exists() and (tmp_path / "_rational" / "runtime.js").exists()
    assert (tmp_path / module.path.lstrip("/")).read_text(encoding="utf-8") == module.js
    assert "Count: 1" in (tmp_path / "index.html").read_text(encoding="utf-8")
