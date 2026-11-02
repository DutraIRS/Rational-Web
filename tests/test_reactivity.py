"""Derived state (computed), reactions (watch), two-way binding (bind) and provide/inject."""

import functools

import pytest
from pydantic import BaseModel

from rational import App, Button, Checkbox, Column, Component, Input, Page, Select, State, Text, computed, watch
from rational.binding import bind_payload
from rational.testing import TestClient


def serve(root):
    app = App()

    @app.page("/")
    class Home(Page):
        def render(self):
            return root()

    return TestClient(app).open("/")


class Cart(Component):
    prices = State(factory=lambda: [3, 4])
    runs = 0

    @computed
    def total(self) -> int:
        type(self).runs += 1
        return sum(self.prices)

    def add(self):
        self.prices = [*self.prices, 10]

    def render(self):
        return Column(Text(f"Total: {self.total}"), Text(f"Again: {self.total}"), Button("Add", on_click=self.add))


def test_computed_values_are_cached_until_their_state_changes():
    Cart.runs = 0
    view = serve(Cart)
    assert "Total: 7" in view.text and "Again: 7" in view.text and Cart.runs == 1
    view.click("Add")
    assert "Total: 17" in view.text and Cart.runs == 2


class Summary(Component):
    cart: Cart

    def render(self):
        return Text(f"Summary: {self.cart.total}")


class Shop(Component):
    def mount(self):
        self.cart = Cart()

    def render(self):
        return Column(self.cart, Summary(cart=self.cart))


def test_a_cached_value_still_makes_its_readers_depend_on_its_state():
    view = serve(Shop)
    assert "Summary: 7" in view.text
    view.click("Add")  # Summary read `total` from the cache, so it must still re-render
    assert "Summary: 17" in view.text


class Search(Component):
    query = State("")
    count = State(0)
    log = State(factory=list)

    def mount(self):
        self.query = "start"  # values set while mounting are the starting point, not changes

    @watch("query")
    async def searched(self, new, old):
        self.log = [*self.log, f"{old}->{new}"]
        self.count = len(new)

    @watch("count")
    def counted(self):
        self.log = [*self.log, "counted"]

    def type_twice(self):
        self.query = "a"
        self.query = "abc"

    def render(self):
        return Column(Text(f"Log: {self.log} / {self.count}"), Button("Type", on_click=self.type_twice))


def test_watchers_run_after_changes_batched_and_chained():
    view = serve(Search)
    assert "Log: [] / 0" in view.text
    view.click("Type")
    assert "Log: ['start->abc', 'counted'] / 3" in view.text


def test_watch_needs_a_state_attribute():
    with pytest.raises(TypeError, match="needs a State attribute"):

        class Broken(Component):
            @watch("missing")
            def nope(self): ...

            def render(self):
                return Text("x")


class Profile(Component):
    name = State("Ada")
    age = State(36)
    admin = State(False)
    plan = State("free")

    def render(self):
        return Column(
            Input("Name", bind=self.bind("name")),
            Input("Age", type="number", bind=self.bind("age")),
            Checkbox("Admin", bind=self.bind("admin")),
            Select("Plan", ["free", "pro"], bind=self.bind("plan")),
            Text(f"{self.name} {self.age!r} {self.admin} {self.plan}"),
        )


def test_bind_shows_and_stores_typed_values():
    view = serve(Profile)
    assert view.field("Name").get("value") == "Ada" and view.field("Age").get("value") == "36"
    view.input("Name", "Grace")
    view.input("Age", "41")
    view.input("Age", "4x")  # not a number (yet): ignored
    view.input("Admin", True, event="change")
    view.input("Plan", "pro", event="change")
    assert "Grace 41 True pro" in view.text


def test_bind_needs_state_and_excludes_a_handler():
    class Plain(Component):
        label = "x"

        def render(self):
            return Input("X", bind=self.bind("label"))

    with pytest.raises(AttributeError, match="not a State attribute"):
        serve(Plain)

    class Both(Component):
        v = State("")

        def render(self):
            return Input("X", bind=self.bind("v"), on_input=lambda value: None)

    with pytest.raises(TypeError, match="bind= or on_input="):
        serve(Both)


class ThemeLeaf(Component):
    def render(self):
        return Text(f"Theme: {self.inject('theme')} / {self.inject('missing', 'none')}")


class ThemeMiddle(Component):
    def render(self):
        return ThemeLeaf()


class ThemeRoot(Component):
    def mount(self):
        self.provide("theme", "dark")

    def render(self):
        return ThemeMiddle()


