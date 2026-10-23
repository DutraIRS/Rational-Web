"""Live session sync: a change made in one tab reaches the other tabs of the same browser."""

import re

from rational import App, Button, Column, Component, Page, State, Text

from .test_push import Raw


def make_app(**options):
    app = App(**options)

    class Cart(Component):
        items = State(0, scope="session")

        def add(self):
            self.items += 1

        def render(self):
            return Column(Text(f"Items: {self.items}"), Button("Add", on_click=self.add))

    class Plain(Component):
        n = State(0)

        def bump(self):
            self.n += 1

        def render(self):
            return Column(Text(f"N: {self.n}"), Button("Bump", on_click=self.bump))

    @app.page("/")
    class Shop(Page):
        def render(self):
            return Cart()

    @app.page("/plain")
    class PlainPage(Page):
        def render(self):
            return Plain()

    return app


def second_tab(raw):
    tab = Raw(raw.app)
    tab.cookie = raw.cookie  # same browser, same session cookie
    return tab


def handler_of(html):
    return re.search(r'data-rw-on-click="([^"]+)"', html).group(1)


async def test_session_change_in_one_tab_updates_the_other():
    app = make_app(live_session=True)
    one = Raw(app)
    m1, html1 = await one.open_page()
    two = second_tab(one)
    m2, _html2 = await two.open_page()
    assert m1["stream"] and m2["stream"]

    stream = two.stream(m2)
    await stream.next()

    status, data = await one.event(m1, handler_of(html1))
    assert status == 200
    assert "Items: 1" in data["patches"][0]["html"]

    batch = await stream.until("Items: 1")
    assert batch["seq"] > 0
    await stream.close()


async def test_the_originating_tab_gets_no_duplicate_push():
    app = make_app(live_session=True)
    one = Raw(app)
    m1, html1 = await one.open_page()
    stream = one.stream(m1)
    await stream.next()

    await one.event(m1, handler_of(html1))

    try:
        frame = await stream.next(timeout=0.3)
    except TimeoutError:
        frame = None
    assert frame is None
    await stream.close()


async def test_live_session_is_off_by_default():
    app = make_app()
    manifest, _html = await Raw(app).open_page()
    assert manifest["stream"] is None


async def test_pages_that_do_not_read_the_session_open_no_stream():
    app = make_app(live_session=True)
    manifest, _html = await Raw(app).open_page("/plain")
    assert manifest["stream"] is None


async def test_closed_tabs_stop_listening():
    app = make_app(live_session=True)
    one = Raw(app)
    manifest, _html = await one.open_page()
    runtime = app.pages.get(manifest["page"])
    session = runtime.session
    assert len(session.listeners) == 1

    runtime.dispose()

    assert len(session.listeners) == 0
