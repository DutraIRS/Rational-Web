"""js.optimistic: shown at once, kept on success, rolled back when the event fails."""

import asyncio

import pytest

from rational import App, Button, Page, State, Text, h, js
from rational.errors import InvalidInput
from tests.browser._support import collect_errors, playwright, serve

pytestmark = pytest.mark.browser


def make_app():
    app = App()

    @app.page("/")
    class Home(Page):
        saved = State(0)

        async def ok(self):
            await asyncio.sleep(0.5)
            self.saved += 1

        async def fail(self):
            await asyncio.sleep(0.5)
            raise InvalidInput("nope")

        def render(self):
            return h(
                "main",
                Text("idle", id="status"),
                Text(f"saved={self.saved}", id="saved"),
                Button("Ok", on_click=[js.optimistic(js.set_text("working", "#status")), self.ok]),
                Button("Fail", on_click=[js.optimistic(js.set_text("working", "#status")), self.fail]),
            )

    return app


def test_optimistic_applies_immediately_and_rolls_back_on_error(browser):
    server, thread, url = serve(make_app())
    try:
        page = browser.new_page()
        errors = collect_errors(page)
        page.goto(url)
        page.get_by_role("button", name="Fail").click()
        playwright.expect(page.locator("#status")).to_have_text("working")
        playwright.expect(page.locator("#status")).to_have_text("idle", timeout=5000)

        page.get_by_role("button", name="Ok").click()
        playwright.expect(page.locator("#status")).to_have_text("working")
        playwright.expect(page.locator("#saved")).to_have_text("saved=1", timeout=5000)
        assert errors == []
    finally:
        server.should_exit = True
        thread.join(timeout=5)
