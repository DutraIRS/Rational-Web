"""Passwords, JSON Web Tokens, signing, encryption and app cookies."""

import base64
import json
import time

import pytest

from rational import App, Page, Text
from rational.backend import Service, remote
from rational.security import (
    Box,
    InvalidToken,
    Signer,
    Tokens,
    hash_password,
    password_needs_rehash,
    verify_password,
)
from rational.testing import TestClient

SECRET = "x" * 40


def test_passwords_hash_with_a_salt_and_verify():
    stored = hash_password("correct horse")
    assert stored.startswith("scrypt$") and "correct horse" not in stored
    assert stored != hash_password("correct horse")  # a new salt each time
    assert verify_password("correct horse", stored)
    assert not verify_password("wrong", stored)
    assert not verify_password("x", "garbage") and not verify_password("x", "md5$1$2$3$aa$bb")
    assert not password_needs_rehash(stored) and password_needs_rehash("scrypt$1024$8$1$aa$bb")


def test_secrets_must_be_long():
    for make in (Signer, Tokens, Box):
        with pytest.raises(ValueError, match="at least 32 bytes"):
            make("short")


def test_tokens_round_trip_and_refuse_tampering():
    tokens = Tokens(SECRET, issuer="shop")
    token = tokens.issue("42", role="admin")
    claims = tokens.verify(token)
    assert claims["sub"] == "42" and claims["role"] == "admin" and claims["iss"] == "shop"

    header, payload, mac = token.split(".")
    forged = json.loads(base64.urlsafe_b64decode(payload + "=="))
    forged["role"] = "root"
    forged_payload = base64.urlsafe_b64encode(json.dumps(forged).encode()).rstrip(b"=").decode()
    none_header = base64.urlsafe_b64encode(b'{"alg":"none"}').rstrip(b"=").decode()
    for bad in (f"{header}.{forged_payload}.{mac}", f"{none_header}.{payload}.", "a.b", "", token + "x"):
        with pytest.raises(InvalidToken):
            tokens.verify(bad)
    with pytest.raises(InvalidToken, match="issuer"):
        Tokens(SECRET, issuer="other").verify(token)
    with pytest.raises(InvalidToken, match="signature"):
        Tokens("y" * 40).verify(token)
    with pytest.raises(InvalidToken, match="expired"):
        Tokens(SECRET, leeway=0).verify(Tokens(SECRET).issue("1", ttl=-5))


def test_signed_values_cannot_change_and_can_expire():
    signer = Signer(SECRET)
    token = signer.sign({"user": 1})
    assert signer.unsign(token) == {"user": 1}
    with pytest.raises(InvalidToken):
        signer.unsign(token[:-2] + "AA")
    with pytest.raises(InvalidToken):
        Signer(SECRET, salt="other purpose").unsign(token)
    old = Signer(SECRET)
    stale = old.sign("v")
    time.sleep(1.1)
    with pytest.raises(InvalidToken, match="expired"):
        old.unsign(stale, max_age=1)


def test_boxes_hide_and_protect_values():
    box = Box(SECRET)
    sealed = box.seal({"card": "4242"})
    assert "4242" not in sealed and box.open(sealed) == {"card": "4242"}
    assert box.seal("same") != box.seal("same")  # a fresh nonce each time
    for bad in (sealed[:-3] + "AAA", "short", Box("z" * 40).seal("x")):
        with pytest.raises(InvalidToken):
            box.open(bad)


class Prefs(Service):
    @remote()
    def remember(self, theme: str) -> None:
        cookies = self.context.cookies
        cookies.set("theme_choice", theme)
        cookies.set("cart", {"items": [1, 2]}, signed=True, max_age=3600)
        cookies.set("vault", {"token": "s3"}, encrypted=True)

    @remote(method="GET")
    def read(self) -> dict:
        cookies = self.context.cookies
        return {
            "theme": cookies.get("theme_choice"),
            "cart": cookies.get("cart", signed=True),
            "vault": cookies.get("vault", encrypted=True),
        }

    @remote()
    def forget(self) -> None:
        self.context.cookies.delete("cart")


def test_app_cookies_plain_signed_and_encrypted():
    app = App(secret_key=SECRET)
    app.service(Prefs)
    client = TestClient(app)
    response = client.http.post("/api/prefs/remember", json={"theme": "dark"})
    header = response.headers.get_list("set-cookie")
    assert any(h.startswith("theme_choice=dark") and "HttpOnly" in h and "SameSite=lax" in h for h in header)
    assert not any("s3" in h for h in header)  # the encrypted value is not readable
    assert client.http.get("/api/prefs/read").json() == {
        "theme": "dark",
        "cart": {"items": [1, 2]},
        "vault": {"token": "s3"},
    }

    forged = TestClient(app).http.get("/api/prefs/read", headers={"Cookie": "cart=e30.tampered"})
    assert forged.json()["cart"] is None  # a forged signed cookie reads as missing
    client.http.post("/api/prefs/forget", json={})


def test_cookie_rules():
    app = App(secret_key=SECRET)

    @app.page("/")
    class Home(Page):
        def render(self):
            with pytest.raises(ValueError, match="used by the framework"):
                self.context.cookies.set("rw_sid", "x")
            with pytest.raises(TypeError, match="plain cookies hold text"):
                self.context.cookies.set("n", 5)
            return Text("ok")

    assert TestClient(app).http.get("/").status_code == 200
    with pytest.raises(RuntimeError, match="need a secret"):
        _ = App(debug=False).secret_key
    assert len(App(debug=True).secret_key) >= 32  # made up in development


def test_bearer_tokens_sign_api_callers_in():
    tokens = Tokens(SECRET)
    app = App(api_only=True)
    app.authenticate(tokens.authenticator(lambda claims: {"id": claims["sub"]}))

    @app.service
    class Me(Service):
        @remote(method="GET", auth="required")
        def whoami(self) -> dict:
            return self.user

    client = TestClient(app)
    assert client.http.get("/api/me/whoami").status_code == 401
    ok = client.http.get("/api/me/whoami", headers={"Authorization": f"Bearer {tokens.issue('7')}"})
    assert ok.json() == {"id": "7"}
    bad = client.http.get("/api/me/whoami", headers={"Authorization": "Bearer nope"})
    assert bad.status_code == 401
