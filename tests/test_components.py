import json

import pytest
from pydantic import BaseModel

from rational import (
    App,
    Button,
    Column,
    Component,
    Event,
    Form,
    Input,
    Page,
    State,
    Style,
    Text,
    js,
)
from rational.testing import TestClient


class Counter(Component):
    label: str = "Count"
    count = State(0)
    renders = 0

    def increment(self):
        self.count += 1

    def render(self):
        Counter.renders += 1
        return Column(Text(f"{self.label}: {self.count}"), Button(f"+ {self.label}", on_click=self.increment))


def make_app(page_cls, path="/", **options):
    app = App(**options)
    app.page(path)(page_cls)
    return app


def test_props_required_unknown_and_defaults():
    class Greeting(Component):
        name: str
        excited: bool = False
        tags: list = []

        def render(self):
            return Text(self.name)

    g = Greeting(name="Ada")
    assert g.excited is False and g.tags == [] and g.tags is not Greeting(name="b").tags
    with pytest.raises(TypeError, match="missing required prop 'name'"):
        Greeting()
    with pytest.raises(TypeError, match="unexpected props: nmae"):
        Greeting(name="x", nmae="y")


def test_state_is_per_instance_and_only_the_owner_rerenders():
    class Home(Page):
        def render(self):
            return Column(Counter(label="A"), Counter(label="B"))

    page = TestClient(make_app(Home)).open("/")
    assert "A: 0" in page.text and "B: 0" in page.text
    Counter.renders = 0
    data = page.click("+ A")
    assert [p["id"] for p in data["patches"]] == ["c1"]
    assert Counter.renders == 1
    assert "A: 1" in page.text and "B: 0" in page.text


def test_component_style_merges_into_root_element():
    class Home(Page):
        def render(self):
            return Counter(style=Style(padding=16))

    page = TestClient(make_app(Home)).open("/")
    root = page.dom.find_all(data_rw_c="c1")[0]
    assert root.tag == "div" and "padding:16px" in page.html


def test_multi_root_components_get_a_wrapper():
    class Pair(Component):
        def render(self):
            return [Text("one"), Text("two")]

    class Home(Page):
        def render(self):
            return Pair()

    page = TestClient(make_app(Home)).open("/")
    wrappers = [div for div in page.dom.find_all("div") if [c.tag for c in div.children] == ["p", "p"]]
    assert len(wrappers) == 1


def test_identity_is_preserved_across_parent_rerenders_with_keys():
    class Home(Page):
        order = State(["x", "y"])

        def flip(self):
            self.order = list(reversed(self.order))

        def render(self):
            return Column(Button("flip", on_click=self.flip), *[Counter(label=k, key=k) for k in self.order])

    page = TestClient(make_app(Home)).open("/")
    page.click("+ y")
    page.click("+ y")
    page.click("flip")
    text = page.text
    assert text.index("y: 2") < text.index("x: 0")
    page.click("+ x")
    assert "x: 1" in page.text and "y: 2" in page.text


def test_removed_components_are_unmounted_and_their_handlers_dropped():
    unmounted = []

    class Child(Counter):
        def unmount(self):
            unmounted.append(self.label)

    class Home(Page):
        show = State(True)

        def hide(self):
            self.show = False

        def render(self):
            return Column(Button("hide", on_click=self.hide), Child(label="c") if self.show else None)

    page = TestClient(make_app(Home)).open("/")
    stale_handler = page.find("+ c", "click").attrs["data-rw-on-click"]
    page.click("hide")
    assert unmounted == ["c"] and "c: 0" not in page.text
    data = page.fire(stale_handler, {})
    assert data["error"]["code"] == "stale"
    assert data["patches"], "a stale event resyncs the page"


def test_class_change_at_same_position_remounts():
    class Other(Component):
        def render(self):
            return Text("other")

    class Home(Page):
        swap = State(False)

        def toggle(self):
            self.swap = True

        def render(self):
            return Column(Button("swap", on_click=self.toggle), Other() if self.swap else Counter())

    page = TestClient(make_app(Home)).open("/")
    page.click("swap")
    assert "other" in page.text


def test_handler_payload_binding_and_validation():
    received = []

    class Signup(BaseModel):
        email: str
        age: int

    class Home(Page):
        def on_age(self, value: int):
            received.append(value)

        def on_any(self, event: Event):
            received.append((event.name, event.value))

        def on_submit(self, form: Signup):
            received.append(form)

        def render(self):
            return Column(
                Input("Age", on_change=self.on_age),
                Input("Free", on_input=self.on_any),
                Form(Input("Email"), Input("Age", name="age"), Button("Join", type="submit"), on_submit=self.on_submit),
            )

    page = TestClient(make_app(Home)).open("/")
    page.input("Age", "42", event="change")
    page.input("Free", "hi")
    page.submit({"email": "a@b.c", "age": "7"})
    assert received == [42, ("input", "hi"), Signup(email="a@b.c", age=7)]

    data = page.submit({"email": "a@b.c", "age": "old"})
    assert data["error"]["code"] == "validation_error"
    assert data["error"]["details"][0]["field"] == "age"
    data = page.input("Age", "x", event="change")
    assert data["error"]["code"] == "validation_error"


