"""Sign-in with Google, GitHub, Microsoft or any OpenID Connect provider.

::

    async def on_login(context, person):            # person: an OAuthUser
        user = await users_by_email(person.email) if person.email_verified else None
        return user.id if user else None             # None refuses the sign-in

    oauth = OAuth(app, base_url="https://shop.example", on_login=on_login)
    oauth.add(google(client_id=..., client_secret=...))
    oauth.add(github(client_id=..., client_secret=...))

    ButtonLink("Sign in with Google", href=oauth.login_url("google", next="/orders"))

``/auth/<provider>/login`` sends the browser to the provider; ``/auth/<provider>/callback`` (the
redirect URI to register with the provider) checks the answer, asks the provider's server who the
person is, calls ``on_login`` and signs the returned principal in with ``session.login``.

The request carries a one-time ``state`` (against cross-site request forgery), a ``nonce`` and a
PKCE challenge, so an intercepted code is useless. The identity is read from the provider over
HTTPS rather than from a token the browser could have touched.
"""

from __future__ import annotations

import base64
import hashlib
import inspect
import secrets
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from urllib.parse import urlencode

from fastapi import Request, Response
from fastapi.responses import RedirectResponse

from . import _http
from .http import base_path, local_path

if TYPE_CHECKING:
    from .app import App
    from .context import Context

_SESSION_KEY = "rw.oauth"


@dataclass(frozen=True)
class OAuthUser:
    """Who signed in, as the provider describes them."""

    provider: str
    id: str  # stable for this person at this provider (OpenID "sub")
    email: str | None
    email_verified: bool
    name: str | None
    picture: str | None
    raw: dict[str, Any] = field(repr=False)


@dataclass
class Provider:
    """An OAuth 2 / OpenID Connect provider. Use :func:`google`, :func:`github`, :func:`microsoft` or :func:`oidc`."""

    name: str
    client_id: str
    client_secret: str
    scopes: tuple[str, ...]
    authorize_url: str = ""
    token_url: str = ""
    userinfo_url: str = ""
    issuer: str | None = None  # OpenID Connect: endpoints are discovered from the issuer
    extra_params: dict[str, str] = field(default_factory=dict)

    async def endpoints(self) -> None:
        """Fill in the endpoints from the issuer's discovery document, once."""
        if self.authorize_url or self.issuer is None:
            return
        config = await _http.request("GET", f"{self.issuer.rstrip('/')}/.well-known/openid-configuration")
        self.authorize_url = config["authorization_endpoint"]
        self.token_url = config["token_endpoint"]
        self.userinfo_url = config["userinfo_endpoint"]

    async def user(self, access_token: str) -> OAuthUser:
        info = await _http.request("GET", self.userinfo_url, headers={"Authorization": f"Bearer {access_token}"})
        return OAuthUser(
            provider=self.name,
            id=str(info["sub"]),
            email=info.get("email"),
            email_verified=info.get("email_verified") is True,
            name=info.get("name"),
            picture=info.get("picture"),
            raw=info,
        )


class GitHub(Provider):
    """GitHub is OAuth 2 without OpenID Connect: the profile and verified emails come from its API."""

    async def user(self, access_token: str) -> OAuthUser:
        headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/vnd.github+json"}
        info = await _http.request("GET", "https://api.github.com/user", headers=headers)
        emails = await _http.request("GET", "https://api.github.com/user/emails", headers=headers)
        primary = next((e for e in emails if e.get("primary") and e.get("verified")), None)
        return OAuthUser(
            provider=self.name,
            id=str(info["id"]),
            email=primary["email"] if primary else None,
            email_verified=primary is not None,
            name=info.get("name") or info.get("login"),
            picture=info.get("avatar_url"),
            raw=info,
        )


def oidc(name: str, issuer: str, *, client_id: str, client_secret: str, scopes: tuple[str, ...] = ()) -> Provider:
    """Any OpenID Connect provider (Okta, Auth0, Keycloak, GitLab, ...), configured from ``issuer``."""
    return Provider(name, client_id, client_secret, ("openid", "email", "profile", *scopes), issuer=issuer)


def google(*, client_id: str, client_secret: str, scopes: tuple[str, ...] = ()) -> Provider:
    return oidc(
        "google", "https://accounts.google.com", client_id=client_id, client_secret=client_secret, scopes=scopes
    )


def microsoft(*, client_id: str, client_secret: str, tenant: str = "common", scopes: tuple[str, ...] = ()) -> Provider:
    """Microsoft accounts and Entra ID. ``tenant``: ``"common"``, ``"consumers"``, ``"organizations"`` or an id."""
    base = f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0"
    return Provider(
        "microsoft",
        client_id,
        client_secret,
        ("openid", "email", "profile", *scopes),
        authorize_url=f"{base}/authorize",
        token_url=f"{base}/token",
        userinfo_url="https://graph.microsoft.com/oidc/userinfo",
    )


