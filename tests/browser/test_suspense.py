"""Suspense in a real browser: the fallback first, then the pushed content, and the busy indicator."""

import asyncio
import threading

import pytest

from rational import App, Button, Page, Skeleton, State, Suspense, Text, h
from tests.browser._support import collect_errors, playwright, serve

pytestmark = pytest.mark.browser


def make_app(report: threading.Event, handler: threading.Event):
    """The slow parts wait for the test to release them, so the in-between states can be seen."""
    app = App()

    async def load():
        await asyncio.to_thread(report.wait, 10)
        return Text("Report ready", id="report")

    @app.page("/")
    class Home(Page):
        n = State(0)

        async def slow(self):
            await asyncio.to_thread(handler.wait, 10)
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
    report, handler = threading.Event(), threading.Event()
    server, thread, url = serve(make_app(report, handler))
    try:
        page = browser.new_page()
        errors = collect_errors(page)
        page.goto(url, wait_until="commit")  # the page streams: it is not "loaded" until the report comes
        playwright.expect(page.locator(".rw-skeleton")).to_be_visible()
        report.set()
        playwright.expect(page.locator("#report")).to_have_text("Report ready", timeout=5000)
        playwright.expect(page.locator(".rw-skeleton")).to_have_count(0)

        page.get_by_role("button", name="Slow").click()
        playwright.expect(page.locator("html")).to_have_attribute("data-rw-busy", "")
        handler.set()
        playwright.expect(page.locator("#n")).to_have_text("n=1", timeout=5000)
        playwright.expect(page.locator("html")).not_to_have_attribute("data-rw-busy", "")
        assert errors == []
    finally:
        report.set(), handler.set()
        server.should_exit = True
        thread.join(timeout=5)
