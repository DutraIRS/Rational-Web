"""Stripe: Checkout, the customer portal and signed webhooks, without the SDK.

::

    stripe = Stripe(app, secret_key=STRIPE_SECRET_KEY, webhook_secret=STRIPE_WEBHOOK_SECRET)

    @app.page("/upgrade")
    class Upgrade(Page):
        def render(self):
            return ButtonLink("Upgrade", href=stripe.checkout_url(
                line_items=[{"price": "price_123", "quantity": 1}],
                mode="payment",
                success_url="/done",
                cancel_url="/upgrade",
            ))                                    # a signed link; the session is created on click

    @stripe.handler
    async def on_stripe(event):                   # a dict: the parsed, signature-verified event
        if event["type"] == "checkout.session.completed":
            ...

``checkout_url`` signs the parameters into a link; clicking it creates the Checkout Session on
Stripe and redirects the browser there, so no API call happens while rendering. Webhook calls are
verified against the ``Stripe-Signature`` header (timestamp plus HMAC of the exact body) before
any handler runs, and replayed or forged calls are rejected.
"""

from __future__ import annotations

import contextlib
import hashlib
import hmac
import inspect
import json
import logging
import time
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from fastapi import Request, Response
from fastapi.responses import JSONResponse, RedirectResponse

from . import _http
from .http import base_path
from .security import InvalidToken, Signer

if TYPE_CHECKING:
    from .app import App

_API = "https://api.stripe.com"
log = logging.getLogger("rational.stripe")


