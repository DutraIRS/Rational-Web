"""Declarative client operations (``js.*``) in a real browser."""

import pytest

from rational import App, Button, Page, Text, h, js
from tests.browser._support import collect_errors, playwright, serve

pytestmark = pytest.mark.browser


def make_app():
    app = App()

    @app.page("/")
    class Home(Page):
        def render(self):
            return h(
                "main",
                Button("Toggle", on_click=js.toggle("#panel")),
                h("div", Text("Panel"), id="panel", hidden=True),
                Button("Hide", on_click=js.hide("#panel")),
                Button("Rename", on_click=js.set_text("Renamed", "#label")),
                Text("Original", id="label"),
                h("input", id="field", value="typed"),
                Button("Clear", on_click=js.set_value("", "#field")),
                Button("Open", on_click=js.open_dialog("#dlg")),
                h("dialog", Text("Hi"), Button("Close", on_click=js.close_dialog()), id="dlg"),
                Button("Gone", on_click=js.remove("#label")),
            )

    return app


def test_client_ops(browser):
    server, thread, url = serve(make_app())
    try:
        page = browser.new_page()
        errors = collect_errors(page)
        page.goto(url)

        panel = page.locator("#panel")
        playwright.expect(panel).to_be_hidden()
        page.get_by_role("button", name="Toggle").click()
        playwright.expect(panel).to_be_visible()
        page.get_by_role("button", name="Hide").click()
        playwright.expect(panel).to_be_hidden()

        page.get_by_role("button", name="Rename").click()
        playwright.expect(page.locator("#label")).to_have_text("Renamed")

        page.get_by_role("button", name="Clear").click()
        playwright.expect(page.locator("#field")).to_have_value("")

        page.get_by_role("button", name="Open").click()
        playwright.expect(page.locator("#dlg")).to_be_visible()
        page.get_by_role("button", name="Close").click()
        playwright.expect(page.locator("#dlg")).to_be_hidden()

        page.get_by_role("button", name="Gone").click()
        playwright.expect(page.locator("#label")).to_have_count(0)
        assert errors == []
    finally:
        server.should_exit = True
        thread.join(timeout=5)
