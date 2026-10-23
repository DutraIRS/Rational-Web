"""Fine-grained edits applied by the browser runtime."""

import pytest

from rational import App, Button, Input, Page, State, Text, h, js
from tests.browser._support import collect_errors, playwright, serve

pytestmark = pytest.mark.browser


def make_app():
    app = App()

    @app.page("/")
    class Home(Page):
        count = State(0)
        name = State("")
        items = State(["a"])

        def inc(self):
            self.count += 1

        def set_name(self, value: str):
            self.name = value

        def add(self):
            self.items = [*self.items, f"i{len(self.items)}"]

        def render(self):
            return h(
                "main",
                Text(f"Count: {self.count}", id="count"),
                Button("Inc", on_click=self.inc),
                Button("Mark", on_click=js.set_text("marked", "#marker")),
                Text("plain", id="marker"),
                Input("Name", on_input=self.set_name),
                Text(f"Hi {self.name}", id="hi"),
                Button("Add", on_click=self.add),
                h("ul", *[h("li", Text(i)) for i in self.items]),
            )

    return app


def test_edits_keep_focus_and_client_side_changes(browser):
    server, thread, url = serve(make_app())
    try:
        page = browser.new_page()
        errors = collect_errors(page)
        page.goto(url)

        page.get_by_role("button", name="Mark").click()
        page.get_by_role("button", name="Inc").click()
        playwright.expect(page.locator("#count")).to_have_text("Count: 1")
        # The untouched node keeps its client-side change: only the changed text was patched.
        playwright.expect(page.locator("#marker")).to_have_text("marked")

        field = page.get_by_label("Name")
        field.click()
        field.press_sequentially("Ada")
        playwright.expect(page.locator("#hi")).to_have_text("Hi Ada")
        playwright.expect(field).to_be_focused()
        assert field.input_value() == "Ada"

        page.get_by_role("button", name="Add").click()
        playwright.expect(page.locator("li")).to_have_count(2)
        assert errors == []
    finally:
        server.should_exit = True
        thread.join(5)
