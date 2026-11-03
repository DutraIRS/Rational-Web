"""Keeping bots out: rate limits, form checks and CAPTCHAs.

::

    @limit("5/minute")                        # pages, event handlers and @remote methods
    async def send_message(self, form: Contact): ...

    Form(Input("Email", name="email"), HumanCheck(), Button("Send", type="submit"), on_submit=self.send)

    @human                                    # checked before the handler runs
    async def send(self, form: Contact): ...

``HumanCheck()`` adds a field people never see (bots fill it in), the time the form was shown
(bots submit at once) and, if the app has a :class:`Captcha`, its widget. ``@human`` rejects a
submit that fails any of these, or that lacks the fields. Limits are counted in memory by
default; ``app.limiter = Limiter(RedisSessionDriver(url=...))`` shares them between workers.
"""

from __future__ import annotations

import hashlib
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, TypeVar

from . import _http
from .component import Component
from .errors import FieldError, InvalidInput, RationalError
from .rendering.builder import h
from .rendering.nodes import Node
from .security import InvalidToken, Signer
from .state import State
from .styling.style import Style

if TYPE_CHECKING:
    from .app import App
    from .context import Context
    from .stores import SessionDriver

T = TypeVar("T")

HONEYPOT = "rw_website"  # a name bots like to fill in
STARTED = "rw_started"
_UNITS = {"second": 1, "minute": 60, "hour": 3600, "day": 86400}
_RATE = re.compile(r"^\s*(\d+)\s*/\s*(\d*)\s*(second|minute|hour|day)s?\s*$")


class TooManyRequests(RationalError):  # noqa: N818 - reads like the HTTP status it answers with
    status = 429
    code = "rate_limited"

    def __init__(self, retry_after: float) -> None:
        self.retry_after = max(1, int(retry_after + 0.999))
        self.headers = {"Retry-After": str(self.retry_after)}
        super().__init__(
            f"Too many requests; try again in {self.retry_after} s", details={"retry_after": self.retry_after}
        )


class NotHuman(InvalidInput):  # noqa: N818
    """A form submit failed the bot checks. The message gives bots nothing to learn from."""

    code = "not_human"

    def __init__(self, message: str = "Something went wrong; please try again") -> None:
        super().__init__(message)


@dataclass(frozen=True)
class Limit:
    count: int
    window: float
    per: Literal["ip", "user", "session"]


def limit(rate: str, *, per: Literal["ip", "user", "session"] = "ip") -> Callable[[T], T]:
    """Allow ``rate`` calls (``"5/minute"``, ``"100/hour"``, ``"10/15 minutes"``) per client.

    ``per``: the client's IP address, the signed-in user (else the IP) or the browser session.
    Decorates event handlers, ``@remote`` methods and ``Page`` classes.
    """
    match = _RATE.match(rate)
    if not match or int(match.group(1)) < 1:
        raise ValueError(f'rate must look like "5/minute" or "100/10 minutes", not {rate!r}')
    window = int(match.group(2) or 1) * _UNITS[match.group(3)]
    spec = Limit(int(match.group(1)), window, per)

    def decorator(target: T) -> T:
        target.__rw_limit__ = spec  # type: ignore[attr-defined]
        return target

    return decorator