def test_provided_values_reach_every_descendant():
    assert "Theme: dark / none" in serve(ThemeRoot).text

    class Orphan(Component):
        def render(self):
            return Text(self.inject("theme"))

    with pytest.raises(LookupError, match="provides 'theme'"):
        serve(Orphan)


def test_view_transitions_are_opt_in():
    import json
    import re

    assert "@view-transition" not in App().theme_css
    app = App(view_transitions=True, client_nav=True)

    @app.page("/")
    class Home(Page):
        def render(self):
            return Text("x")

    html = TestClient(app).http.get("/").text
    manifest = json.loads(re.search(r'id="rw-manifest">(.*?)</script>', html).group(1))
    assert manifest["transitions"] is True and "@view-transition{navigation:auto}" in app.theme_css


def test_a_failing_unmount_is_logged_and_the_rest_still_unmount(caplog):
    unmounted = []

    class Bad(Component):
        def unmount(self):
            raise ValueError("no")

        def render(self):
            return Text("bad")

    class Good(Component):
        def unmount(self):
            unmounted.append(True)

        def render(self):
            return Text("good")

    app = App()

    @app.page("/")
    class Home(Page):
        def render(self):
            return Column(Bad(), Good())

    TestClient(app).http.get("/")
    assert unmounted == [True] and "error in Bad.unmount" in caplog.text


def test_unmount_cannot_be_async():
    with pytest.raises(TypeError, match="cannot be async"):

        class Bad(Component):
            async def unmount(self):
                pass


def test_computed_values_survive_changes_on_other_pages():
    calls = []

    class Shows(Component):
        n = State(1)

        @computed
        def double(self):
            calls.append(self)
            return self.n * 2

        def inc(self):
            self.n += 1

        def render(self):
            return Column(Text(f"{self.double} {self.double}"), Button("Inc", on_click=self.inc))

    app = App()

    @app.page("/")
    class Home(Page):
        def render(self):
            return Shows()

    client = TestClient(app)
    one = client.open("/")
    assert len(calls) == 1  # read twice, calculated once
    runtime = app.pages.get(one.manifest["page"])
    shows = next(c for c in runtime.components.values() if isinstance(c, Shows))
    assert shows.double == 2  # the page's session started after its render, which counts as a change
    before = calls.count(shows)
    client.open("/").click("Inc")
    assert shows.double == 2 and calls.count(shows) == before  # another page's change is not this page's


def test_computed_values_follow_state_props_and_session_data():
    class Child(Component):
        label: str = "a"

        @computed
        def shout(self):
            return self.label.upper()

        def render(self):
            return Text(self.shout)

    class Shows(Component):
        label = State("a")

        @computed
        def visits(self):
            return self.context.session.get("visits", 0)

        def visit(self):
            self.context.session["visits"] = self.visits + 1

        def rename(self):
            self.label = "b"

        def render(self):
            return Column(
                Text(f"visits={self.visits}"),
                Child(label=self.label),
                Button("Visit", on_click=self.visit),
                Button("Rename", on_click=self.rename),
            )

    app = App()

    @app.page("/")
    class Home(Page):
        def render(self):
            return Shows()

    view = TestClient(app).open("/")
    view.click("Visit")
    assert "visits=1" in view.text
    view.click("Rename")
    assert "B" in view.text


def test_computed_on_an_unmounted_component_calculates_every_time():
    calls = []

    class Free(Component):
        @computed
        def value(self):
            calls.append(True)
            return 1

    free = Free()
    assert free.value == free.value == 1 and len(calls) == 2


def test_wrappers_of_one_decorator_keep_their_own_annotations():
    def logged(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            return fn(*args, **kwargs)

        return wrapper

    class Form1(BaseModel):
        a: int

    class Form2(BaseModel):
        b: str

    @logged
    def first(form: Form1):
        return form

    @logged
    def second(form: Form2):
        return form

    first.__annotations__["form"], second.__annotations__["form"] = Form1, Form2
    assert isinstance(bind_payload(first, "submit", {"form": {"a": "1"}})[0], Form1)
    assert isinstance(bind_payload(second, "submit", {"form": {"b": "x"}})[0], Form2)


def test_an_annotation_that_cannot_be_resolved_is_reported(caplog):
    namespace: dict = {}
    exec("def handler(form: 'NoSuchModel'): ...", namespace)
    assert bind_payload(namespace["handler"], "submit", {"form": {"a": 1}}) == [{"a": 1}]
    assert "cannot be resolved" in caplog.text