def test_lambda_handlers_capture_server_side_values():
    deleted = []

    class Home(Page):
        def render(self):
            return Column(*[Button(f"delete {i}", on_click=lambda i=i: deleted.append(i)) for i in range(3)])

    page = TestClient(make_app(Home)).open("/")
    page.click("delete 2")
    page.click("delete 0")
    assert deleted == [2, 0]


def test_page_scope_state_is_shared_by_instances_on_one_page():
    class Shared(Component):
        n = State(0, scope="page")

        def bump(self):
            self.n += 1

        def render(self):
            return Button(f"shared {self.key} {self.n}", on_click=self.bump)

    class Home(Page):
        def render(self):
            return Column(Shared(key="a"), Shared(key="b"))

    client = TestClient(make_app(Home))
    page = client.open("/")
    page.click("shared a")
    assert "shared a 1" in page.text and "shared b 1" in page.text
    assert "shared a 0" in client.open("/").text


def test_session_scope_state_spans_tabs():
    class Cart(Component):
        items = State(0, scope="session")

        def add(self):
            self.items += 1

        def render(self):
            return Button(f"cart {self.items}", on_click=self.add)

    class Home(Page):
        def render(self):
            return Cart()

    client = TestClient(make_app(Home))
    tab1, tab2 = client.open("/"), client.open("/")
    tab1.click("cart")
    assert "cart 1" in tab1.text and "cart 0" in tab2.text
    tab2.click("cart")  # sees tab1's write on its next event
    assert "cart 2" in tab2.text
    assert "cart 0" in TestClient(tab1.client.app).open("/").text


def test_in_place_mutation_needs_touch():
    class Home(Page):
        items = State(factory=list)

        def add_silently(self):
            self.items.append(1)

        def add(self):
            self.items.append(1)
            self.touch("items")

        def render(self):
            return Column(
                Text(f"items={len(self.items)}"),
                Button("silent", on_click=self.add_silently),
                Button("loud", on_click=self.add),
            )

    page = TestClient(make_app(Home)).open("/")
    page.click("silent")
    assert "items=0" in page.text
    page.click("loud")
    assert "items=2" in page.text


def test_writing_state_during_render_is_an_error():
    class Home(Page):
        n = State(0)

        def render(self):
            self.n = 5
            return Text("x")

    with pytest.raises(RuntimeError, match="during render"):
        TestClient(make_app(Home)).open("/")


def test_async_mount_and_render():
    class Home(Page):
        data = State("")

        async def mount(self):
            self.data = "loaded"

        async def render(self):
            return Text(self.data)

    page = TestClient(make_app(Home)).open("/")
    assert "loaded" in page.text and page.manifest is None


def test_navigate_and_run_js_actions():
    class Home(Page):
        def go(self):
            self.navigate("/elsewhere")
            self.run_js(js.focus("#x"))

        def render(self):
            return Button("go", on_click=self.go)

    page = TestClient(make_app(Home)).open("/")
    data = page.click("go")
    assert data["actions"] == [{"op": "navigate", "url": "/elsewhere"}, {"op": "js", "ops": [["focus", "#x"]]}]
    with pytest.raises(ValueError):
        Home().navigate("https://evil.example")


def test_client_ops_make_a_page_interactive_without_handlers():
    class Home(Page):
        def render(self):
            return Button("theme", on_click=js.toggle_theme())

    page = TestClient(make_app(Home)).open("/")
    assert page.manifest is not None
    assert page.dom.find_all("button")[0].get("data-rw-js-click") == '[["toggle_theme",null]]'


def test_duplicate_keys_are_rejected():
    class Home(Page):
        def render(self):
            return Column(Counter(key="a"), Counter(key="a"))

    with pytest.raises(ValueError, match="duplicate component identity"):
        TestClient(make_app(Home)).open("/")


def test_user_text_is_escaped_in_patches():
    class Home(Page):
        name = State("")

        def set_name(self, value: str):
            self.name = value

        def render(self):
            return Column(Input("Name", on_input=self.set_name), Text(f"Hi {self.name}"))

    page = TestClient(make_app(Home)).open("/")
    data = page.input("Name", "<img src=x onerror=alert(1)>")
    # A text edit is applied with textContent in the browser, so the raw string is safe.
    assert data["patches"][0]["op"] == "edit"
    assert "<img src=x onerror=alert(1)>" in json.dumps(data["patches"])

    page = TestClient(make_app(Home, fine_patches=False)).open("/")
    html = page.input("Name", "<img src=x onerror=alert(1)>")["patches"][0]["html"]
    assert "<img" not in html
    assert "&lt;img src=x onerror=alert(1)&gt;" in html


def test_form_controls_are_labelled_and_described():
    class Home(Page):
        def render(self):
            return Form(Input("E-mail address", help="We never share it", required=True))

    page = TestClient(make_app(Home)).open("/")
    control = page.field("E-mail address")
    assert control.get("name") == "e_mail_address" and control.get("required") == ""
    described = control.get("aria-describedby").split()
    assert len(described) == 2 and all(page.dom.find_all(id=i) for i in described)
