"""Keeping bots out: rate limits, form checks and CAPTCHAs."""

import fakeredis
import pytest
from pydantic import BaseModel

from rational import App, Button, Component, FieldError, Form, Input, Page, State, Text, _http
from rational.backend import Service, remote
from rational.bots import HONEYPOT, STARTED, Captcha, HumanCheck, Limiter, NotHuman, TooManyRequests, human, limit
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
    assert '<div class="cf-turnstile" data-sitekey="site-key">' in response.text
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
        assert captcha.field == field and app.frame_origins
        with pytest.raises(FieldError) as failed:
            await captcha.verify("token")
        assert failed.value.details == [
            {"field": "captcha", "message": "The check could not be completed; please try again"}
        ]
    with pytest.raises(ValueError, match="provider"):
        Captcha(App(), "other", site_key="k", secret="s")  # type: ignore[arg-type]
    assert NotHuman().status == 422
