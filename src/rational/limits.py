"""``Limits``: how much the server holds, accepts and allows, in one place (``App(limits=Limits(...))``).

Live page views and sessions are kept in process memory, and anyone can ask for a new one. The
defaults keep a flood of anonymous requests from pushing out the visitors who are actually using
the site:

* A visitor seen for the first time (no session cookie, or an expired one) gets a page view and a
  session in a separate, smaller pool. They join the main pool when the browser comes back with
  the cookie (its first event, or its next request), so requests that never send the cookie back
  only ever replace each other.
* One session holds at most ``pages_per_session`` page views (16); past that its own oldest one goes.
* One IP address may open at most ``new_visitor_pages`` interactive page views without a session
  cookie (``"60/minute"``); the rest are answered with 429, without a cookie. Behind a reverse proxy, run with
  ``--prod`` and list the proxy in ``FORWARDED_ALLOW_IPS`` so that the visitor's address is used,
  not the proxy's; ``None`` turns the limit off (when the proxy limits rates itself, say).
* With a persistent session store or page snapshots, the records of first-time visitors are kept
  for ``NEW_VISITOR_TTL`` (one hour) until the browser comes back, not for the whole session TTL.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .bots import Limit

NEW_VISITOR_TTL = 60 * 60  # seconds a first-time visitor's stored session and snapshot wait for the browser


@dataclass(frozen=True)
class Limits:
    """Sizes, rates and time limits for an :class:`~rational.App`.

    Pages
        ``page_ttl``: seconds an idle page view is kept. ``max_pages``: page views of returning
        visitors held in memory; ``max_new_pages``: page views of first-time visitors.
        ``pages_per_session``: page views one session may hold (its oldest goes first).
        ``new_visitor_pages``: interactive page views one IP address may open without a session
        cookie (a rate such as ``"60/minute"``, or ``None`` for no limit).
    Events
        ``event_burst`` events at once, then ``event_rate`` per second, per browser session.
        ``max_event_bytes``: the largest event body. ``handler_timeout``: seconds a handler may run
        (``None``: no limit; ``@timeout`` overrides it per handler).
    Requests
        ``max_request_bytes``: the largest request body (413 past it).
    """

    page_ttl: float = 30 * 60
    max_pages: int = 5_000
    max_new_pages: int = 1_000
    pages_per_session: int = 16
    new_visitor_pages: str | None = "60/minute"
    event_burst: int = 40
    event_rate: float = 20.0
    max_event_bytes: int = 64 * 1024
    max_request_bytes: int = 10 * 1024 * 1024
    handler_timeout: float | None = None

    def __post_init__(self) -> None:
        if self.handler_timeout is not None and self.handler_timeout <= 0:
            raise ValueError("handler_timeout must be a positive number of seconds or None")
        for name in ("max_pages", "max_new_pages", "pages_per_session", "event_burst"):
            if getattr(self, name) < 1:
                raise ValueError(f"{name} must be at least 1")
        self.new_visitor_limit  # noqa: B018 - a malformed rate fails now, not on the first visitor

    @property
    def new_visitor_limit(self) -> Limit | None:
        """``new_visitor_pages`` as a per-IP :class:`~rational.bots.Limit`."""
        from .bots import parse_rate  # bots imports the component layer, which needs this module

        return None if self.new_visitor_pages is None else parse_rate(self.new_visitor_pages)
