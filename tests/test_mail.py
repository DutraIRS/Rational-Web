"""Email: components rendered for mail clients, backends, background delivery, and the HTTP helper."""

import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from pydantic import ValidationError

from rational import App, Column, Component, Heading, Link, Text, _http
from rational.jobs import Jobs
from rational.mail import SMTP, Console, Email, Mailer, Memory, Postmark, Resend, html_to_text


class Welcome(Component):
    name: str

    def render(self):
        return Column(
            Heading(f"Welcome, {self.name}"),
            Text("Thanks for joining."),
            Link("Open the app", href="https://shop.example/app"),
            gap="md",
        )


async def test_components_become_emails_with_inline_styles_and_a_text_version():
    outbox = Memory()
    mailer = Mailer(App(), outbox, sender="Shop <hi@shop.example>")
    await mailer.send("ada@example.com", "Welcome", Welcome(name="Ada"), bcc=["log@shop.example"])
    email = outbox.outbox[0]
    assert email.to == ["ada@example.com"] and email.sender == "Shop <hi@shop.example>"
    assert "<title>Welcome</title>" in email.html and "Welcome, Ada" in email.html
    assert 'style="display:flex;flex-direction:column;gap:16px;"' in email.html
    assert "color:#" in email.html  # theme colors filled in: mail clients ignore CSS variables
    assert "var(" not in email.html and 'class="rw-' not in email.html and "data-rw" not in email.html
    assert "&quot;Segoe UI&quot;" in email.html  # quotes in token values stay inside the attribute
    assert email.text == "Welcome, Ada\n\nThanks for joining.\n\nOpen the app (https://shop.example/app)\n"


def test_messages_have_both_versions_and_no_header_injection():
    email = Email(sender="a@x.example", to=["b@x.example"], subject="Hi", html="<p>Hi</p>", text="Hi", bcc=["c@x"])
    msg = email.message()
    assert msg.is_multipart() and [p.get_content_type() for p in msg.iter_parts()] == ["text/plain", "text/html"]
    assert msg["Bcc"] is None and msg["Message-ID"]  # blind copies never appear in the headers
    for field in ({"subject": "Hi\nBcc: everyone@x"}, {"to": ["b@x\r\nBcc: e@x"]}, {"reply_to": "r@x\n"}):
        with pytest.raises(ValidationError, match="single line"):
            Email(**{**email.model_dump(), **field})


def test_html_to_text_keeps_paragraphs_lists_and_links():
    html = "<html><head><style>p{}</style></head><body><h1>Title</h1><p>One &amp; two</p>"
    html += '<ul><li>A</li><li>B</li></ul><a href="https://x.example">Go</a><a href="#top">Top</a></body></html>'
    assert html_to_text(html) == "Title\n\nOne & two\n\n- A\n- B\n\nGo (https://x.example)Top\n"


async def test_background_delivery_goes_through_jobs():
    outbox, jobs = Memory(), Jobs()
    mailer = Mailer(App(), outbox, sender="hi@shop.example", jobs=jobs)
    await mailer.send(["a@x.example", "b@x.example"], "Raw", "<p>Trusted <b>HTML</b></p>", text="Plain")
    assert outbox.outbox == []  # queued, not sent yet
    assert await jobs.run_pending() == 1
    assert outbox.outbox[0].html == "<p>Trusted <b>HTML</b></p>" and outbox.outbox[0].text == "Plain"


async def test_api_backends_send_json(monkeypatch):
    calls = []

    async def fake_request(method, url, **kwargs):
        calls.append((url, kwargs["json_body"], kwargs["headers"]))

    monkeypatch.setattr(_http, "request", fake_request)
    email = Email(sender="a@x", to=["b@x"], subject="S", html="<p>H</p>", text="H", cc=["c@x"], reply_to="r@x")
    await Resend("re_key").send(email)
    await Postmark("pm_token").send(email.model_copy(update={"bcc": ["d@x"]}))
    (resend_url, resend, resend_headers), (pm_url, pm, pm_headers) = calls
    assert resend_url == "https://api.resend.com/emails" and resend_headers["Authorization"] == "Bearer re_key"
    assert resend["to"] == ["b@x"] and resend["reply_to"] == "r@x" and resend["text"] == "H"
    assert pm_url == "https://api.postmarkapp.com/email" and pm_headers["X-Postmark-Server-Token"] == "pm_token"
    assert pm["To"] == "b@x" and pm["Cc"] == "c@x" and pm["Bcc"] == "d@x" and pm["ReplyTo"] == "r@x"


