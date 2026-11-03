"""Resumable pages: state survives eviction of the in-memory runtime."""

import logging

import pytest

from rational import App, Button, Column, Component, Page, PersistentSessionStore, State, Text
from rational.stores import MemorySessionDriver
from rational.testing import EventFailedError, TestClient


def make_app(snapshots=None, **kwargs):
    app = App(page_snapshots=MemorySessionDriver() if snapshots is None else snapshots, **kwargs)
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


def test_workers_can_take_turns_on_one_page():
    """Without sticky routing each event may reach either worker: an outdated copy is rebuilt, not refused."""
    from rational import PersistentSessionStore

    driver = MemorySessionDriver()
    workers = [TestClient(make_app(driver, session_store=PersistentSessionStore(driver))[0]) for _ in range(2)]
    view = workers[0].open("/items/7")
    workers[1].http.cookies.set("rw_sid", workers[0].http.cookies["rw_sid"])
    for turn in range(4):
        view.client = workers[turn % 2]
        assert "error" not in view.click("+")
    assert "count=4" in view.html


def test_a_snapshot_write_loses_to_a_concurrent_one():
    import asyncio

    app, _ = make_app()
    with TestClient(app) as client:
        client.open("/items/1")
        runtime = next(iter(app.pages._items.values()))[1]
        runtime.revision = 1  # this worker advanced the page from revision 0...
        assert asyncio.run(app.resume.save(runtime, expect_revision=0))
        runtime.revision = 1  # ...and so did another worker, from the same revision
        assert not asyncio.run(app.resume.save(runtime, expect_revision=0))


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


def deployed(driver, version):
    """The same page as served by two releases of the app."""
    from rational import PersistentSessionStore

    app = App(page_snapshots=driver, session_store=PersistentSessionStore(driver))

    class Counter(Component):
        if version == "renamed":
            count = State(0)
        elif version == "retyped":
            n = State("")
        else:
            n = State(0)
        if version == "extended":
            note = State("new state is fine")

        def inc(self):
            if version in ("old", "extended"):
                self.n += 1

        def render(self):
            return Button(f"+ {version}", on_click=self.inc)

    @app.page("/")
    class Home(Page):
        def render(self):
            return Counter()

    return TestClient(app)


@pytest.mark.parametrize("version", ["renamed", "retyped"])
def test_a_deploy_that_changes_saved_state_reloads_the_page(version):
    driver = MemorySessionDriver()
    old, new = deployed(driver, "old"), deployed(driver, version)
    view = old.open("/")
    view.click("+ old")
    new.http.cookies.set("rw_sid", old.http.cookies["rw_sid"])
    view.client = new  # the next event reaches a worker running the new code
    reply = view.click("+ old", check=False)
    assert reply["error"]["code"] == "expired"  # 410: the browser reloads the page afresh


def test_a_deploy_that_only_adds_state_resumes():
    driver = MemorySessionDriver()
    old, new = deployed(driver, "old"), deployed(driver, "extended")
    view = old.open("/")
    view.click("+ old")
    new.http.cookies.set("rw_sid", old.http.cookies["rw_sid"])
    view.client = new
    assert "error" not in view.click("+ old")


async def test_a_failed_save_does_not_read_as_another_worker_having_moved_on():
    app, _mounts = make_app()
    client = TestClient(app)
    view = client.open("/items/1")
    runtime = app.pages.get(view.manifest["page"])
    resumer = app.resume
    await resumer.save(runtime)  # stored at this revision
    runtime.revision += 2  # as after an event whose save failed
    assert await resumer.save(runtime, expect_revision=runtime.revision)
    runtime.revision -= 3
    assert not await resumer.save(runtime, expect_revision=runtime.revision)  # the stored one is really newer


def deployed_page_state(driver, kind):
    app = App(page_snapshots=driver, session_store=PersistentSessionStore(driver))

    @app.page("/")
    class Home(Page):
        total = State(kind(), scope="page")

        def bump(self):
            self.total = kind(1)

        def render(self):
            return Button("+", on_click=self.bump)

    return TestClient(app)


def test_page_state_that_no_longer_fits_the_code_reloads_the_page(caplog):
    driver = MemorySessionDriver()
    old, new = deployed_page_state(driver, int), deployed_page_state(driver, str)
    view = old.open("/")
    view.click("+")
    new.http.cookies.set("rw_sid", old.http.cookies["rw_sid"])
    view.client = new
    with caplog.at_level(logging.INFO, "rational"):
        reply = view.click("+", check=False)
    assert reply["error"]["code"] == "expired"
    record = next(r for r in caplog.records if "cannot be resumed" in r.getMessage())
    assert record.levelno == logging.INFO and record.exc_info is None  # after a deploy, not an error


def test_a_page_that_requires_signing_in_does_not_resume_for_a_signed_out_visitor():
    driver = MemorySessionDriver()
    store = PersistentSessionStore(MemorySessionDriver())
    app = App(page_snapshots=driver, session_store=store)

    @app.page("/login")
    class Login(Page):
        def mount(self):
            self.context.session.login("ada")

        def render(self):
            return Text("in")

    @app.page("/account", auth="required")
    class Account(Page):
        def render(self):
            return Button("Act", on_click=lambda: None)

    client = TestClient(app)
    client.http.get("/login")
    view = client.open("/account")
    page_id = view.manifest["page"]
    app.pages.pop(page_id)  # this worker no longer holds it
    app.sessions.get(client.http.cookies["rw_sid"]).data.clear()
    assert view.click("Act", check=False)["error"]["code"] == "expired"
