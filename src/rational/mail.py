"""Sending email: messages written as components, delivered by SMTP or an email API.

::

    mailer = Mailer(app, SMTP("smtp.example.com", username=..., password=...), sender="Shop <hi@shop.example>")

    class Welcome(Component):
        name: str

        def render(self):
            return Column(Heading(f"Welcome, {self.name}"), Text("Thanks for joining."), gap="md")

    await mailer.send("ada@example.com", "Welcome", Welcome(name="Ada"))

A component's ``Style`` is written into each element's ``style`` attribute, with theme colors and
sizes filled in, because most email clients ignore stylesheets and CSS variables (hover and
responsive variants are dropped). A plain-text version is made from the HTML. ``Console()`` prints
messages instead of sending them, for development; ``Memory()`` keeps them in ``outbox``, for tests.

Pass ``jobs=`` to send in the background, with retries, instead of while the request waits.
"""

from __future__ import annotations

import logging
import re
import smtplib
import ssl
from collections.abc import Callable, Sequence
from dataclasses import replace
from email.message import EmailMessage
from email.utils import make_msgid, parseaddr
from html import unescape
from html.parser import HTMLParser
from typing import TYPE_CHECKING, Any, Literal, Protocol

import anyio.to_thread
from pydantic import BaseModel, field_validator

from . import _http
from .component import Component
from .rendering.html import escape_attr, escape_text, to_html
from .rendering.nodes import Node
from .styling.compiler import StyleSheet
from .styling.style import Style
from .styling.theme import get_theme

if TYPE_CHECKING:
    from .app import App
    from .jobs import Jobs

log = logging.getLogger("rational.mail")


class Email(BaseModel):
    """One message, ready to send."""

    sender: str
    to: list[str]
    subject: str
    html: str
    text: str
    cc: list[str] = []
    bcc: list[str] = []
    reply_to: str | None = None

    @field_validator("sender", "to", "cc", "bcc", "subject", "reply_to")
    @classmethod
    def _one_line(cls, value: Any) -> Any:  # a line break in a header could add headers (injection)
        for item in value if isinstance(value, list) else [value]:
            if isinstance(item, str) and ("\r" in item or "\n" in item):
                raise ValueError("must be a single line")
        return value

    def message(self) -> EmailMessage:
        """The message as a standard-library ``EmailMessage`` (text and HTML alternatives)."""
        msg = EmailMessage()
        msg["From"] = self.sender
        msg["To"] = ", ".join(self.to)
        if self.cc:
            msg["Cc"] = ", ".join(self.cc)
        if self.reply_to:
            msg["Reply-To"] = self.reply_to
        msg["Subject"] = self.subject
        # The sender's domain: make_msgid() alone looks the machine's name up in DNS, which can hang.
        domain = parseaddr(self.sender)[1].rpartition("@")[2] or "localhost"
        msg["Message-ID"] = make_msgid(domain=domain)
        msg.set_content(self.text)
        msg.add_alternative(self.html, subtype="html")
        return msg


class MailBackend(Protocol):
    async def send(self, email: Email) -> None: ...


class SMTP:
    """Any SMTP server. ``security``: ``"starttls"`` (port 587), ``"tls"`` (port 465) or ``"none"``."""

    def __init__(
        self,
        host: str,
        port: int | None = None,
        *,
        username: str | None = None,
        password: str | None = None,
        security: Literal["starttls", "tls", "none"] = "starttls",
        timeout: float = 15.0,
    ) -> None:
        if security not in ("starttls", "tls", "none"):
            raise ValueError('security must be "starttls", "tls" or "none"')
        self.host = host
        self.port = port or {"starttls": 587, "tls": 465, "none": 25}[security]
        self.username = username
        self.password = password
        self.security = security
        self.timeout = timeout

    async def send(self, email: Email) -> None:
        await anyio.to_thread.run_sync(self._send, email)

    def _send(self, email: Email) -> None:
        context = ssl.create_default_context()
        server: smtplib.SMTP
        if self.security == "tls":
            server = smtplib.SMTP_SSL(self.host, self.port, timeout=self.timeout, context=context)
        else:
            server = smtplib.SMTP(self.host, self.port, timeout=self.timeout)
        with server:
            if self.security == "starttls":
                server.starttls(context=context)
            if self.username is not None:
                server.login(self.username, self.password or "")
            server.send_message(email.message(), to_addrs=[*email.to, *email.cc, *email.bcc])