async def test_smtp_uses_starttls_login_and_every_recipient(monkeypatch):
    sessions = []

    class FakeSMTP:
        def __init__(self, host, port, timeout, **kwargs):
            sessions.append(self)
            self.address, self.steps = (host, port), []

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self.steps.append("quit")

        def starttls(self, context):
            self.steps.append("starttls")

        def login(self, user, password):
            self.steps.append(("login", user, password))

        def send_message(self, msg, to_addrs):
            self.steps.append(("send", msg["Subject"], to_addrs))

    monkeypatch.setattr("smtplib.SMTP", FakeSMTP)
    monkeypatch.setattr("smtplib.SMTP_SSL", FakeSMTP)
    email = Email(sender="a@x", to=["b@x"], subject="S", html="<p>H</p>", text="H", cc=["c@x"], bcc=["d@x"])
    await SMTP("smtp.example", username="u", password="p").send(email)
    await SMTP("smtp.example", security="tls").send(email)
    first, second = sessions
    assert first.address == ("smtp.example", 587) and second.address == ("smtp.example", 465)
    assert first.steps == ["starttls", ("login", "u", "p"), ("send", "S", ["b@x", "c@x", "d@x"]), "quit"]
    assert second.steps == [("send", "S", ["b@x", "c@x", "d@x"]), "quit"]
    with pytest.raises(ValueError, match="security"):
        SMTP("x", security="ssl")  # type: ignore[arg-type]


async def test_console_logs_messages(caplog):
    with caplog.at_level(logging.WARNING, "rational.mail"):
        await Console().send(Email(sender="a@x", to=["b@x"], subject="Hello", html="", text="Body"))
    assert "email to b@x: Hello" in caplog.text and "Body" in caplog.text


@pytest.fixture
def local_server():
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802 - the http.server API
            length = int(self.headers["Content-Length"])
            body = self.rfile.read(length).decode()
            if self.path == "/fail":
                self.send_response(422)
                self.end_headers()
                self.wfile.write(b'{"error":"nope"}')
                return
            if self.path == "/moved":
                self.send_response(302)
                self.send_header("Location", "https://evil.example/")
                self.end_headers()
                return
            self.send_response(200)
            self.end_headers()
            echo = {"body": body, "type": self.headers["Content-Type"], "auth": self.headers.get("Authorization")}
            self.wfile.write(json.dumps(echo).encode())

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


async def test_http_helper_sends_json_and_forms_and_reports_errors(local_server):
    echo = await _http.request("POST", local_server + "/", json_body={"a": 1}, auth=("user", "pw"))
    assert json.loads(echo["body"]) == {"a": 1} and echo["type"] == "application/json"
    assert echo["auth"] == "Basic dXNlcjpwdw=="
    echo = await _http.request("POST", local_server + "/", form={"b": "2 3"})
    assert echo["body"] == "b=2+3" and echo["type"] == "application/x-www-form-urlencoded"
    with pytest.raises(_http.HTTPError) as failed:
        await _http.request("POST", local_server + "/fail", json_body={})
    assert failed.value.status == 422 and "nope" in failed.value.body
    with pytest.raises(_http.HTTPError) as moved:  # redirects are not followed
        await _http.request("POST", local_server + "/moved", json_body={})
    assert moved.value.status == 302
    with pytest.raises(_http.HTTPError) as unreachable:
        await _http.request("POST", "http://127.0.0.1:9/", json_body={}, timeout=2)
    assert unreachable.value.status == 0
    with pytest.raises(ValueError, match="plain HTTP"):
        await _http.request("POST", "http://api.example/", json_body={})