def github(*, client_id: str, client_secret: str, scopes: tuple[str, ...] = ()) -> Provider:
    return GitHub(
        "github",
        client_id,
        client_secret,
        ("read:user", "user:email", *scopes),
        authorize_url="https://github.com/login/oauth/authorize",
        token_url="https://github.com/login/oauth/access_token",
    )


OnLogin = Callable[["Context", OAuthUser], Any | Awaitable[Any]]


class OAuth:
    """Adds ``{path}/<provider>/login`` and ``{path}/<provider>/callback`` to ``app``.

    ``on_login(context, person)`` returns what to store with ``session.login`` (a user id, say),
    or ``None`` to refuse. ``base_url`` is the site's public address, used for the redirect URI.
    """

    def __init__(self, app: App, *, base_url: str, on_login: OnLogin, path: str = "/auth", after: str = "/") -> None:
        self.app = app
        self.base_url = base_url.rstrip("/")
        self.on_login = on_login
        self.path = "/" + path.strip("/")
        self.after = after
        self.providers: dict[str, Provider] = {}
        app.fastapi.add_api_route(
            f"{self.path}/{{provider}}/login", self._login, methods=["GET"], include_in_schema=False
        )
        app.fastapi.add_api_route(
            f"{self.path}/{{provider}}/callback", self._callback, methods=["GET"], include_in_schema=False
        )

    def add(self, provider: Provider) -> Provider:
        self.providers[provider.name] = provider
        return provider

    def login_url(self, provider: str, *, next: str | None = None) -> str:
        """The link that starts signing in with ``provider``, coming back to ``next`` afterwards."""
        query = f"?{urlencode({'next': next})}" if next else ""
        return f"{self.path}/{provider}/login{query}"

    def redirect_uri(self, provider: str) -> str:
        return f"{self.base_url}{self.path}/{provider}/callback"

    async def _login(self, request: Request, provider: str) -> Response:
        chosen = self.providers.get(provider)
        if chosen is None:
            return self._fail(request, 404, "Unknown sign-in provider")
        await chosen.endpoints()
        verifier = secrets.token_urlsafe(48)
        flow = {
            "provider": provider,
            "state": secrets.token_urlsafe(24),
            "nonce": secrets.token_urlsafe(24),
            "verifier": verifier,
            "next": local_path(request.query_params.get("next"), self.after),
        }
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        params = {
            "response_type": "code",
            "client_id": chosen.client_id,
            "redirect_uri": self.redirect_uri(provider),
            "scope": " ".join(chosen.scopes),
            "state": flow["state"],
            "nonce": flow["nonce"],
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            **chosen.extra_params,
        }
        ctx = await self.app.context_for(request)
        async with self.app.session_lock(ctx):
            ctx.session[_SESSION_KEY] = flow
        response = RedirectResponse(f"{chosen.authorize_url}?{urlencode(params)}", status_code=303)
        await self.app.finish(request, response, ctx)
        return response

    async def _callback(self, request: Request, provider: str) -> Response:
        ctx = await self.app.context_for(request)
        if ctx.peek_session() is None:
            response = self._fail(request, 400, "This sign-in link is not valid; please start again")
        else:
            async with self.app.session_lock(ctx):  # the state is used up even if signing in fails
                response = await self._complete(request, provider, ctx, ctx.session.pop(_SESSION_KEY, None))
        await self.app.finish(request, response, ctx)
        return response

    async def _complete(self, request: Request, provider: str, ctx: Context, flow: Any) -> Response:
        chosen = self.providers.get(provider)
        query = request.query_params
        if chosen is None or not isinstance(flow, dict) or flow.get("provider") != provider:
            return self._fail(request, 400, "This sign-in link is not valid; please start again")
        if not secrets.compare_digest(str(query.get("state", "")), str(flow["state"])):
            return self._fail(request, 400, "This sign-in link is not valid; please start again")
        if "error" in query or "code" not in query:
            return self._fail(request, 400, "Sign-in was cancelled")
        try:
            tokens = await _http.request(
                "POST",
                chosen.token_url,
                form={
                    "grant_type": "authorization_code",
                    "code": query["code"],
                    "redirect_uri": self.redirect_uri(provider),
                    "client_id": chosen.client_id,
                    "client_secret": chosen.client_secret,
                    "code_verifier": flow["verifier"],
                },
            )
            person = await chosen.user(tokens["access_token"])
        except (_http.HTTPError, KeyError, TypeError):
            return self._fail(request, 502, f"Could not sign in with {provider}; please try again")
        principal = self.on_login(ctx, person)
        if inspect.isawaitable(principal):
            principal = await principal
        if principal is None:
            return self._fail(request, 403, "This account cannot sign in here")
        ctx.session.login(principal)
        return RedirectResponse(base_path(request) + flow["next"], status_code=303)

    def _fail(self, request: Request, status: int, message: str) -> Response:
        from .pages import error_page

        return error_page(self.app, request, status, message)
