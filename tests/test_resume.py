"""Resumable pages: state survives eviction of the in-memory runtime."""

import pytest

from rational import App, Button, Column, Component, Page, State, Text
from rational.stores import MemorySessionDriver
from rational.testing import EventFailedError, TestClient


def make_app(**kwargs):
    app = App(page_snapshots=MemorySessionDriver(), **kwargs)
    mounts = []

    class Counter(Component):
        n = State(0)
        label: str = "count"

        def mount(self):
            mounts.append(self.path)

        def inc(self):
            self.n += 1

        def render(self):
            return Column(Text(f"{self.label}={self.n}"), Button("+", on_click=self.inc))

    @app.page("/items/{item}")
    class Items(Page):
        item: int
        total = State(0, scope="page")

        def bump(self):
            self.total += 10

        def render(self):
            return Column(
                Text(f"item {self.item} total={self.total}"),
                Button("bump", on_click=self.bump),
                Counter(),
            )

    return app, mounts


def test_page_resumes_after_its_runtime_is_evicted():
    app, mounts = make_app()
    with TestClient(app) as client:
        view = client.open("/items/7")
        view.click("+")
        view.click("+")
        view.click("bump")
        assert "count=2" in view.html and "total=10" in view.html

        page_id = next(iter(app.pages._items)) if hasattr(app.pages, "_items") else None
        assert page_id is not None
        app.pages.pop(page_id)  # the process forgot the page
        assert app.pages.get(page_id) is None

        view.click("+")
        assert "count=3" in view.html and "total=10" in view.html and "item 7" in view.html
        assert len(mounts) == 2  # mount() ran again for the rebuilt page


def test_unknown_page_without_snapshots_is_still_gone():
    app = App()

    @app.page("/")
    class Home(Page):
        n = State(0)

        def inc(self):
            self.n += 1

        def render(self):
            return Button(f"n={self.n}", on_click=self.inc)

    with TestClient(app) as client:
        view = client.open("/")
        app.pages.pop(next(iter(app.pages._items)))
        with pytest.raises(EventFailedError, match="410"):
            view.click("n=0")
        assert "n=0" in view.html  # the page is reloaded, the click is lost


def test_snapshot_skips_values_that_are_not_json():
    app, _ = make_app()
    with TestClient(app) as client:
        client.open("/items/1")
        runtime = next(iter(app.pages._items.values()))[1]
        comp = next(c for c in runtime.components.values() if c.path and c.path.endswith("Counter:0"))
        comp._rw_state["blob"] = {1, 2}
        snap = app.resume.snapshot(runtime)
        assert "blob" not in snap["components"][comp.path]


async def test_persistent_sessions_carry_json_session_state():
    from rational.stores import PersistentSessionStore

    driver = MemorySessionDriver()
    first = PersistentSessionStore(driver)
    session = first.create()
    session.state["k"] = {"a": 1}
    session.state["blob"] = {1, 2}
    session.bump()
    await first.save(session)

    other = PersistentSessionStore(driver)  # another worker
    loaded = await other.load(session.id)
    assert loaded.state == {"k": {"a": 1}}


async def test_serverless_database_uses_a_null_pool():
    from sqlalchemy.pool import NullPool

    from rational.backend.database import Database

    db = Database("sqlite+aiosqlite://", serverless=True)
    assert isinstance(db.engine.pool, NullPool)
    await db.engine.dispose()
