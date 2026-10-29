"""State kept in the URL query: search pages that can be shared, bookmarked and resumed."""

import pytest

from rational import App, Button, Column, Component, Input, Page, State, Text
from rational.client import ClientCompileError, ClientComponent
from rational.stores import MemorySessionDriver
from rational.testing import TestClient


class Search(Component):
    q = State("", query="q")
    page = State(1, query="page")
    exact = State(False, query="exact")

    def type(self, value: str):
        self.q = value
        self.page = 1

    def next(self):
        self.page += 1

    def render(self):
        return Column(
            Input("Search", value=self.q, on_input=self.type),
            Button("Next", on_click=self.next),
            Text(f"q={self.q} page={self.page} exact={self.exact}"),
        )


def search_app(**kwargs):
    app = App(**kwargs)

    @app.page("/search")
    class SearchPage(Page):
        def render(self):
            return Search()

    return app


def test_state_starts_from_the_query_string():
    client = TestClient(search_app())
    assert "q=tea page=3 exact=True" in client.open("/search?q=tea&page=3&exact=true").text
    assert "q= page=1 exact=False" in client.open("/search?page=abc").text  # a bad value: the default


def test_changes_update_the_url_and_defaults_leave_it():
    view = TestClient(search_app()).open("/search?q=tea&page=3")
    reply = view.input("Search", "milk")
    assert {"op": "query", "name": "q", "value": "milk"} in reply["actions"]
    assert {"op": "query", "name": "page", "value": None} in reply["actions"]  # back to 1: dropped
    assert {"op": "query", "name": "page", "value": "2"} in view.click("Next")["actions"]
    assert {"op": "query", "name": "q", "value": None} in view.input("Search", "")["actions"]


def test_a_resumed_page_keeps_its_search():
    app = search_app(page_snapshots=MemorySessionDriver())
    client = TestClient(app)
    view = client.open("/search?q=tea")
    view.click("Next")
    app.pages.pop(next(iter(app.pages._items)))  # the worker forgot the page
    view.click("Next")
    assert "q=tea page=3" in view.text


def test_query_state_is_declared_with_plain_values_on_the_server():
    with pytest.raises(TypeError, match="query="):
        State(factory=list, query="tags")
    with pytest.raises(TypeError, match="query="):
        State("", scope="session", query="q")

    class Box(ClientComponent):
        q = State("", query="q")

        def render(self):
            return Text(self.q)

    app = App()

    @app.page("/")
    class Home(Page):
        def render(self):
            return Box()

    with pytest.raises(ClientCompileError, match="State\\(query=...\\) works in server components"):
        TestClient(app).open("/")
