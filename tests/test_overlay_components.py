import pytest

from rational import App, Button, Menu, MenuItem, Modal, Page, Table, Tabs, Text, Toast, Toasts, js
from rational.testing import TestClient


def html_of(node):
    app = App()

    @app.page("/")
    class Home(Page):
        def render(self):
            return node

    with TestClient(app) as client:
        return client.open("/").html


def test_modal_is_a_labelled_hidden_dialog_with_a_close_button():
    html = html_of(Modal(Text("body"), id="dlg", title="Confirm"))
    assert "<dialog" in html and 'id="dlg"' in html and 'aria-labelledby="dlg-title"' in html
    assert "Confirm" in html and 'aria-label="Close"' in html


def test_tabs_render_all_panels_with_only_the_selected_visible():
    html = html_of(Tabs([("One", Text("a")), ("Two", Text("b"))], id="t", selected=1))
    assert html.count('role="tab"') == 2 and html.count('role="tabpanel"') == 2
    assert html.count("hidden") >= 1
    assert 'aria-selected="true"' in html and 'aria-selected="false"' in html


def test_table_renders_semantic_markup_and_empty_state():
    html = html_of(Table(["Name", "Age"], [["Ada", 36]], caption="People"))
    assert "<th" in html and 'scope="col"' in html and "Ada" in html and "People" in html
    assert "Nothing here" in html_of(Table(["A"], [], empty="Nothing here"))


def test_menu_is_a_labelled_hidden_menu_and_loads_the_runtime():
    html = html_of(Menu("Options", MenuItem("Edit"), MenuItem("Docs", href="/docs"), id="m"))
    assert 'aria-haspopup="menu"' in html and 'aria-expanded="false"' in html
    assert html.count('role="menuitem"') == 2 and 'role="menu"' in html and "data-rw-menu" in html
    assert "rw-manifest" in html  # a menu-only page still needs the runtime for its keyboard support


def test_tabs_use_a_roving_tabindex():
    html = html_of(Tabs([("One", Text("a")), ("Two", Text("b"))], id="t"))
    assert html.count('tabindex="0"') == 1 and html.count('tabindex="-1"') == 1


def test_toast_roles_and_region():
    html = html_of(Toasts(Toast("saved", tone="success"), Toast("boom", tone="danger")))
    assert 'role="status"' in html and 'role="alert"' in html and 'aria-live="polite"' in html


@pytest.mark.parametrize(
    "build",
    [
        lambda: Modal(id="1bad", title="x"),
        lambda: Tabs([], id="t"),
        lambda: Tabs([("a", "b")], id="t", selected=3),
        lambda: Table(["A", "B"], [["only one"]]),
        lambda: Toast("x", tone="loud"),
    ],
)
def test_bad_arguments_fail_early(build):
    with pytest.raises(ValueError):
        build()


def test_modal_opens_through_a_client_op():
    node = Button("Open", on_click=js.open_dialog("#dlg"))
    assert "open_dialog" in html_of(node)
