"""Keeping bots out: rate limits, form checks and CAPTCHAs."""

import fakeredis
import pytest
from pydantic import BaseModel

from rational import App, Button, Component, FieldError, Form, Input, Page, State, Text, _http
from rational.backend import Service, remote
from rational.bots import (
    HONEYPOT,
    STARTED,
    Captcha,
    HumanCheck,
    Limiter,
    NotHuman,
    TooManyRequests,
    _signer,
    human,
    limit,
)
from rational.context import Context
from rational.stores import MemorySessionDriver, RedisSessionDriver
from rational.testing import TestClient


class Contact(BaseModel):
    email: str


class ContactForm(Component):
    sent = State("")

    @human
    def send(self, form: Contact):
        self.sent = form.email

    def render(self):
        return Form(
            Input("Email", name="email"),
            HumanCheck(),
            Button("Send", type="submit"),
            Text(self.sent),
            on_submit=self.send,
        )


def contact_app(**kwargs):
    app = App(secret_key="k" * 40, **kwargs)

    @app.page("/")
    class Home(Page):
        def render(self):
            return ContactForm()

    return app


def test_forms_reject_fast_submits_and_filled_traps():
    app = contact_app()
    page = TestClient(app).open("/")
    assert page.dom.find_all("input", name=HONEYPOT) and page.dom.find_all("input", name=STARTED)
    assert page.submit({"email": "a@x.example"}, check=False)["error"]["code"] == "not_human"  # too fast

    app.min_form_seconds = 0
    assert page.submit({"email": "bot@x.example", HONEYPOT: "spam"}, check=False)["error"]["code"] == "not_human"
    page.submit({"email": "a@x.example"})
    assert "a@x.example" in page.text

    tampered = page.submit({"email": "a@x.example", STARTED: "forged.value"}, check=False)
    assert "too old" in tampered["error"]["message"]


def test_submits_without_the_check_fields_are_refused():
    app = contact_app()
    app.min_form_seconds = 0
    page = TestClient(app).open("/")
    handler = page.dom.find_all("form")[0].attrs["data-rw-on-submit"]
    reply = page.fire(handler, {"form": {"email": "bot@x.example"}}, check=False)  # a script posting directly
    assert reply["error"]["code"] == "not_human"


def test_the_check_fields_never_reach_other_handlers():
    received = []

    class Plain(Component):
        def save(self, form: dict):
            received.append(form)

        def render(self):
            return Form(Input("Name", name="name"), HumanCheck(), Button("Save", type="submit"), on_submit=self.save)

    app = App(secret_key="k" * 40)

    @app.page("/")
    class Home(Page):
        def render(self):
            return Plain()

    TestClient(app).open("/").submit({"name": "Ada"})
    assert received == [{"name": "Ada"}]


def test_limits_on_pages_handlers_and_remote_methods():
    app = App()

    @app.page("/")
    @limit("2/minute")
    class Home(Page):
        def render(self):
            return Clicker()

    class Clicker(Component):
        count = State(0)

        @limit("1/minute", per="session")
        def bump(self):
            self.count += 1

        def render(self):
            return Button(f"Clicked {self.count}", on_click=self.bump)

    @app.service
    class Mail(Service):
        @remote()
        @limit("1/hour", per="user")
        def send(self) -> str:
            return "sent"

    client = TestClient(app)
    page = client.open("/")
    page.click("Clicked 0")
    assert page.click("Clicked 1", check=False)["error"]["code"] == "rate_limited"
    client.open("/")
    third = client.http.get("/")
    assert third.status_code == 429 and "Too many requests" in third.text

    api = TestClient(app).http  # an API caller: no browser session
    assert api.post("/api/mail/send", json={}).json() == "sent"
    second = api.post("/api/mail/send", json={})
    assert second.status_code == 429 and second.json()["error"]["details"]["retry_after"] > 0


async def test_limits_count_per_client_and_window_in_any_driver():
    @limit("2/10 seconds")
    def handler(): ...

    for driver in (MemorySessionDriver(), RedisSessionDriver(fakeredis.FakeAsyncRedis())):
        limiter = Limiter(driver)
        ctx = Context(None)
        await limiter.check(handler, ctx)
        await limiter.check(handler, ctx)
        with pytest.raises(TooManyRequests) as stopped:
            await limiter.check(handler, ctx)
        assert 1 <= stopped.value.retry_after <= 10
        await limiter.check(lambda: None, ctx)  # no @limit: never counted

    for rate in ("5", "five/minute", "0/minute", "5/fortnight"):
        with pytest.raises(ValueError, match="rate must look like"):
            limit(rate)


async def test_the_memory_driver_forgets_expired_keys():
    driver = MemorySessionDriver()
    for i in range(1000):
        await driver.set(f"k{i}", b"1", ttl=-1)  # already expired, never read again
    assert len(driver._items) <= 1