class Limiter:
    """Counts calls per client and time window, in a session driver (memory or Redis)."""

    def __init__(self, driver: SessionDriver | None = None) -> None:
        from .stores import MemorySessionDriver

        self.driver: SessionDriver = MemorySessionDriver() if driver is None else driver

    async def check(self, target: Any, context: Context) -> None:
        """Count one call to ``target`` if it has a ``@limit``; raise ``TooManyRequests`` past it."""
        spec: Limit | None = getattr(target, "__rw_limit__", None)
        if spec is None:
            return
        now = time.time()
        slot = int(now // spec.window)
        name = getattr(target, "__qualname__", type(target).__name__)
        # Hashed: of a size any driver can store, and session ids stay out of the store's keys.
        who = hashlib.sha256(f"{name}:{_client(context, spec.per)}".encode()).hexdigest()
        key = f"rational:limit:{who}:{slot}"
        if await self._increment(key, int(spec.window) + 1) > spec.count:
            raise TooManyRequests((slot + 1) * spec.window - now)

    async def _increment(self, key: str, ttl: int) -> int:
        for _ in range(50):  # compare-and-swap: lose a race with another worker, read and try again
            raw = await self.driver.get(key)
            count = int(raw or 0) + 1
            if await self.driver.cas(key, raw, str(count).encode(), ttl):
                return count
        raise RuntimeError(f"could not update rate limit counter {key!r}")


def _ip(context: Context) -> str:
    connection = context.request if context.request is not None else context.websocket
    return connection.client.host if connection is not None and connection.client else "unknown"


def _client(context: Context, per: str) -> str:
    if per == "user" and context.user is not None:
        return "user:" + str(getattr(context.user, "id", context.user))
    if per == "session" and (session := context.peek_session()) is not None:
        return "session:" + session.id
    return "ip:" + _ip(context)


def human(handler: T) -> T:
    """Require a form submit to pass the bot checks of :class:`HumanCheck` before ``handler`` runs."""
    handler.__rw_human__ = True  # type: ignore[attr-defined]
    return handler


_OFF_SCREEN = Style(
    raw={"position": "absolute", "left": "-10000px", "width": "1px", "height": "1px", "overflow": "hidden"}
)


class HumanCheck(Component):
    """Put inside a ``Form`` whose submit handler has ``@human``."""

    started = State("")

    def mount(self) -> None:
        if not self.started:  # resuming a page keeps the time its form was first shown
            # Bound to this page view. Not to the session: signed values can be read, and its id stays in the cookie.
            self.started = _signer(self.context.app).sign([self._require_runtime().id, time.time()])

    def render(self) -> Node:
        app = self.context.app
        captcha = app.captcha if app is not None else None
        if captcha is not None:
            self._require_runtime().use_script(captcha.script)
        trap = h(
            "div",
            h("label", "Leave this empty", for_=HONEYPOT),
            h("input", type="text", id=HONEYPOT, name=HONEYPOT, tabindex="-1", autocomplete="off"),
            aria_hidden="true",
            style=_OFF_SCREEN,
        )
        widget = captcha.widget() if captcha is not None else None
        return h("div", trap, h("input", type="hidden", name=STARTED, value=self.started), widget)


def _signer(app: App | None) -> Signer:
    assert app is not None
    return app.signer("rational.bots.form")


async def check_submit(handler: Any, context: Context, form: dict[str, Any], page_id: str) -> None:
    """Remove the check fields from ``form``; for an ``@human`` handler, raise ``NotHuman`` unless they pass."""
    app = context.app
    assert app is not None
    trap, started = form.pop(HONEYPOT, None), form.pop(STARTED, None)
    token = form.pop(app.captcha.field, None) if app.captcha is not None else None
    if not getattr(handler, "__rw_human__", False):
        return
    if trap:
        raise NotHuman()
    if not isinstance(started, str):
        raise NotHuman("@human needs a HumanCheck() inside the form") if app.debug else NotHuman()
    try:
        shown_on, shown_at = _signer(app).unsign(started, max_age=24 * 3600)
        elapsed = time.time() - float(shown_at)
    except (InvalidToken, TypeError, ValueError):
        raise NotHuman("This form is too old; reload the page and try again") from None
    if shown_on != page_id or elapsed < app.min_form_seconds:
        raise NotHuman()
    if app.captcha is not None:
        await app.captcha.verify(token if isinstance(token, str) else "", _ip(context))


_HCAPTCHA_ORIGINS = ["https://hcaptcha.com", "https://*.hcaptcha.com"]
_PROVIDERS: dict[str, tuple[str, str, str, str, dict[str, list[str]]]] = {
    # name: (widget script, widget class, form field, verify URL, Content-Security-Policy sources)
    "turnstile": (
        "https://challenges.cloudflare.com/turnstile/v0/api.js",
        "cf-turnstile",
        "cf-turnstile-response",
        "https://challenges.cloudflare.com/turnstile/v0/siteverify",
        {
            "script-src": ["https://challenges.cloudflare.com"],
            "frame-src": ["https://challenges.cloudflare.com"],
        },
    ),
    "hcaptcha": (
        "https://js.hcaptcha.com/1/api.js",
        "h-captcha",
        "h-captcha-response",
        "https://api.hcaptcha.com/siteverify",
        {
            "script-src": _HCAPTCHA_ORIGINS,
            "frame-src": _HCAPTCHA_ORIGINS,
            "style-src": _HCAPTCHA_ORIGINS,
            "connect-src": _HCAPTCHA_ORIGINS,
        },
    ),
    "recaptcha": (
        "https://www.google.com/recaptcha/api.js",
        "g-recaptcha",
        "g-recaptcha-response",
        "https://www.google.com/recaptcha/api/siteverify",
        {
            "script-src": ["https://www.google.com", "https://www.gstatic.com"],
            "frame-src": ["https://www.google.com", "https://recaptcha.google.com"],
            "connect-src": ["https://www.google.com"],
        },
    ),
}


class Captcha:
    """A CAPTCHA in every :class:`HumanCheck`: Cloudflare Turnstile (free, private), hCaptcha or reCAPTCHA v2.

    The widget's script loads only on pages with a ``HumanCheck``, which client navigation always
    loads in full (the script sets up the widgets it finds as it loads). Its origins are added to
    the app's Content-Security-Policy. A ``HumanCheck`` must be in the page's first render.
    """

    def __init__(
        self, app: App, provider: Literal["turnstile", "hcaptcha", "recaptcha"], *, site_key: str, secret: str
    ) -> None:
        if provider not in _PROVIDERS:
            raise ValueError(f"provider must be one of {sorted(_PROVIDERS)}")
        self.script, self.css_class, self.field, self.verify_url, sources = _PROVIDERS[provider]
        self.provider = provider
        self.site_key = site_key
        self.secret = secret
        app.captcha = self
        for directive, origins in sources.items():
            app.csp_sources.setdefault(directive, []).extend(origins)

    def widget(self) -> Node:
        # data-rw-ignore: the provider's script fills this in, and a re-render must not wipe it.
        return h("div", class_=self.css_class, data_sitekey=self.site_key, data_rw_ignore=True)

    async def verify(self, token: str, ip: str | None = None) -> None:
        """Ask the provider whether ``token`` was earned by a person; raise ``FieldError`` if not."""
        if not token:
            raise FieldError("captcha", "Please confirm you are not a robot")
        form = {"secret": self.secret, "response": token}
        if ip and ip != "unknown":
            form["remoteip"] = ip
        try:
            answer = await _http.request("POST", self.verify_url, form=form)
        except _http.HTTPError:
            raise FieldError("captcha", "The check could not be completed; please try again") from None
        if not (isinstance(answer, dict) and answer.get("success") is True):
            raise FieldError("captcha", "Please confirm you are not a robot")
