"""Modal, tabs and toasts in a real browser."""

import pytest

from rational import App, Button, Menu, MenuItem, Modal, Page, Tabs, Text, Toast, Toasts, js
from tests.browser._support import collect_errors, playwright, serve

pytestmark = pytest.mark.browser


def make_app():
    app = App()

    @app.page("/")
    class Home(Page):
        def render(self):
            return [
                Button("Open modal", on_click=js.open_dialog("#dlg")),
                Modal(Text("Are you sure?"), id="dlg", title="Confirm"),
                Tabs([("Alpha", Text("first panel")), ("Beta", Text("second panel"))], id="tabs"),
                Toasts(Toast("Saved!", tone="success")),
                Menu(
                    "Actions", MenuItem("Rename", on_click=js.set_text("Renamed", "#status")), MenuItem("Other"), id="m"
                ),
                Text("Idle", id="status"),
            ]

    return app


def test_tabs_and_menu_keyboard(browser):
    server, thread, url = serve(make_app())
    try:
        page = browser.new_page()
        errors = collect_errors(page)
        page.goto(url)

        page.get_by_role("tab", name="Alpha").focus()
        page.keyboard.press("ArrowRight")
        playwright.expect(page.get_by_role("tab", name="Beta")).to_be_focused()
        playwright.expect(page.get_by_text("second panel")).to_be_visible()
        page.keyboard.press("ArrowRight")  # wraps around
        playwright.expect(page.get_by_role("tab", name="Alpha")).to_be_focused()
        page.keyboard.press("End")
        playwright.expect(page.get_by_role("tab", name="Beta")).to_have_attribute("tabindex", "0")

        trigger = page.get_by_role("button", name="Actions")
        trigger.focus()
        page.keyboard.press("ArrowDown")
        playwright.expect(page.get_by_role("menu")).to_be_visible()
        playwright.expect(page.get_by_role("menuitem", name="Rename")).to_be_focused()
        playwright.expect(trigger).to_have_attribute("aria-expanded", "true")
        page.keyboard.press("ArrowDown")
        playwright.expect(page.get_by_role("menuitem", name="Other")).to_be_focused()
        page.keyboard.press("Escape")
        playwright.expect(page.get_by_role("menu")).to_be_hidden()
        playwright.expect(trigger).to_be_focused()

        trigger.click()
        page.get_by_role("menuitem", name="Rename").click()
        playwright.expect(page.get_by_role("menu")).to_be_hidden()
        playwright.expect(page.locator("#status")).to_have_text("Renamed")
        trigger.click()
        page.locator("#status").click()  # an outside click closes it
        playwright.expect(page.get_by_role("menu")).to_be_hidden()
        assert errors == []
    finally:
        server.should_exit = True
        thread.join(timeout=5)


def test_modal_tabs_and_toast(browser):
    server, thread, url = serve(make_app())
    try:
        page = browser.new_page()
        errors = collect_errors(page)
        page.goto(url)

        playwright.expect(page.get_by_text("first panel")).to_be_visible()
        playwright.expect(page.get_by_text("second panel")).to_be_hidden()
        page.get_by_role("tab", name="Beta").click()
        playwright.expect(page.get_by_text("second panel")).to_be_visible()
        playwright.expect(page.get_by_text("first panel")).to_be_hidden()
        playwright.expect(page.get_by_role("tab", name="Beta")).to_have_attribute("aria-selected", "true")
        playwright.expect(page.get_by_role("tab", name="Alpha")).to_have_attribute("aria-selected", "false")

        page.get_by_role("button", name="Open modal").click()
        playwright.expect(page.get_by_role("dialog")).to_be_visible()
        page.keyboard.press("Escape")
        playwright.expect(page.get_by_role("dialog")).to_be_hidden()
        page.get_by_role("button", name="Open modal").click()
        page.get_by_role("button", name="Close").click()
        playwright.expect(page.get_by_role("dialog")).to_be_hidden()

        playwright.expect(page.get_by_text("Saved!")).to_be_visible()
        page.get_by_role("button", name="Dismiss").click()
        playwright.expect(page.get_by_text("Saved!")).to_have_count(0)
        assert errors == []
    finally:
        server.should_exit = True
        thread.join(timeout=5)
