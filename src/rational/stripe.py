"""Stripe: Checkout, the customer portal and signed webhooks, without the SDK.

::

    stripe = Stripe(app, secret_key=STRIPE_SECRET_KEY, webhook_secret=STRIPE_WEBHOOK_SECRET,
                    base_url="https://shop.example")

    @app.page("/upgrade")
    class Upgrade(Page):
        def render(self):
            return ButtonLink("Upgrade", href=stripe.checkout_url(
                self.context,                     # only this visitor's browser can use the link
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
Stripe and redirects the browser there, so no API call happens while rendering. Given the page's
context, the link works only in this visitor's browser session; it expires after ``link_ttl``
seconds (an hour) either way. To create the session from a ``POST`` instead, call
:meth:`Stripe.checkout` in an event handler and ``raise redirect(session["url"])``.

Webhook calls are verified against the ``Stripe-Signature`` header (timestamp plus HMAC of the
exact body) before any handler runs, so forged calls and calls older than ``tolerance`` (five
minutes) are rejected. A call replayed within those five minutes is not, and Stripe itself may send
an event more than once: make handlers idempotent (record ``event["id"]``).
"""

from __future__ import annotations

import contextlib
import hashlib
import hmac
import inspect
import json
import logging
import math
import time
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

from fastapi import Request, Response
from fastapi.responses import JSONResponse, RedirectResponse

from . import _http
from .security import InvalidToken, Signer, same_text

if TYPE_CHECKING:
    from .app import App
    from .context import Context

_API = "https://api.stripe.com"
_URL_PARAMS = ("success_url", "cancel_url", "return_url")
log = logging.getLogger("rational.stripe")


class StripeError(Exception):
    """Stripe answered with an error status."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(f"Stripe answered HTTP {status}: {message}")
        self.status = status
        self.message = message


Handler = Callable[[dict[str, Any]], Any | Awaitable[Any]]


class Stripe:
    """Adds ``{path}/checkout`` and ``{path}/webhook`` routes to ``app``; talks to the REST API.

    ``base_url`` is the site's public address, which site paths given as ``success_url``,
    ``cancel_url`` or ``return_url`` are made absolute with. Without it those must be absolute URLs,
    except in ``--dev``, where a checkout link uses the address of the request. (Not in production:
    anyone can send a request with another ``Host`` header and pass on the Stripe page it leads to.)
    """

    def __init__(
        self,
        app: App,
        *,
        secret_key: str,
        webhook_secret: str = "",  # needed to accept webhooks: without it every webhook call is refused
        path: str = "/stripe",
        tolerance: float = 300.0,
        api_url: str = _API,
        base_url: str = "",
        link_ttl: float = 60 * 60,
    ) -> None:
        self.app = app
        self.link_ttl = link_ttl
        self.base_url = base_url.rstrip("/")
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

    def checkout_url(self, context: Context | None = None, /, **params: Any) -> str:
        """A signed ``href``: clicking it creates the Checkout Session and redirects to Stripe.

        Pass the page's ``self.context`` to bind the link to this visitor's session, so that it
        does not work for anyone who finds it in a log or a shared screenshot; a link that names a
        ``customer`` must be bound. Links expire after ``link_ttl`` seconds. ``success_url`` and
        ``cancel_url`` may be site paths with ``Stripe(base_url=...)``; ``{CHECKOUT_SESSION_ID}``
        in ``success_url`` works as in Stripe's API.
        """
        if context is None and "customer" in params:
            raise TypeError(
                "a checkout link that names a customer would work for anyone holding it: "
                "pass the page's context first, stripe.checkout_url(self.context, customer=...)"
            )
        if not self.base_url and not self.app.debug and any(_site_path(params.get(k)) for k in _URL_PARAMS):
            raise ValueError(
                "site paths in a checkout link need Stripe(base_url=...), the site's public address: "
                "a request's Host header can be forged"
            )
        bound = _session_tag(context.session.id) if context is not None else None
        return f"{self.path}/checkout?c={self._signer.sign({'p': params, 's': bound})}"

    async def checkout(self, **params: Any) -> dict[str, Any]:
        """Create a Checkout Session directly (in an event handler, say); returns Stripe's answer."""
        form = _stripe_form(self._absolute(params))
        return dict(await self._call("POST", "/v1/checkout/sessions", form=form))

    async def portal(self, customer: str, *, return_url: str | None = None) -> dict[str, Any]:
        """Create a customer portal session (manage cards, subscriptions, invoices); returns its ``url``."""
        form = self._absolute({"customer": customer, "return_url": return_url})
        return dict(await self._call("POST", "/v1/billing_portal/sessions", form=form))

    async def customer(self, customer_id: str) -> dict[str, Any]:
        return dict(await self._call("GET", f"/v1/customers/{quote(customer_id, safe='')}"))

    def _absolute(self, params: dict[str, Any], origin: str = "") -> dict[str, Any]:
        """``params`` with site paths made absolute: Stripe redirects to them from its own site."""
        origin = self.base_url or origin
        return {
            key: origin + value if key in _URL_PARAMS and origin and str(value).startswith("/") else value
            for key, value in params.items()
        }

    async def _checkout(self, request: Request) -> Response:
        from .pages import error_page

        if _speculative(request):  # a prefetch, or an <img> on another site: not someone who clicked
            return Response(status_code=503, headers={"Cache-Control": "no-store"})
        try:
            signed = self._signer.unsign(str(request.query_params.get("c", "")), max_age=self.link_ttl)
            params, bound = dict(signed["p"]), signed["s"]
        except (InvalidToken, TypeError, ValueError, KeyError):
            return error_page(self.app, request, 404, "This checkout link is not valid or has expired")
        if bound is not None:
            visitor = await self.app.load_session(request)
            if visitor is None or not same_text(_session_tag(visitor.id), str(bound)):
                return error_page(self.app, request, 403, "This checkout link was made for another visitor")
        origin = str(request.base_url).rstrip("/") if self.app.debug else ""
        try:
            session = await self.checkout(**self._absolute(params, origin))
            return RedirectResponse(str(session["url"]), status_code=303)
        except (StripeError, KeyError, TypeError, ValueError):
            log.exception("could not create a Stripe Checkout Session")
            return error_page(self.app, request, 502, "Checkout is not available right now; please try again")

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
        if not math.isfinite(age) or not signatures or age > self.tolerance:
            raise ValueError("the Stripe signature is stale or missing")
        signed = f"{timestamp}.".encode() + payload
        expected = hmac.new(self.webhook_secret.encode(), signed, hashlib.sha256).hexdigest()
        if not any(same_text(expected, signature) for signature in signatures):
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


def _site_path(value: Any) -> bool:
    return isinstance(value, str) and value.startswith("/")


def _session_tag(session_id: str) -> str:
    """What a bound link carries: signed values can be read, so not the session id itself."""
    return hashlib.sha256(f"rational.stripe:{session_id}".encode()).hexdigest()[:32]


def _speculative(request: Request) -> bool:
    """A request no person asked for: a prefetch or prerender, or a fetch for something other than a page."""
    purpose = (request.headers.get("sec-purpose", "") + request.headers.get("purpose", "")).lower()
    dest = request.headers.get("sec-fetch-dest")
    return "prefetch" in purpose or "prerender" in purpose or (dest is not None and dest != "document")


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
        elif isinstance(value, bool):
            form[name] = "true" if value else "false"
        elif value is not None:
            form[name] = str(value)
    return form