class Resend:
    """The Resend API (resend.com)."""

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    async def send(self, email: Email) -> None:
        body: dict[str, Any] = {"from": email.sender, "to": email.to, "subject": email.subject}
        body |= {"html": email.html, "text": email.text, "cc": email.cc, "bcc": email.bcc}
        if email.reply_to:
            body["reply_to"] = email.reply_to
        headers = {"Authorization": f"Bearer {self.api_key}"}
        await _http.request("POST", "https://api.resend.com/emails", json_body=body, headers=headers)


class Postmark:
    """The Postmark API (postmarkapp.com)."""

    def __init__(self, server_token: str, *, stream: str = "outbound") -> None:
        self.server_token = server_token
        self.stream = stream

    async def send(self, email: Email) -> None:
        body: dict[str, Any] = {"From": email.sender, "To": ", ".join(email.to), "Subject": email.subject}
        body |= {"HtmlBody": email.html, "TextBody": email.text, "MessageStream": self.stream}
        if email.cc:
            body["Cc"] = ", ".join(email.cc)
        if email.bcc:
            body["Bcc"] = ", ".join(email.bcc)
        if email.reply_to:
            body["ReplyTo"] = email.reply_to
        headers = {"X-Postmark-Server-Token": self.server_token}
        await _http.request("POST", "https://api.postmarkapp.com/email", json_body=body, headers=headers)


class Console:
    """Logs each message instead of sending it (development)."""

    async def send(self, email: Email) -> None:
        log.warning("email to %s: %s\n\n%s", ", ".join(email.to), email.subject, email.text)


class Memory:
    """Keeps each message in ``outbox`` instead of sending it (tests)."""

    def __init__(self) -> None:
        self.outbox: list[Email] = []

    async def send(self, email: Email) -> None:
        self.outbox.append(email)


class Mailer:
    """Composes messages and hands them to ``backend``; with ``jobs``, in the background with retries."""

    def __init__(self, app: App, backend: MailBackend, *, sender: str, jobs: Jobs | None = None) -> None:
        self.app = app
        self.backend = backend
        self.sender = sender
        self._deliver = None
        if jobs is not None:
            self._deliver = jobs.job(name="rational.mail.deliver", retries=5, backoff=4.0)(self._deliver_now)

    async def send(
        self,
        to: str | Sequence[str],
        subject: str,
        body: Component | Node | str,
        *,
        text: str | None = None,
        cc: Sequence[str] = (),
        bcc: Sequence[str] = (),
        reply_to: str | None = None,
    ) -> None:
        """Send ``body`` (a component, an element tree or trusted HTML) to ``to``.

        ``text`` replaces the plain-text version made from the HTML.
        """
        email = await self.compose(to, subject, body, text=text, cc=cc, bcc=bcc, reply_to=reply_to)
        if self._deliver is not None:
            await self._deliver.enqueue(email.model_dump())
        else:
            await self.backend.send(email)

    async def compose(
        self,
        to: str | Sequence[str],
        subject: str,
        body: Component | Node | str,
        *,
        text: str | None = None,
        cc: Sequence[str] = (),
        bcc: Sequence[str] = (),
        reply_to: str | None = None,
    ) -> Email:
        """The message ``send`` would deliver, without sending it."""
        html = body if isinstance(body, str) else await render_email(self.app, body, subject)
        return Email(
            sender=self.sender,
            to=[to] if isinstance(to, str) else list(to),
            subject=subject,
            html=html,
            text=text if text is not None else html_to_text(html),
            cc=list(cc),
            bcc=list(bcc),
            reply_to=reply_to,
        )

    async def _deliver_now(self, email: dict[str, Any]) -> None:
        await self.backend.send(Email.model_validate(email))


