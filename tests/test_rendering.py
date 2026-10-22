import pytest

from rational.rendering import UnsafeMarkupError, h, to_html, unsafe_html
from rational.rendering.nodes import Node, TextNode


def test_text_and_attributes_are_escaped():
    node = Node("p", attrs=(("title", "a \"quoted\" <b> & 'x'"),), children=(TextNode("<script>&"),))
    assert to_html(node) == ('<p title="a &quot;quoted&quot; &lt;b&gt; &amp; &#x27;x&#x27;">&lt;script&gt;&amp;</p>')


def test_boolean_and_none_attributes():
    node = Node("input", attrs=(("disabled", True), ("checked", False), ("value", None), ("max", 3)))
    assert to_html(node) == '<input disabled max="3">'


def test_void_elements_have_no_closing_tag():
    assert to_html(Node("br")) == "<br>"
    with pytest.raises(ValueError):
        to_html(Node("img", children=(TextNode("x"),)))


@pytest.mark.parametrize("tag", ["script", "STYLE", "bad tag", "1h"])
def test_unsafe_tags_rejected(tag):
    with pytest.raises(UnsafeMarkupError):
        Node(tag)


@pytest.mark.parametrize("name", ["onclick", "onLoad", 'x"y', "a b"])
def test_unsafe_attribute_names_rejected(name):
    with pytest.raises(UnsafeMarkupError):
        Node("div", attrs=((name, "x"),))


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        " JavaScript:alert(1)",
        "java\tscript:x",
        "vbscript:x",
        "data:text/html,<b>",
        "data:image/svg+xml,<svg>",
    ],
)
def test_dangerous_urls_rejected(url):
    with pytest.raises(UnsafeMarkupError):
        Node("a", attrs=(("href", url),))


@pytest.mark.parametrize("url", ["/path", "https://example.com", "mailto:a@b.c", "data:image/png;base64,AA"])
def test_safe_urls_allowed(url):
    Node("a", attrs=(("href", url),))


def test_builder_maps_attribute_names_and_flattens_children():
    node = h("label", "a", ["b", None, ("c", 1)], False, class_="x", for_="id", aria_label="L", data_x="1")
    assert node.attrs == (("class", "x"), ("for", "id"), ("aria-label", "L"), ("data-x", "1"))
    assert [c.text for c in node.children] == ["a", "b", "c", "1"]


def test_builder_rejects_unknown_events_and_multiple_handlers():
    with pytest.raises(ValueError):
        h("div", on_hover=lambda: None)
    with pytest.raises(ValueError):
        h("div", on_click=[lambda: None, lambda: None])


def test_unresolved_nodes_are_not_serialized():
    with pytest.raises(ValueError):
        to_html(h("button", on_click=lambda: None))


def test_unsafe_html_is_verbatim():
    assert to_html(Node("div", children=(unsafe_html("<b>ok</b>"),))) == "<div><b>ok</b></div>"


def test_serialization_is_deterministic():
    tree = h("ul", [h("li", str(i), key=i) for i in range(3)])
    tree = Node(tree.tag, children=tuple(Node(c.tag, children=c.children) for c in tree.children))
    assert to_html(tree) == to_html(tree) == "<ul><li>0</li><li>1</li><li>2</li></ul>"
