"""Stripe Checkout, portal and signed webhooks, against a fake Stripe API."""

import hashlib
import hmac
import json
import time

from rational import App, Page, Text, _http
from rational.stripe import Stripe, StripeError, _stripe_form
from rational.testing import TestClient


class FakeStripe:
    """Answers checkout, portal and customer calls, and records what was sent."""

    def __init__(self):
        self.checkouts = []
        self.portals = []
        self.fail = False

    async def __call__(self, method, url, *, form=None, headers=None, auth=None, **kwargs):
        assert auth == ("sk_test_x", ""), "the secret key rides as HTTP Basic"
        if self.fail:
            raise _http.HTTPError(402, json.dumps({"error": {"message": "Your card was declined."}}), url)
        if url.endswith("/v1/checkout/sessions"):
            self.checkouts.append(form)
            return {"id": "cs_test_1", "url": "https://checkout.stripe.com/c/cs_test_1"}
        if url.endswith("/v1/billing_portal/sessions"):
            self.portals.append(form)
            return {"id": "bps_1", "url": "https://billing.stripe.com/p/bps_1"}
        if "/v1/customers/" in url:
            return {"id": url.rsplit("/", 1)[1], "email": "ada@x.example"}
        raise AssertionError(f"unexpected call {method} {url}")


def stripe_app(fake, **kwargs):
    app = App(secret_key="k" * 40)
    events = []
    stripe = Stripe(app, secret_key="sk_test_x", webhook_secret="whsec_1", **kwargs)

    @stripe.handler
    async def on_event(event):
        events.append(event)

    @app.page("/upgrade")
    class Upgrade(Page):
        def render(self):
            return Text("upgrade")

    client = TestClient(app)
    return app, stripe, client, events


def sign(payload: bytes, secret: str, timestamp: int | None = None) -> str:
    t = int(time.time()) if timestamp is None else timestamp
    mac = hmac.new(secret.encode(), f"{t}.".encode() + payload, hashlib.sha256).hexdigest()
    return f"t={t},v1={mac}"


def test_checkout_url_creates_the_session_on_click(monkeypatch):
    fake = FakeStripe()
    monkeypatch.setattr(_http, "request", fake)
    app, stripe, client, _ = stripe_app(fake)
    url = stripe.checkout_url(
        line_items=[{"price": "price_123", "quantity": 2}],
        mode="payment",
        success_url="/done",
        cancel_url="/upgrade",
        customer_email="ada@x.example",
    )
    assert url.startswith("/stripe/checkout?c=")

    answer = client.http.get(url, follow_redirects=False)
    assert answer.status_code == 303
    assert answer.headers["location"] == "https://checkout.stripe.com/c/cs_test_1"
    sent = fake.checkouts[0]
    assert sent["line_items[0][price]"] == "price_123"
    assert sent["line_items[0][quantity]"] == "2"
    assert sent["mode"] == "payment"
    assert sent["customer_email"] == "ada@x.example"
    assert sent["success_url"].endswith("/done") and sent["success_url"].startswith("http")
    assert sent["cancel_url"].endswith("/upgrade")


def test_checkout_link_cannot_be_forged(monkeypatch):
    fake = FakeStripe()
    monkeypatch.setattr(_http, "request", fake)
    app, stripe, client, _ = stripe_app(fake)
    assert client.http.get("/stripe/checkout?c=forged", follow_redirects=False).status_code == 404
    assert client.http.get("/stripe/checkout", follow_redirects=False).status_code == 404
    url = stripe.checkout_url(mode="payment", success_url="/done", cancel_url="/u")
    first = client.http.get(url, follow_redirects=False)
    again = client.http.get(url, follow_redirects=False)
    assert first.status_code == again.status_code == 303  # a signed link, not a one-time token


def test_webhooks_are_verified_before_the_handler_runs(monkeypatch):
    fake = FakeStripe()
    monkeypatch.setattr(_http, "request", fake)
    app, stripe, client, events = stripe_app(fake)
    payload = json.dumps(
        {"id": "evt_1", "type": "checkout.session.completed", "data": {"object": {"id": "cs_1"}}}
    ).encode()

    ok = client.http.post("/stripe/webhook", content=payload, headers={"Stripe-Signature": sign(payload, "whsec_1")})
    assert ok.status_code == 200 and ok.json() == {"received": True}
    assert events[0]["type"] == "checkout.session.completed"

    wrong = client.http.post(
        "/stripe/webhook", content=payload, headers={"Stripe-Signature": sign(payload, "whsec_other")}
    )
    assert wrong.status_code == 400 and events[-1] is events[0]

    stale = sign(payload, "whsec_1", timestamp=int(time.time()) - 3600)
    old = client.http.post("/stripe/webhook", content=payload, headers={"Stripe-Signature": stale})
    assert old.status_code == 400

    body_swap = json.dumps({"id": "evt_2", "type": "charge.refunded"}).encode()
    reused = sign(payload, "whsec_1")
    tampered = client.http.post("/stripe/webhook", content=body_swap, headers={"Stripe-Signature": reused})
    assert tampered.status_code == 400


def test_portal_customer_and_api_errors(monkeypatch):
    fake = FakeStripe()
    monkeypatch.setattr(_http, "request", fake)
    app, stripe, client, _ = stripe_app(fake)

    from asyncio import run

    async def calls():
        portal = await stripe.portal("cus_1", return_url="/account")
        assert fake.portals[0] == {"customer": "cus_1", "return_url": "/account"}
        assert portal["url"] == "https://billing.stripe.com/p/bps_1"
        who = await stripe.customer("cus_9")
        assert who["email"] == "ada@x.example"
        fake.fail = True
        try:
            await stripe.checkout(mode="payment")
        except StripeError as e:
            return e
        return None

    error = run(calls())
    assert error is not None and error.status == 402 and "card was declined" in str(error)


def test_nested_parameters_become_stripes_form_encoding():
    form = _stripe_form({"mode": "payment", "metadata": {"order": "7"}, "line_items": [{"price": "p", "quantity": 1}]})
    assert form == {
        "mode": "payment",
        "metadata[order]": "7",
        "line_items[0][price]": "p",
        "line_items[0][quantity]": "1",
    }