class _InlineSheet(StyleSheet):
    """Remembers each class's plain declarations, to write them into ``style`` attributes."""

    def __init__(self, sheet_compiler: Any) -> None:
        super().__init__(sheet_compiler)
        self.declarations: dict[str, str] = {}

    def use(self, style: Style) -> str:
        name = super().use(style)
        self.declarations.setdefault(name, self.compiler.declarations(style))
        return name


_VAR = re.compile(r"var\(--rw-([a-z0-9-]+)(?:,[^()]*)?\)")


class _Tree(Component):
    """Lets a plain element tree (``Column(...)``) render like a component."""

    tree: Any

    def render(self) -> Any:
        return self.tree


async def render_email(app: App, body: Component | Node, subject: str) -> str:
    """``body`` as a complete HTML email, its styles inlined and theme values filled in."""
    from .context import Context
    from .pages import _without_component_ids
    from .runtime import PageRuntime

    sheet = _InlineSheet(app.compiler)
    component = body if isinstance(body, Component) else _Tree(tree=body)
    runtime = PageRuntime(component, Context(app), sheet)  # type: ignore[arg-type]  # any component renders
    tokens: dict[str, str] = {}
    for name, value in re.findall(r"--rw-([a-z0-9-]+):([^;}]+)", (app.theme or get_theme("modern")).css("light")):
        tokens.setdefault(name, value.strip())  # the light values: the first definition of each token

    def resolve(css: str) -> str:
        for _ in range(5):  # tokens may refer to other tokens
            css, n = _VAR.subn(lambda m: tokens.get(m.group(1), m.group(0)), css)
            if not n:
                break
        return css

    root = _inline(_without_component_ids(await runtime.render_page()), sheet.declarations, resolve)
    body_style = resolve("margin:0;padding:24px;background:var(--rw-color-background);")
    body_style += resolve("color:var(--rw-color-on-background);font-family:var(--rw-font-body)")
    return (
        f'<!doctype html><html lang="{escape_attr(app.lang)}"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f'<title>{escape_text(subject)}</title></head><body style="{escape_attr(body_style)}">'
        f"{to_html(root)}</body></html>"
    )


def _inline(node: Any, declarations: dict[str, str], resolve: Callable[[str], str]) -> Any:
    if not isinstance(node, Node):
        return node
    classes = str(node.attr("class") or "").split()
    styles = "".join(declarations.get(c, "") for c in classes)
    rest = [c for c in classes if c not in declarations]
    attrs = [(n, v) for n, v in node.attrs if n not in ("class", "style")]
    if rest:
        attrs.insert(0, ("class", " ".join(rest)))
    if styles or node.attr("style"):
        attrs.append(("style", resolve(styles + str(node.attr("style") or ""))))  # escaped when written
    kids = tuple(_inline(c, declarations, resolve) for c in node.children)
    return replace(node, attrs=tuple(attrs), children=kids)


_BLOCKS = {"p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "tr", "table", "section", "header", "footer"}


class _Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip = 0
        self.href: list[str | None] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("head", "style", "script"):
            self.skip += 1
        elif tag in _BLOCKS:
            self.parts.append("\n\n")
        elif tag == "li":
            self.parts.append("\n- ")
        elif tag == "br":
            self.parts.append("\n")
        elif tag == "a":
            self.href.append(dict(attrs).get("href"))

    def handle_endtag(self, tag: str) -> None:
        if tag in ("head", "style", "script"):
            self.skip -= 1
        elif tag in _BLOCKS:
            self.parts.append("\n\n")
        elif tag == "a" and self.href:
            href = self.href.pop()
            if href and not href.startswith("#"):
                self.parts.append(f" ({href})")

    def handle_data(self, data: str) -> None:
        if not self.skip:
            self.parts.append(re.sub(r"\s+", " ", data))


def html_to_text(html: str) -> str:
    """A readable plain-text version of an HTML message: paragraphs kept, links written out."""
    parser = _Text()
    parser.feed(html)
    lines = (line.strip() for line in unescape("".join(parser.parts)).splitlines())
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip() + "\n"
