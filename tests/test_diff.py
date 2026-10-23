from rational import App, Button, Column, Input, Page, State, Text
from rational.diff import diff
from rational.rendering.nodes import Node, RawHTML, TextNode
from rational.testing import TestClient


def el(tag, *children, **attrs):
    return Node(tag, attrs=tuple(attrs.items()), children=tuple(children))


def test_identical_trees_need_no_edits():
    assert diff(el("p", TextNode("a")), el("p", TextNode("a"))) == []


def test_text_change_is_a_text_edit():
    edits = diff(el("div", el("p", TextNode("a"))), el("div", el("p", TextNode("b"))))
    assert edits == [["t", [0], "p", "b"]]


def test_attribute_changes_and_removals():
    edits = diff(el("p", a="1", b="2"), el("p", a="9", c="3"))
    assert edits == [["a", [], "p", {"b": None, "a": "9", "c": "3"}]]


def test_added_child_replaces_the_parent_only():
    old = el("div", el("p", TextNode("x")), el("ul", el("li", TextNode("1"))))
    new = el("div", el("p", TextNode("x")), el("ul", el("li", TextNode("1")), el("li", TextNode("2"))))
    edits = diff(old, new)
    assert [e[0] for e in edits] == ["h"] and edits[0][1] == [1] and edits[0][2] == "ul"


def test_tag_change_and_raw_html_fall_back_to_replace():
    assert diff(el("div", el("p")), el("div", el("span")))[0][0] == "h"
    assert diff(el("div", RawHTML("<b>a</b>")), el("div", RawHTML("<b>b</b>")))[0][0] == "h"


def test_text_beside_elements_is_replaced_not_addressed():
    old = el("p", TextNode("a "), el("b", TextNode("x")))
    new = el("p", TextNode("c "), el("b", TextNode("x")))
    assert diff(old, new)[0][:2] == ["h", []]


def test_many_edits_fall_back_to_one_coarse_patch():
    old = el("ul", *[el("li", TextNode(str(i))) for i in range(100)])
    new = el("ul", *[el("li", TextNode(str(i + 1))) for i in range(100)])
    assert diff(old, new) is None


def make_page():
    class Home(Page):
        count = State(0)
        name = State("")

        def inc(self):
            self.count += 1

        def set_name(self, value: str):
            self.name = value

        def render(self):
            return Column(
                Text(f"Count: {self.count}"),
                Button("+", on_click=self.inc),
                Input("Name", on_input=self.set_name),
                Text(f"Hi {self.name}"),
            )

    return Home


def test_events_send_small_edits_and_the_dom_stays_correct():
    app = App()
    app.page("/")(make_page())
    with TestClient(app) as client:
        page = client.open("/")
        data = page.click("+")
        assert [p["op"] for p in data["patches"]] == ["edit"]
        assert all(e[0] == "t" for e in data["patches"][0]["edits"])
        assert "Count: 1" in page.text
        page.input("Name", "Ada")
        assert "Hi Ada" in page.text


def test_fine_patches_can_be_disabled():
    app = App(fine_patches=False)
    app.page("/")(make_page())
    with TestClient(app) as client:
        data = client.open("/").click("+")
        assert [p["op"] for p in data["patches"]] == ["morph"]
