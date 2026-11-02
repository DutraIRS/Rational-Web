"""A small HTTPS client for the batteries that call other services (mail, CAPTCHA, OAuth, Stripe).

The standard library's ``urllib`` in a worker thread, so no HTTP package is required. Certificates
are verified, redirects are not followed, and every call has a time limit.
"""

from __future__ import annotations

import base64
import http.client
import json
import urllib.error
import urllib.request
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlencode, urlsplit

import anyio.to_thread

USER_AGENT = "rational-web"
MAX_ANSWER_BYTES = 8 * 1024 * 1024


class HTTPError(Exception):
    """The service answered with an error or nonsense, or could not be reached (``status`` 0)."""

    def __init__(self, status: int, body: str, url: str) -> None:
        super().__init__(f"{url} answered HTTP {status}: {body[:200]}" if status else f"{url}: {body}")
        self.status = status
        self.body = body


class _NoRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


_opener = urllib.request.build_opener(_NoRedirects())


async def request(
    method: str,
    url: str,
    *,
    json_body: Any = None,
    form: Mapping[str, str] | None = None,
    headers: Mapping[str, str] | None = None,
    auth: tuple[str, str] | None = None,
    timeout: float = 10.0,
) -> Any:
    """Send one request and return the decoded JSON answer (``None`` for an empty body).

    ``json_body`` and ``form`` set the body and its content type; ``auth`` is HTTP Basic.
    """
    local = urlsplit(url)
    if local.scheme != "https" and (local.scheme, local.hostname) != ("http", "127.0.0.1"):
        raise ValueError(f"refusing to send credentials over plain HTTP: {url}")
    data: bytes | None = None
    sent = {"User-Agent": USER_AGENT, "Accept": "application/json", **(headers or {})}
    if json_body is not None:
        data = json.dumps(json_body).encode()
        sent["Content-Type"] = "application/json"
    elif form is not None:
        data = urlencode(form).encode()
        sent["Content-Type"] = "application/x-www-form-urlencoded"
    if auth is not None:
        sent["Authorization"] = "Basic " + base64.b64encode(f"{auth[0]}:{auth[1]}".encode()).decode()
    req = urllib.request.Request(url, data=data, headers=sent, method=method)

    def send() -> Any:
        try:
            try:
                with _opener.open(req, timeout=timeout) as response:
                    status, raw = response.status, response.read(MAX_ANSWER_BYTES + 1)
            except urllib.error.HTTPError as e:
                raise HTTPError(e.code, e.read(MAX_ANSWER_BYTES).decode("utf-8", "replace"), url) from None
        except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException) as e:
            raise HTTPError(0, str(getattr(e, "reason", e)), url) from None
        if len(raw) > MAX_ANSWER_BYTES:
            raise HTTPError(status, "the answer is too large", url)
        text = raw.decode("utf-8", "replace")
        try:
            return json.loads(text) if text.strip() else None
        except ValueError:
            raise HTTPError(status, text, url) from None

    return await anyio.to_thread.run_sync(send)
