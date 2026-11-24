"""A flood of anonymous requests must not push out the visitors who are using the site (review 2026-11-24, #1)."""

import json

import pytest

from rational import App, Button, Component, Limits, Page, State, Text
from rational.limits import NEW_VISITOR_TTL
from rational.session import SessionStore
from rational.stores import MemorySessionDriver, PersistentSessionStore
from rational.testing import TestClient


class Counter(Component):
    count = State(0)

    def increment(self):
        self.count += 1

    def render(self):
        return Button(f"Count: {self.count}", on_click=self.increment)


def counter_app(**limits):
    app = App(limits=Limits(**limits))

    @app.page("/")
    class Home(Page):
        def render(self):
            return Counter()

    @app.page("/about")
    class About(Page):
        def render(self):
            return Text("static")

    return app


def anonymous_get(app, path="/"):
    """A request from someone who never sends cookies back."""
    return TestClient(app).http.get(path, headers={"accept": "text/html"})


def test_cookieless_requests_do_not_evict_a_returning_visitor():
    app = counter_app(max_pages=20, max_new_pages=10, new_visitor_pages=None)
    user = TestClient(app).open("/")
    user.click("Count: 0")  # the browser came back with its cookie

    for _ in range(200):  # ten times both pools
        assert anonymous_get(app).status_code == 200

    user.click("Count: 1")
    assert "Count: 2" in user.text


def test_a_returning_visitors_first_page_survives_a_flood_once_the_cookie_comes_back():
    app = counter_app(max_pages=20, max_new_pages=10, new_visitor_pages=None)
    client = TestClient(app)
    client.open("/about")  # no session yet: a static page
    first = client.open("/")  # a first-time visitor's page...
    second = client.open("/")  # ...and a returning one's

    for _ in range(50):
        anonymous_get(app)

    second.click("Count: 0")
    assert "Count: 1" in second.text
    assert first.click("Count: 0", check=False)["error"]["code"] == "expired"  # never used: may go


def test_one_session_cannot_fill_the_main_pool():
    app = counter_app(max_pages=10, pages_per_session=3, new_visitor_pages=None)
    victim = TestClient(app).open("/")
    victim.click("Count: 0")

    flooder = TestClient(app)
    for _ in range(50):  # keeps its cookie: every page after the first is a returning visitor's
        flooder.open("/")

    victim.click("Count: 1")
    assert len(app.pages) <= 1 + 3


def test_new_visitor_pages_are_limited_per_ip_without_a_cookie():
    app = counter_app(new_visitor_pages="3/minute")
    returning = TestClient(app)
    returning.open("/")  # its first page counts: it had no cookie yet

    for _ in range(2):
        assert anonymous_get(app).status_code == 200
    refused = anonymous_get(app)
    assert refused.status_code == 429
    assert "set-cookie" not in refused.headers and "retry-after" in refused.headers

    assert returning.open("/").status_code == 200  # a visitor with a session is not counted
    assert anonymous_get(app, "/about").status_code == 200  # nor are pages that need no session


def test_limits_are_validated():
    with pytest.raises(ValueError):
        Limits(new_visitor_pages="lots")
    with pytest.raises(ValueError):
        Limits(pages_per_session=0)


def test_the_event_rate_limit_is_per_session_not_per_page_view():
    app = counter_app(event_burst=3, event_rate=0.001, new_visitor_pages=None)
    client = TestClient(app)
    pages = [client.open("/") for _ in range(3)]
    for page in pages:
        page.click(page.find("Count", "click").text)
    fresh = client.open("/")  # a new page view does not come with a new bucket
    assert fresh.click("Count: 0", check=False)["error"]["code"] == "rate_limited"


async def test_session_store_keeps_new_sessions_apart_until_the_cookie_comes_back():
    store = SessionStore(max_items=2, max_new=2)
    kept = store.create()
    assert await store.load(kept.id) is kept  # the browser came back

    for _ in range(10):
        store.create()

    assert await store.load(kept.id) is kept
    assert len(store._store) == 1 and len(store._new) == 2


async def test_persistent_store_keeps_a_first_time_visitors_record_for_an_hour():
    driver = MemorySessionDriver()
    store = PersistentSessionStore(driver, ttl=24 * 3600)
    session = store.create()
    session["x"] = 1
    await store.save(session)

    def lifetime():
        import time

        expires, raw = driver._items[store._key(session.id)]
        return expires - time.monotonic(), json.loads(raw)

    assert lifetime()[0] <= NEW_VISITOR_TTL

    assert await store.load(session.id) is session  # the cookie came back
    await store.save(session)
    assert lifetime()[0] > NEW_VISITOR_TTL
