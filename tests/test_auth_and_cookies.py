"""Passwords, JSON Web Tokens, signing, encryption and app cookies."""

import base64
import hashlib
import json
import time

import pytest

from rational import App, Button, Page, Text
from rational.backend import Service, remote
from rational.context import Context
from rational.security import (
    Box,
    InvalidToken,
    Signer,
    Tokens,
    ahash_password,
    averify_password,
    hash_password,
    password_needs_rehash,
    same_text,
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
    sealed = box.seal({"card": "4242 4242!"})
    assert "4242!" not in sealed and box.open(sealed) == {"card": "4242 4242!"}
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
        cookies.set("vault", {"token": "shh, secret!"}, encrypted=True)

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
    assert not any("secret!" in h for h in header)  # not readable; "!" never occurs in base64url
    assert client.http.get("/api/prefs/read").json() == {
        "theme": "dark",
        "cart": {"items": [1, 2]},
        "vault": {"token": "shh, secret!"},
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


def test_a_password_for_nobody_is_refused_after_the_same_work(monkeypatch):
    calls = []
    real = hashlib.scrypt
    monkeypatch.setattr(hashlib, "scrypt", lambda *args, **kwargs: calls.append(kwargs) or real(*args, **kwargs))
    assert verify_password("anything", None) is False
    assert len(calls) == 1 and calls[0]["n"] == 2**14  # what checking a real password costs


async def test_the_async_versions_keep_the_event_loop_free():
    stored = await ahash_password("correct horse")
    assert await averify_password("correct horse", stored)
    assert not await averify_password("wrong", stored)
    assert not await averify_password("x", None)


def test_passwords_hashed_with_stronger_settings_still_verify_and_get_rehashed():
    salt = b"s" * 16
    strong = hashlib.scrypt(b"pw", salt=salt, n=2**15, r=8, p=1, maxmem=256 * 1024 * 1024)
    stored = f"scrypt${2**15}$8$1${salt.hex()}${strong.hex()}"
    assert verify_password("pw", stored) and password_needs_rehash(stored)


def test_strange_stored_hashes_and_passwords_are_just_wrong():
    assert not verify_password("x", f"scrypt${2**80}$8$1$aa$bb")
    assert not verify_password("x", "scrypt$abc$8$1$aa$bb")
    assert verify_password("\ud800 lone surrogate", hash_password("\ud800 lone surrogate"))


@pytest.mark.parametrize("forged", ["payload.é", "é.é", "a.\u202e"])
def test_forged_values_with_non_ascii_characters_are_refused_not_a_crash(forged):
    with pytest.raises(InvalidToken):
        Signer(SECRET).unsign(forged)
    with pytest.raises(InvalidToken):
        Tokens(SECRET).verify(f"{_jwt_header()}.e30.{forged}")


def _jwt_header():
    return base64.urlsafe_b64encode(b'{"alg":"HS256","typ":"JWT"}').rstrip(b"=").decode()


def test_same_text_compares_any_text():
    assert same_text("é", "é") and not same_text("é", "e") and not same_text("a", "é")


def test_a_csrf_header_with_non_ascii_bytes_is_refused_not_a_crash():
    app = App()

    @app.page("/")
    class Home(Page):
        def render(self):
            return Button("Go", on_click=lambda: None)

    client = TestClient(app)
    page = client.open("/")
    body = {"v": 1, "page": page.manifest["page"], "rev": 0, "handler": "c0.1", "payload": {}}
    reply = client.http.post("/_rational/event", json=body, headers={"x-rw-csrf": b"\xc3\xa9"})
    assert reply.status_code == 403 and reply.json()["error"]["code"] == "csrf"


def test_tokens_honour_a_zero_lifetime():
    payload = Tokens(SECRET).issue("ada", ttl=0).split(".")[1]
    claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    assert claims["exp"] == claims["iat"]  # not the default lifetime


def test_every_rw_cookie_name_belongs_to_the_framework():
    context = Context(App(secret_key=SECRET))
    for name in ("rw_sid", "rw_oauth", "rw_anything"):
        with pytest.raises(ValueError, match="framework"):
            context.cookies.set(name, "x")
    with pytest.raises(ValueError, match="framework"):
        context.cookies.delete("rw_oauth")


def test_encrypted_cookies_follow_key_rotation(monkeypatch):
    pytest.importorskip("cryptography")
    old = App(secret_key="o" * 40).box("purpose").seal({"n": 1})
    monkeypatch.setenv("RATIONAL_OLD_SECRET_KEYS", f" {'o' * 40} , ")
    assert App(secret_key="n" * 40).box("purpose").open(old) == {"n": 1}


def test_a_forged_signed_cookie_with_non_ascii_bytes_reads_as_missing():
    app = App(secret_key=SECRET)

    @app.page("/")
    class Home(Page):
        def render(self):
            return Text(f"cart={self.context.cookies.get('cart', signed=True, default='none')}")

    reply = TestClient(app).http.get("/", headers={"cookie": "cart=abc.é".encode()})
    assert reply.status_code == 200 and "cart=none" in reply.text
