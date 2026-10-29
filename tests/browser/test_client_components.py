"""Client components in a real browser: compiled Python runs locally, with no round trips."""

import pytest

from tests.browser._support import collect_errors, playwright, serve
from tests.clientapp import ISLAND_ERRORS, SERVER_TEXTS, TEXTS, assert_same, make_app

pytestmark = pytest.mark.browser


@pytest.fixture
def live():
    server, thread, url = serve(make_app())
    yield url
    server.should_exit = True
    thread.join(timeout=5)


def test_client_components_run_in_the_browser(browser, live):
    page = browser.new_page()
    errors = collect_errors(page)
    events = []
    page.on("request", lambda r: events.append(r.url) if "/_rational/event" in r.url else None)
    page.goto(live)
    page.wait_for_function("Array.from(document.querySelectorAll('rw-island')).every((el) => el.__rw)")

    page.get_by_role("button", name="First plus").click()
    page.get_by_role("button", name="First plus").click()
    page.get_by_text("First: 2").wait_for()

    page.get_by_label("Say").press_sequentially("hi", delay=20)
    page.get_by_text("You said: HI").wait_for()
    assert events == []  # everything so far ran in the browser

    page.get_by_role("button", name="Rename").click()  # a server event changes the island's prop...
    page.get_by_text("Second: 2").wait_for()  # ...and the island keeps its own state
    assert len(events) == 1
    playwright.expect(page.get_by_label("Say")).to_have_value("hi")
    assert errors == []


def test_compiled_code_matches_python(browser, live):
    page = browser.new_page()
    errors = collect_errors(page)
    page.add_init_script(ISLAND_ERRORS)
    page.goto(live + "/semantics?n=7")
    page.wait_for_function("document.querySelector('rw-island').__rw")
    python_7 = page.evaluate(SERVER_TEXTS, live + "/semantics?n=7")
    assert len(python_7) > 80
    assert_same(python_7, page.evaluate(TEXTS))  # hydration rendered exactly what the server did

    # Now the browser alone computes every value for another input; the server computes the same page.
    python_8 = page.evaluate(SERVER_TEXTS, live + "/semantics?n=8")
    page.evaluate("document.querySelector('rw-island').__rw.s.n = 8")
    page.wait_for_function(f"document.querySelectorAll('rw-island p')[0].textContent === {python_8[0]!r}")
    assert_same(python_8, page.evaluate(TEXTS))
    assert python_8 != python_7
    assert page.evaluate("window.__rw_errors") == [] and errors == []


def test_remote_calls_nested_components_and_server_children(browser, live):
    page = browser.new_page()
    errors = collect_errors(page)
    page.add_init_script(ISLAND_ERRORS)
    events = []
    page.on("request", lambda r: events.append(r.url) if "/_rational/event" in r.url else None)
    page.goto(live + "/todos")
    page.wait_for_function("document.querySelector('rw-island').__rw")

    page.get_by_role("button", name="Add").click()  # empty: the service refuses, as a RemoteError
    page.get_by_text("Error: Write something first").wait_for()

    page.get_by_label("New todo").fill("buy milk")
    page.get_by_role("button", name="Add").click()
    page.get_by_text("Added Buy Milk (7 letters)").wait_for()  # two remote calls and a sleep, all awaited
    playwright.expect(page.get_by_label("New todo")).to_have_value("")
    page.get_by_label("New todo").fill("call mom")
    page.get_by_role("button", name="Add").click()
    page.get_by_text("Added Call Mom (7 letters)").wait_for()

    page.get_by_role("checkbox", name="Buy Milk").check()  # a nested client component keeps its own state
    page.get_by_role("button", name="Remove Call Mom").click()  # a callback prop runs the parent's method
    playwright.expect(page.get_by_role("checkbox", name="Call Mom")).to_have_count(0)
    playwright.expect(page.get_by_role("checkbox", name="Buy Milk")).to_be_checked()

    page.get_by_role("button", name="Server clicks: 0").click()  # a server component inside the island
    page.get_by_text("Server clicks: 1").wait_for()
    assert len(events) == 1  # only that click went to the server
    playwright.expect(page.get_by_role("checkbox", name="Buy Milk")).to_be_checked()  # island state survived
    assert page.evaluate("window.__rw_errors") == []
    assert [e for e in errors if "status of 400" not in e] == [], errors  # the refused add is the only 400


def test_client_components_on_cached_pages_fetch_a_token_for_remote_calls(browser, live):
    page = browser.new_page()
    errors = collect_errors(page)
    page.goto(live + "/todos")  # an interactive page: the visitor now has a session (and a token)
    page.wait_for_function("document.querySelector('rw-island').__rw")
    token_requests = []
    page.on("request", lambda r: token_requests.append(r.url) if r.url.endswith("/_rational/csrf") else None)
    response = page.goto(live + "/cached-todos")
    assert response.headers["cache-control"] == "public, max-age=60"
    assert page.evaluate("JSON.parse(document.getElementById('rw-manifest').textContent).csrf") is None
    page.wait_for_function("document.querySelector('rw-island').__rw")

    page.get_by_label("New todo").fill("tea")
    page.get_by_role("button", name="Add").click()  # refused for CSRF, token fetched, call retried
    page.get_by_text("Added Tea (3 letters)").wait_for()
    page.get_by_label("New todo").fill("jam")
    page.get_by_role("button", name="Add").click()
    page.get_by_text("Added Jam (3 letters)").wait_for()
    assert len(token_requests) == 1  # fetched once, then kept
    assert [e for e in errors if "status of 403" not in e] == [], errors  # the first, refused call


def test_binding_computed_values_and_watchers_in_the_browser(browser, live):
    page = browser.new_page()
    errors = collect_errors(page)
    page.add_init_script(ISLAND_ERRORS)
    events = []
    page.on("request", lambda r: events.append(r.url) if "/_rational/event" in r.url else None)
    page.goto(live + "/signup")
    page.wait_for_function("document.querySelector('rw-island').__rw")
    page.get_by_text("Hi There (0)").wait_for()
    page.get_by_label("Your name").press_sequentially("ada lovelace", delay=10)
    page.get_by_text("Hi Ada Lovelace (0)").wait_for()
    page.get_by_label("Your age").fill("36")
    page.get_by_text("Hi Ada Lovelace (36)").wait_for()
    page.get_by_text("Changes: 0->36").wait_for()
    assert events == [] and page.evaluate("window.__rw_errors") == [] and errors == []
