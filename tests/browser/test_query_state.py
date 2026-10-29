"""State(query=...) in a real browser: the URL follows the search, and a reload restores it."""

import pytest

from tests.browser._support import collect_errors, playwright, serve
from tests.test_query_state import search_app

pytestmark = pytest.mark.browser


def test_the_url_follows_the_search_and_survives_a_reload(browser):
    server, thread, url = serve(search_app())
    try:
        page = browser.new_page()
        errors = collect_errors(page)
        page.goto(url + "/search")
        page.get_by_label("Search").fill("milk")
        page.get_by_text("q=milk page=1").wait_for()
        page.get_by_role("button", name="Next").click()
        page.get_by_text("q=milk page=2").wait_for()
        playwright.expect(page).to_have_url(url + "/search?q=milk&page=2")
        history = page.evaluate("history.length")

        page.reload()
        page.get_by_text("q=milk page=2").wait_for()  # the state came back from the URL
        assert page.evaluate("history.length") == history  # updates replace the entry, not add one
        assert errors == []
    finally:
        server.should_exit = True
        thread.join(timeout=5)
