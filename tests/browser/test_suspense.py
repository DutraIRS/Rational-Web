"""Suspense in a real browser: the fallback first, then the pushed content, and the busy indicator."""

import asyncio

import pytest

from rational import App, Button, Page, Skeleton, State, Suspense, Text, h
from tests.browser._support import collect_errors, playwright, serve

pytestmark = pytest.mark.browser


def make_app():
    app = App()

    async def load():
        await asyncio.sleep(0.6)
        return Text("Report ready", id="report")

    @app.page("/")
    class Home(Page):
        n = State(0)

        async def slow(self):
            await asyncio.sleep(0.5)
            self.n += 1

        def render(self):
            return h(
                "main",
                Suspense(load=load, fallback=Skeleton(height="2rem")),
                Button("Slow", on_click=self.slow),
                Text(f"n={self.n}", id="n"),
            )

    return app


def test_suspense_and_busy_indicator(browser):
    server, thread, url = serve(make_app())
    try:
        page = browser.new_page()
        errors = collect_errors(page)
        page.goto(url)
        playwright.expect(page.locator(".rw-skeleton")).to_be_visible()
        playwright.expect(page.locator("#report")).to_have_text("Report ready", timeout=5000)
        playwright.expect(page.locator(".rw-skeleton")).to_have_count(0)

        page.get_by_role("button", name="Slow").click()
        playwright.expect(page.locator("html")).to_have_attribute("data-rw-busy", "")
        playwright.expect(page.locator("#n")).to_have_text("n=1", timeout=5000)
        playwright.expect(page.locator("html")).not_to_have_attribute("data-rw-busy", "")
        assert errors == []
    finally:
        server.should_exit = True
        thread.join(timeout=5)
