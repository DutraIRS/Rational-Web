"""How the browser runtime copes when things change under it: tokens, sessions, widgets and URLs."""

import pytest

from rational import App, Button, Column, Component, Forbidden, Form, Link, Page, State, Text
from rational.bots import Captcha, HumanCheck
from tests.browser._support import collect_errors, playwright, serve

pytestmark = pytest.mark.browser

WIDGET_SCRIPT = "https://challenges.cloudflare.com/**"


class Counter(Component):
    n = State(0)

    def inc(self):
        self.n += 1

    def refuse(self):
        raise Forbidden("Not for you")

    def render(self):
        return Column(
            Text(f"n={self.n}", id="n"),
            Button("Inc", on_click=self.inc),
            Button("Refuse", on_click=self.refuse),
        )


def counter_app():
    app = App()

    @app.page("/")
    class Home(Page):
        def render(self):
            return Counter()

    return app


def only_page(app):
    return next(entry[1] for entry in app.pages._items.values())


def test_a_changed_token_is_fetched_and_the_event_sent_again(browser):
    app = counter_app()
    server, thread, url = serve(app)
    try:
        page = browser.new_page()
        page.goto(url)
        only_page(app).session.csrf = "changed-by-a-sign-in-in-another-tab"
        page.get_by_role("button", name="Inc").click()
        playwright.expect(page.locator("#n")).to_have_text("n=1")
    finally:
        server.should_exit = True
        thread.join(timeout=5)


def test_a_handler_refusing_shows_its_error_without_reloading(browser):
    app = counter_app()
    server, thread, url = serve(app)
    try:
        page = browser.new_page()
        page.goto(url)
        page.evaluate(
            """() => {
                window.kept = true;
                document.addEventListener("rw:error", (e) => { window.refused = e.detail.code; });
            }"""
        )
        page.get_by_role("button", name="Refuse").click()
        page.wait_for_function("window.refused === 'forbidden'")
        assert page.evaluate("window.kept") is True
    finally:
        server.should_exit = True
        thread.join(timeout=5)


def test_a_page_of_another_session_reloads(browser):
    app = counter_app()
    server, thread, url = serve(app)
    try:
        page = browser.new_page()
        page.goto(url)
        page.evaluate("window.kept = true")
        only_page(app).session = None  # as when the cookie now names another session
        with page.expect_navigation():
            page.get_by_role("button", name="Inc").click()
        assert page.evaluate("window.kept") is None
    finally:
        server.should_exit = True
        thread.join(timeout=5)


class Guarded(Component):
    n = State(0)

    def inc(self):
        self.n += 1

    def render(self):
        return Form(HumanCheck(), Text(f"n={self.n}", id="n"), Button("Inc", on_click=self.inc, type="button"))


def captcha_app(**kwargs):
    app = App(secret_key="k" * 40, **kwargs)
    Captcha(app, "turnstile", site_key="key", secret="secret")

    @app.page("/form")
    class WithWidget(Page):
        def render(self):
            return Guarded()

    @app.page("/")
    class Home(Page):
        def render(self):
            return Link("To the form", href="/form")

    return app


def fake_widget_script(page):
    page.route(
        WIDGET_SCRIPT,
        lambda route: route.fulfill(
            status=200,
            content_type="text/javascript",
            body="window.widgetScripts = (window.widgetScripts || 0) + 1;",
        ),
    )


def test_a_re_render_leaves_what_the_captcha_put_in_its_widget(browser):
    server, thread, url = serve(captcha_app(fine_patches=False))  # whole components are morphed
    try:
        page = browser.new_page()
        errors = collect_errors(page)
        fake_widget_script(page)
        page.goto(url + "/form")
        assert page.evaluate("window.widgetScripts") == 1
        page.evaluate("document.querySelector('.cf-turnstile').innerHTML = '<iframe id=challenge></iframe>'")
        page.get_by_role("button", name="Inc").click()
        playwright.expect(page.locator("#n")).to_have_text("n=1")
        playwright.expect(page.locator(".cf-turnstile #challenge")).to_have_count(1)
        assert errors == []
    finally:
        server.should_exit = True
        thread.join(timeout=5)


def test_client_navigation_loads_a_page_with_a_widget_in_full(browser):
    server, thread, url = serve(captcha_app(client_nav=True))
    try:
        page = browser.new_page()
        fake_widget_script(page)
        page.goto(url)
        assert page.evaluate("window.widgetScripts") is None  # pages without a form do not load it
        page.evaluate("window.kept = true")
        with page.expect_navigation():
            page.get_by_role("link", name="To the form").click()
        playwright.expect(page.locator("#n")).to_have_text("n=0")
        assert page.evaluate("window.kept") is None and page.evaluate("window.widgetScripts") == 1
    finally:
        server.should_exit = True
        thread.join(timeout=5)


class Search(Component):
    q = State("", query="q")
    n = State(0)

    def search(self):
        self.q = "cats"

    def inc(self):
        self.n += 1

    def render(self):
        return Column(
            Text(f"q={self.q} n={self.n}", id="status"),
            Button("Search", on_click=self.search),
            Button("Inc", on_click=self.inc),
        )


def test_going_back_over_an_anchor_stays_on_the_page_after_the_query_changed(browser):
    app = App(client_nav=True)

    @app.page("/")
    class Home(Page):
        def render(self):
            return Search()

    server, thread, url = serve(app)
    try:
        page = browser.new_page()
        page.goto(url)
        page.get_by_role("button", name="Search").click()
        playwright.expect(page.locator("#status")).to_have_text("q=cats n=0")
        assert page.url.endswith("/?q=cats")
        requests = []
        page.on("request", lambda request: requests.append(request) if request.method == "GET" else None)
        page.evaluate("location.hash = 'top'")
        page.go_back()
        page.get_by_role("button", name="Inc").click()
        playwright.expect(page.locator("#status")).to_have_text("q=cats n=1")  # still the same live page
        assert requests == []
    finally:
        server.should_exit = True
        thread.join(timeout=5)