def test_captcha_widget_script_and_policy(monkeypatch):
    app = contact_app(csp=True)
    Captcha(app, "turnstile", site_key="site-key", secret="secret-key")
    app.min_form_seconds = 0
    client = TestClient(app)
    response = client.http.get("/")
    assert '<div class="cf-turnstile" data-sitekey="site-key" data-rw-ignore>' in response.text  # re-renders keep it
    assert 'src="https://challenges.cloudflare.com/turnstile/v0/api.js"' in response.text
    policy = response.headers["content-security-policy"]
    assert "frame-src 'self' https://challenges.cloudflare.com;" in policy
    assert "script-src 'self' https://challenges.cloudflare.com;" in policy

    verified = []

    async def fake_verify(method, url, *, form, **kwargs):
        verified.append((url, form))
        return {"success": form["response"] == "good"}

    monkeypatch.setattr(_http, "request", fake_verify)
    page = client.open("/")
    missing = page.submit({"email": "a@x.example"}, check=False)
    assert missing["error"]["details"] == [{"field": "captcha", "message": "Please confirm you are not a robot"}]
    assert page.submit({"email": "a@x.example", "cf-turnstile-response": "bad"}, check=False)["error"]
    page.submit({"email": "a@x.example", "cf-turnstile-response": "good"})
    assert "a@x.example" in page.text
    url, form = verified[-1]
    assert url == "https://challenges.cloudflare.com/turnstile/v0/siteverify"
    assert form["secret"] == "secret-key" and form["remoteip"] == "testclient"


async def test_captcha_providers_and_failures(monkeypatch):
    async def unreachable(*args, **kwargs):
        raise _http.HTTPError(0, "timed out", "https://x")

    monkeypatch.setattr(_http, "request", unreachable)
    for provider, field in (("hcaptcha", "h-captcha-response"), ("recaptcha", "g-recaptcha-response")):
        app = App()
        captcha = Captcha(app, provider, site_key="k", secret="s")
        assert captcha.field == field and app.csp_sources["frame-src"]
        with pytest.raises(FieldError) as failed:
            await captcha.verify("token")
        assert failed.value.details == [
            {"field": "captcha", "message": "The check could not be completed; please try again"}
        ]
    with pytest.raises(ValueError, match="provider"):
        Captcha(App(), "other", site_key="k", secret="s")  # type: ignore[arg-type]
    assert NotHuman().status == 422


def test_the_session_id_stays_out_of_the_page():
    app = contact_app()
    client = TestClient(app)
    page = client.open("/")
    token = page.dom.find_all("input", name=STARTED)[0].attrs["value"]
    assert client.http.cookies["rw_sid"] not in str(_signer(app).unsign(token))
    assert client.http.cookies["rw_sid"] not in client.http.get("/").text


def test_a_form_token_works_only_on_the_page_view_it_was_shown_on():
    app = contact_app()
    app.min_form_seconds = 0
    client = TestClient(app)
    first, second = client.open("/"), client.open("/")
    from_first = first.dom.find_all("input", name=STARTED)[0].attrs["value"]
    assert second.submit({"email": "a@x.example", STARTED: from_first}, check=False)["error"]["code"] == "not_human"
    first.submit({"email": "a@x.example", STARTED: from_first})
    assert "a@x.example" in first.text


def test_a_form_token_of_the_old_format_counts_as_too_old():
    app = contact_app()
    page = TestClient(app).open("/")
    old = _signer(app).sign("sid 123.0")
    assert "too old" in page.submit({"email": "a@x.example", STARTED: old}, check=False)["error"]["message"]


def test_debug_mode_says_what_is_missing_from_the_form():
    class Bare(Component):
        @human
        def send(self, form: Contact):
            pass

        def render(self):
            return Form(Input("Email", name="email"), Button("Send", type="submit"), on_submit=self.send)

    app = App(secret_key="k" * 40, debug=True)

    @app.page("/")
    class Home(Page):
        def render(self):
            return Bare()

    assert "HumanCheck" in TestClient(app).open("/").submit({"email": "a@x"}, check=False)["error"]["message"]


def test_captcha_script_loads_only_on_pages_that_use_it():
    app = contact_app(csp=True)

    @app.page("/plain")
    class Plain(Page):
        def render(self):
            return Text("no form")

    Captcha(app, "hcaptcha", site_key="k", secret="s")
    client = TestClient(app)
    plain, form = client.http.get("/plain"), client.http.get("/")
    assert "hcaptcha" not in plain.text
    assert 'src="https://js.hcaptcha.com/1/api.js"' in form.text
    assert '"full":true' in form.text  # client navigation loads this page in full, so the script runs
    policy = form.headers["content-security-policy"]
    for directive in ("script-src", "frame-src", "style-src", "connect-src"):
        assert any(part.startswith(directive) and "https://*.hcaptcha.com" in part for part in policy.split("; "))


def test_too_many_requests_says_when_to_come_back():
    class Api(Service):
        @remote
        @limit("1/hour")
        async def ping(self) -> dict:
            return {}

    app = App(secret_key="k" * 40)
    app.service(Api)

    @app.page("/limited")
    @limit("1/hour")
    class Limited(Page):
        def render(self):
            return Text("ok")

    client = TestClient(app)
    client.http.post("/api/api/ping", json={})
    refused = client.http.post("/api/api/ping", json={})
    assert refused.status_code == 429 and int(refused.headers["retry-after"]) > 0
    client.http.get("/limited")
    refused = client.http.get("/limited")
    assert refused.status_code == 429 and int(refused.headers["retry-after"]) > 0


async def test_limit_keys_fit_any_driver_and_hide_session_ids():
    driver = MemorySessionDriver()
    app = App()
    context = Context(app)
    context.session["x"] = 1

    @limit("5/minute", per="session")
    def target():
        pass

    target.__qualname__ = "t" * 300
    await Limiter(driver).check(target, context)
    (key,) = driver._items
    assert len(key) < 255 and context.session.id not in key