class StripeError(Exception):
    """Stripe answered with an error status."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(f"Stripe answered HTTP {status}: {message}")
        self.status = status
        self.message = message


Handler = Callable[[dict[str, Any]], Any | Awaitable[Any]]


class Stripe:
    """Adds ``{path}/checkout`` and ``{path}/webhook`` routes to ``app``; talks to the REST API."""

    def __init__(
        self,
        app: App,
        *,
        secret_key: str,
        webhook_secret: str = "",  # needed to accept webhooks: without it every webhook call is refused
        path: str = "/stripe",
        tolerance: float = 300.0,
        api_url: str = _API,
    ) -> None:
        self.app = app
        self.secret_key = secret_key
        self.webhook_secret = webhook_secret
        self.tolerance = tolerance
        self.api_url = api_url.rstrip("/")
        self.path = "/" + path.strip("/")
        self.handlers: list[Handler] = []
        app.fastapi.add_api_route(f"{self.path}/checkout", self._checkout, methods=["GET"], include_in_schema=False)
        app.fastapi.add_api_route(f"{self.path}/webhook", self._webhook, methods=["POST"], include_in_schema=False)

    @property
    def _signer(self) -> Signer:
        return self.app.signer("rational.stripe.checkout")

    def handler(self, fn: Handler) -> Handler:
        """Register ``fn(event)`` to run for every verified webhook event."""
        self.handlers.append(fn)
        return fn

    def checkout_url(self, **params: Any) -> str:
        """A signed ``href``: clicking it creates the Checkout Session and redirects to Stripe.

        ``success_url``/``cancel_url`` may be site paths; they are made absolute with the request
        host. ``{CHECKOUT_SESSION_ID}`` in ``success_url`` works as in Stripe's API.
        """
        return f"{self.path}/checkout?c={self._signer.sign(params)}"

    async def checkout(self, **params: Any) -> dict[str, Any]:
        """Create a Checkout Session directly (in an event handler, say); returns Stripe's answer."""
        return dict(await self._call("POST", "/v1/checkout/sessions", form=_stripe_form(params)))

    async def portal(self, customer: str, *, return_url: str = "") -> dict[str, Any]:
        """Create a customer portal session (manage cards, subscriptions, invoices); returns its ``url``."""
        return dict(
            await self._call(
                "POST", "/v1/billing_portal/sessions", form={"customer": customer, "return_url": return_url}
            )
        )

    async def customer(self, customer_id: str) -> dict[str, Any]:
        return dict(await self._call("GET", f"/v1/customers/{customer_id}"))

    async def _checkout(self, request: Request) -> Response:
        from .pages import error_page

        try:
            params = dict(self._signer.unsign(str(request.query_params.get("c", "")), max_age=24 * 60 * 60))
        except (InvalidToken, TypeError, ValueError):
            return error_page(self.app, request, 404, "This checkout link is not valid")
        origin = str(request.base_url).rstrip("/") + base_path(request)
        for key in ("success_url", "cancel_url"):
            if key in params and str(params[key]).startswith("/"):
                params[key] = origin + str(params[key])
        try:
            session = await self.checkout(**params)
        except StripeError:
            log.exception("could not create a Stripe Checkout Session")
            return error_page(self.app, request, 502, "Checkout is not available right now; please try again")
        return RedirectResponse(str(session["url"]), status_code=303)

    async def _webhook(self, request: Request) -> Response:
        payload = await request.body()
        if not self.webhook_secret:  # without a secret anyone could sign events: accept none
            log.error("a Stripe webhook arrived, but Stripe(webhook_secret=...) is not set")
            return JSONResponse({"error": "webhooks are not configured"}, status_code=503)
        try:
            event = self.verify(payload, request.headers.get("Stripe-Signature", ""))
        except ValueError:
            return JSONResponse({"error": "invalid signature"}, status_code=400)
        for fn in self.handlers:
            result = fn(event)
            if inspect.isawaitable(result):
                await result
        return JSONResponse({"received": True})

    def verify(self, payload: bytes, header: str) -> dict[str, Any]:
        """Check the ``Stripe-Signature`` header against the exact body; return the parsed event.

        Raises ``ValueError`` when the header is malformed, the timestamp is older than
        ``tolerance`` seconds, or the HMAC does not match — the request is then rejected.
        """
        if not self.webhook_secret:
            raise ValueError("no webhook secret is set")
        timestamp, signatures = "", []
        for entry in header.split(","):
            key, _, value = entry.partition("=")
            if key.strip() == "t":
                timestamp = value
            elif key.strip() == "v1":  # several while the endpoint's secret is being rolled
                signatures.append(value)
        try:
            age = abs(time.time() - float(timestamp))
        except ValueError:
            raise ValueError("malformed Stripe signature header") from None
        if not signatures or age > self.tolerance:
            raise ValueError("the Stripe signature is stale or missing")
        signed = f"{timestamp}.".encode() + payload
        expected = hmac.new(self.webhook_secret.encode(), signed, hashlib.sha256).hexdigest()
        if not any(hmac.compare_digest(expected, signature) for signature in signatures):
            raise ValueError("the Stripe signature does not match this payload")
        event: dict[str, Any] = json.loads(payload)
        return event

    async def _call(self, method: str, endpoint: str, *, form: dict[str, Any] | None = None) -> Any:
        try:
            return await _http.request(
                method,
                f"{self.api_url}{endpoint}",
                form={k: v for k, v in form.items() if v is not None} if form is not None else None,
                auth=(self.secret_key, ""),
            )
        except _http.HTTPError as e:
            message = e.body
            with contextlib.suppress(ValueError, KeyError, TypeError):
                message = json.loads(e.body)["error"]["message"]
            raise StripeError(e.status, str(message)) from e


def _stripe_form(params: dict[str, Any], prefix: str = "") -> dict[str, str]:
    """Flatten nested values into Stripe's ``a[b][c]=v`` form encoding."""
    form: dict[str, str] = {}
    for key, value in params.items():
        name = f"{prefix}[{key}]" if prefix else str(key)
        if isinstance(value, dict):
            form.update(_stripe_form(value, name))
        elif isinstance(value, (list, tuple)):
            for i, item in enumerate(value):
                form.update(_stripe_form({str(i): item}, name))
        elif value is not None:
            form[name] = str(value)
    return form
