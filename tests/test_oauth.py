"""Sign-in with OAuth 2 / OpenID Connect providers, against a fake provider."""

import base64
import hashlib
from urllib.parse import parse_qs, urlsplit

import pytest

from rational import App, Page, Text, _http
from rational.oauth import OAuth, github, google, microsoft, oidc
from rational.testing import TestClient


class FakeProvider:
    """Answers discovery, token and profile requests like Google (and GitHub's API)."""

    def __init__(self):
        self.challenge = None
        self.token_forms = []
        self.fail_token = False

    async def __call__(self, method, url, *, form=None, headers=None, **kwargs):
        if url.endswith("/.well-known/openid-configuration"):
            return {
                "authorization_endpoint": "https://idp.example/authorize",
                "token_endpoint": "https://idp.example/token",
                "userinfo_endpoint": "https://idp.example/userinfo",
            }
        if url in ("https://idp.example/token", "https://github.com/login/oauth/access_token") or "token" in url:
            self.token_forms.append(form)
            if self.fail_token:
                raise _http.HTTPError(400, "invalid_grant", url)
            return {"access_token": "at-123", "token_type": "Bearer"}
        assert headers["Authorization"] == "Bearer at-123"
        if url == "https://api.github.com/user":
            return {"id": 42, "login": "ada", "name": None, "avatar_url": "https://avatars.example/ada"}
        if url == "https://api.github.com/user/emails":
            return [
                {"email": "old@x.example", "primary": False, "verified": True},
                {"email": "ada@x.example", "primary": True, "verified": True},
            ]
        return {"sub": "g-1", "email": "ada@x.example", "email_verified": True, "name": "Ada", "picture": None}


def oauth_app(provider, on_login=None):
    app = App(secret_key="k" * 40)
    signed_in = []

    async def default_login(context, person):
        signed_in.append(person)
        return {"id": person.id, "email": person.email}

    oauth = OAuth(app, base_url="https://shop.example/", on_login=on_login or default_login)
    oauth.add(provider)

    @app.page("/orders", auth="required")
    class Orders(Page):
        def render(self):
            return Text(f"Orders of {self.context.user['email']}")

    return app, oauth, signed_in


def start(client, url):
    response = client.http.get(url, follow_redirects=False)
    assert response.status_code == 303
    location = urlsplit(response.headers["location"])
    return location, {k: v[0] for k, v in parse_qs(location.query).items()}


def callback(client, provider, **params):
    return client.http.get(f"/auth/{provider}/callback", params=params, follow_redirects=False)


@pytest.fixture
def fake(monkeypatch):
    provider = FakeProvider()
    monkeypatch.setattr(_http, "request", provider)
    return provider


def test_signing_in_with_an_openid_provider(fake):
    app, oauth, signed_in = oauth_app(google(client_id="cid", client_secret="secret"))
    client = TestClient(app)
    assert oauth.login_url("google", next="/orders") == "/auth/google/login?next=%2Forders"
    location, params = start(client, oauth.login_url("google", next="/orders"))
    assert location.netloc == "idp.example" and location.path == "/authorize"
    assert params["redirect_uri"] == "https://shop.example/auth/google/callback"
    assert params["scope"] == "openid email profile" and params["code_challenge_method"] == "S256"
    assert params["client_id"] == "cid" and params["state"] and params["nonce"]

    done = callback(client, "google", code="the-code", state=params["state"])
    assert done.status_code == 303 and done.headers["location"] == "/orders"
    form = fake.token_forms[0]
    assert form["code"] == "the-code" and form["client_secret"] == "secret"
    digest = hashlib.sha256(form["code_verifier"].encode()).digest()
    assert base64.urlsafe_b64encode(digest).rstrip(b"=").decode() == params["code_challenge"]  # PKCE holds
    assert signed_in[0].email == "ada@x.example" and signed_in[0].email_verified and signed_in[0].id == "g-1"
    assert "Orders of ada@x.example" in client.http.get("/orders").text

    again = callback(client, "google", code="the-code", state=params["state"])
    assert again.status_code == 400  # the state is used up


def test_forged_cancelled_and_refused_sign_ins(fake):
    app, oauth, _ = oauth_app(google(client_id="cid", client_secret="s"), on_login=lambda ctx, person: None)
    client = TestClient(app)
    assert callback(client, "google", code="c", state="x").status_code == 400  # no sign-in started here

    _, params = start(client, "/auth/google/login")
    assert callback(client, "google", code="c", state="forged").status_code == 400
    _, params = start(client, "/auth/google/login")
    cancelled = callback(client, "google", error="access_denied", state=params["state"])
    assert cancelled.status_code == 400 and "cancelled" in cancelled.text
    _, params = start(client, "/auth/google/login")
    refused = callback(client, "google", code="c", state=params["state"])
    assert refused.status_code == 403 and "cannot sign in" in refused.text
    _, params = start(client, "/auth/google/login")
    assert callback(client, "github", code="c", state=params["state"]).status_code == 400  # another provider
    assert client.http.get("/auth/nope/login", follow_redirects=False).status_code == 404


def test_next_must_stay_on_the_site_and_provider_errors_are_reported(fake):
    app, _, _ = oauth_app(google(client_id="cid", client_secret="s"))
    client = TestClient(app)
    _, params = start(client, "/auth/google/login?next=https://evil.example/")
    assert callback(client, "google", code="c", state=params["state"]).headers["location"] == "/"

    fake.fail_token = True
    _, params = start(client, "/auth/google/login")
    failed = callback(client, "google", code="c", state=params["state"])
    assert failed.status_code == 502 and "Could not sign in with google" in failed.text


def test_github_uses_its_api_for_the_verified_primary_email(fake):
    app, _, signed_in = oauth_app(github(client_id="gh", client_secret="s"))
    client = TestClient(app)
    location, params = start(client, "/auth/github/login")
    assert location.netloc == "github.com" and params["scope"] == "read:user user:email"
    callback(client, "github", code="c", state=params["state"])
    person = signed_in[0]
    assert (person.id, person.email, person.email_verified, person.name) == ("42", "ada@x.example", True, "ada")


def test_microsoft_and_custom_providers_are_configured_without_discovery_calls(fake):
    provider = microsoft(client_id="ms", client_secret="s", tenant="organizations")
    assert provider.authorize_url == "https://login.microsoftonline.com/organizations/oauth2/v2.0/authorize"
    custom = oidc("okta", "https://dev.okta.example", client_id="o", client_secret="s", scopes=("groups",))
    assert custom.scopes == ("openid", "email", "profile", "groups") and custom.authorize_url == ""
