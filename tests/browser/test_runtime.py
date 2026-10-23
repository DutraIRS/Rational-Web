"""Drive the real browser runtime (runtime.js) against a live server.

Skipped unless Playwright and Chromium are installed:
    pip install "rational[browser]" && playwright install chromium
"""

import pytest

from tests.browser._support import collect_errors, playwright, serve
from tests.examples.conftest import load_example

pytestmark = pytest.mark.browser


@pytest.fixture
def live(request):
    server, thread, url = serve(request.param)
    yield url
    server.should_exit = True
    thread.join(timeout=5)


@pytest.mark.parametrize("live", [load_example("counter").app], indirect=True)
def test_counter_clicks_inputs_and_theme(browser, live):
    page = browser.new_page()
    errors = collect_errors(page)
    page.goto(live)
    navigations = []
    page.on("framenavigated", lambda f: navigations.append(f.url))

    page.get_by_role("button", name="+10").click()
    page.get_by_role("button", name="+10").dblclick()  # queued, not dropped
    page.get_by_role("button", name="+1", exact=True).click()
    page.get_by_text("30", exact=True).wait_for()
    page.get_by_text("1", exact=True).wait_for()

    name = page.get_by_label("Your name")
    name.press_sequentially("Grace", delay=30)
    page.get_by_text("Hello, Grace!").wait_for()
    assert name.input_value() == "Grace"  # typing was never clobbered by morphs
    assert page.evaluate("document.activeElement.name") == "your_name"  # focus survived

    page.get_by_role("button", name="Toggle theme").click()
    assert page.evaluate("document.documentElement.dataset.theme") in ("dark", "light")

    page.get_by_role("button", name="Reset").first.click()
    playwright.expect(page.get_by_role("button", name="Reset").first).to_be_disabled()
    assert navigations == [] and errors == []


@pytest.fixture
def todos_app(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{(tmp_path / 'todos.db').as_posix()}")
    return load_example("todos").app


def test_todos_end_to_end(browser, todos_app):
    server, thread, url = serve(todos_app)
    try:
        page = browser.new_page()
        errors = collect_errors(page)
        page.goto(url)
        assert page.url.endswith("/login?next=/")

        page.get_by_label("Your name").fill("ada")
        page.get_by_role("button", name="Continue").click()
        page.wait_for_url(url + "/")

        box = page.get_by_label("New todo")
        box.fill("Write docs")
        box.press("Enter")
        page.get_by_text("1 item left").wait_for()
        playwright.expect(page.get_by_label("New todo")).to_be_focused()  # refocused for the next entry
        playwright.expect(page.get_by_label("New todo")).to_have_value("")
        page.keyboard.type("Ship")
        page.keyboard.press("Enter")
        page.get_by_text("2 items left").wait_for()

        page.get_by_role("checkbox", name="Write docs").check()
        page.get_by_text("1 item left").wait_for()
        page.get_by_role("button", name="Clear completed").click()
        page.get_by_role("checkbox", name="Write docs").wait_for(state="detached")

        # Client-side validation errors from the server land next to the field.
        page.goto(url + "/login")
        page.get_by_label("Your name").fill("<bad>")
        page.get_by_role("button", name="Continue").click()
        playwright.expect(page.get_by_label("Your name")).to_have_attribute("aria-invalid", "true")
        playwright.expect(page.locator("[data-rw-error-for=name]")).to_be_visible()
        assert errors == []
    finally:
        server.should_exit = True
        thread.join(timeout=5)
