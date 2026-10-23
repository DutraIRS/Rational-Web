"""The push stream over a real WebSocket, and the SSE fallback when it is off."""

import asyncio

import pytest

from rational import App, Component, Page, State, Text
from tests.browser._support import collect_errors, playwright, serve

pytestmark = pytest.mark.browser


def make_app(websocket):
    app = App(websocket=websocket)

    class Ticker(Component):
        count = State(0)

        async def mount(self):
            self.run_task(self.tick)

        async def tick(self):
            await asyncio.sleep(0.4)
            self.count += 1

        def render(self):
            return Text(f"Count: {self.count}", id="count")

    @app.page("/")
    class Home(Page):
        def render(self):
            return Ticker()

    return app


@pytest.mark.parametrize("websocket", [True, False])
def test_push_arrives_over_websocket_or_sse(browser, websocket):
    server, thread, url = serve(make_app(websocket))
    try:
        page = browser.new_page()
        errors = collect_errors(page)
        sockets = []
        page.on("websocket", lambda ws: sockets.append(ws.url))
        page.goto(url)
        playwright.expect(page.locator("#count")).to_have_text("Count: 1", timeout=5000)
        assert bool(sockets) is websocket
        assert errors == []
    finally:
        server.should_exit = True
        thread.join(timeout=5)
