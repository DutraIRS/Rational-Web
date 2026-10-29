"""Secret-key rotation: sign with the newest key, still accept the older ones."""

import pytest

from rational import App, Page, Text
from rational.security import Box, InvalidToken, Signer, Tokens
from rational.testing import TestClient

NEW = "n" * 40
OLD = "o" * 40
OLDER = "d" * 40


def test_signer_accepts_old_keys_and_signs_with_the_new_one():
    current = Signer(NEW, extra_secrets=[OLD])
    previous = Signer(OLD)
    token = previous.sign({"user": 7})
    assert current.unsign(token) == {"user": 7}
    fresh = current.sign("x")
    assert Signer(NEW).unsign(fresh) == "x"  # signed with the newest key only
    with pytest.raises(InvalidToken):
        Signer(OLD).unsign(fresh)  # a new token does not verify with an old key


def test_signer_still_rejects_forged_values_under_rotation():
    current = Signer(NEW, extra_secrets=[OLD])
    with pytest.raises(InvalidToken):
        current.unsign("forged.value")


def test_tokens_rotate():
    current = Tokens(NEW, issuer="shop", extra_secrets=[OLD])
    old_token = Tokens(OLD, issuer="shop").issue("42")
    assert current.verify(old_token)["sub"] == "42"
    assert Tokens(NEW, issuer="shop").verify(current.issue("7"))["sub"] == "7"


def test_box_decrypts_old_seals_and_seals_with_the_new_key():
    current = Box(NEW, extra_secrets=[OLD])
    old_seal = Box(OLD).seal({"cart": [1, 2]})
    assert current.open(old_seal) == {"cart": [1, 2]}
    assert Box(NEW).open(current.seal("v")) == "v"


def test_app_cookies_survive_a_key_rotation():
    def app_with(keys):
        app = App(secret_key=keys[0], old_secret_keys=keys[1:])

        @app.page("/")
        class Home(Page):
            def mount(self):
                self.seen = self.context.cookies.get("prefs", signed=True, default=None)
                self.context.cookies.set("prefs", {"theme": "dark"}, signed=True)

            def render(self):
                return Text(f"theme={self.seen['theme']}" if self.seen else "none")

        return app

    old_client = TestClient(app_with([OLD]))
    old_client.http.get("/")
    cookie = old_client.http.cookies.get("prefs")

    rotated = TestClient(app_with([NEW, OLD]))
    rotated.http.cookies.set("prefs", cookie)
    assert "theme=dark" in rotated.http.get("/").text

    only_new = TestClient(app_with([NEW]))
    only_new.http.cookies.set("prefs", cookie)
    assert "none" in only_new.http.get("/").text  # once the old key is dropped, old cookies are gone
