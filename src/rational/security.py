"""Passwords, tokens, signing and encryption, with safe defaults.

Everything here uses the standard library except encryption, which needs the ``cryptography``
package (``pip install "rational[crypto]"``):

* :func:`hash_password` / :func:`verify_password`: scrypt with a random salt per password.
* :class:`Tokens`: JSON Web Tokens signed with HMAC-SHA256 (``HS256``), with expiry, for APIs and
  mobile clients. :meth:`Tokens.authenticator` plugs them into ``app.authenticate``.
* :class:`Signer`: tamper-proof (not secret) values, optionally expiring: signed cookies, links in
  emails, unsubscribe tokens.
* :class:`Box`: authenticated encryption (AES-256-GCM) for values the client must not read.

Secrets must be long and random: ``python -c "import secrets; print(secrets.token_urlsafe(32))"``.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from collections.abc import Awaitable, Callable, Sequence
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .context import Context

MIN_SECRET_BYTES = 32
_SCRYPT = {"n": 2**14, "r": 8, "p": 1}


class InvalidToken(ValueError):  # noqa: N818 - reads naturally: except InvalidToken
    """A token or signed value that is malformed, forged or expired."""


def _secret(secret: str | bytes, what: str) -> bytes:
    key = secret.encode() if isinstance(secret, str) else bytes(secret)
    if len(key) < MIN_SECRET_BYTES:
        raise ValueError(f"{what} needs a secret of at least {MIN_SECRET_BYTES} bytes; use secrets.token_urlsafe(32)")
    return key


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(text: str) -> bytes:
    try:
        return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    except (ValueError, TypeError) as e:
        raise InvalidToken("malformed") from e


# -- passwords ----------------------------------------------------------------------------------------


def hash_password(password: str) -> str:
    """``scrypt$n$r$p$<salt>$<hash>``: store this, never the password."""
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, **_SCRYPT)
    return f"scrypt${_SCRYPT['n']}${_SCRYPT['r']}${_SCRYPT['p']}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """True if ``password`` matches ``stored``. Takes the same time whether or not it matches."""
    try:
        scheme, n, r, p, salt, digest = stored.split("$")
        if scheme != "scrypt":
            return False
        candidate = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p))
        return hmac.compare_digest(candidate, bytes.fromhex(digest))
    except (ValueError, TypeError):
        return False


def password_needs_rehash(stored: str) -> bool:
    """True if ``stored`` used weaker parameters than today's: re-hash it after a successful sign-in."""
    parts = stored.split("$")
    return len(parts) != 6 or parts[0] != "scrypt" or parts[1:4] != [str(v) for v in _SCRYPT.values()]


# -- signing ---------------------------------------------------------------------------------------------


class Signer:
    """Sign values so they cannot be altered (they stay readable). ``max_age`` rejects old ones.

    ``salt`` separates purposes: a value signed for one purpose is invalid for another.
    ``extra_secrets`` are older keys that still verify (secret-key rotation): new values are
    always signed with ``secret``.
    """

    def __init__(
        self, secret: str | bytes, *, salt: str = "rational.signer", extra_secrets: Sequence[str | bytes] = ()
    ) -> None:
        self._keys = [
            hmac.new(_secret(s, "Signer"), salt.encode(), hashlib.sha256).digest() for s in (secret, *extra_secrets)
        ]

    def _macs(self, payload: bytes) -> list[str]:
        return [_b64(hmac.new(key, payload, hashlib.sha256).digest()) for key in self._keys]

    def sign(self, value: Any) -> str:
        """A URL-safe string carrying ``value`` (any JSON data) and when it was signed."""
        payload = _b64(json.dumps([int(time.time()), value], separators=(",", ":")).encode())
        return f"{payload}.{self._macs(payload.encode())[0]}"

    def unsign(self, token: str, *, max_age: float | None = None) -> Any:
        """The value, if ``token`` is intact (and younger than ``max_age`` seconds); else ``InvalidToken``."""
        payload, _, mac = token.rpartition(".")
        if not payload or not any(hmac.compare_digest(mac, candidate) for candidate in self._macs(payload.encode())):
            raise InvalidToken("bad signature")
        try:
            signed_at, value = json.loads(_unb64(payload))
        except (ValueError, TypeError) as e:
            raise InvalidToken("malformed") from e
        if max_age is not None and time.time() - signed_at > max_age:
            raise InvalidToken("expired")
        return value


# -- encryption -------------------------------------------------------------------------------------------


class Box:
    """Encrypt values the client may hold but must not read or change (AES-256-GCM).

    Needs ``pip install "rational[crypto]"``. The key is derived from ``secret`` with HKDF.
    """

    def __init__(
        self, secret: str | bytes, *, salt: str = "rational.box", extra_secrets: Sequence[str | bytes] = ()
    ) -> None:
        try:
            from cryptography.hazmat.primitives import hashes
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
            from cryptography.hazmat.primitives.kdf.hkdf import HKDF
        except ImportError as e:
            raise ImportError('Box needs the cryptography package: pip install "rational[crypto]"') from e
        keys = [
            HKDF(algorithm=hashes.SHA256(), length=32, salt=salt.encode(), info=b"rational.box").derive(
                _secret(s, "Box")
            )
            for s in (secret, *extra_secrets)
        ]
        self._aeads = [AESGCM(key) for key in keys]  # the first encrypts; all of them decrypt

    def seal(self, value: Any) -> str:
        """Encrypt any JSON data into a URL-safe string."""
        nonce = secrets.token_bytes(12)
        data = self._aeads[0].encrypt(nonce, json.dumps(value, separators=(",", ":")).encode(), None)
        return _b64(nonce + data)

    def open(self, token: str) -> Any:
        """The value sealed in ``token``; ``InvalidToken`` if it was altered or sealed with another key."""
        from cryptography.exceptions import InvalidTag

        raw = _unb64(token)
        if len(raw) < 13:
            raise InvalidToken("malformed")
        for aead in self._aeads:
            try:
                return json.loads(aead.decrypt(raw[:12], raw[12:], None))
            except InvalidTag:
                continue
            except ValueError as e:
                raise InvalidToken("malformed") from e
        raise InvalidToken("cannot decrypt")


# -- JSON Web Tokens ------------------------------------------------------------------------------------------


class Tokens:
    """Issue and verify JSON Web Tokens (HS256) for API clients::

        tokens = Tokens(SECRET, issuer="shop", ttl=3600)
        token = tokens.issue(str(user.id), role="admin")
        claims = tokens.verify(token)  # {"sub": "42", "role": "admin", "iat": ..., "exp": ..., "iss": "shop"}

    Only ``HS256`` is accepted (never ``none`` or another algorithm named by the token itself).
    """

    def __init__(
        self,
        secret: str | bytes,
        *,
        issuer: str | None = None,
        ttl: float = 3600,
        leeway: float = 30,
        extra_secrets: Sequence[str | bytes] = (),
    ) -> None:
        self._keys = [_secret(s, "Tokens") for s in (secret, *extra_secrets)]
        self._key = self._keys[0]
        self.issuer = issuer
        self.ttl = ttl
        self.leeway = leeway

    def issue(self, subject: str, *, ttl: float | None = None, **claims: Any) -> str:
        now = int(time.time())
        body: dict[str, Any] = {**claims, "sub": subject, "iat": now, "exp": now + int(ttl or self.ttl)}
        if self.issuer is not None:
            body["iss"] = self.issuer
        header = _b64(b'{"alg":"HS256","typ":"JWT"}')
        payload = _b64(json.dumps(body, separators=(",", ":")).encode())
        signing_input = f"{header}.{payload}".encode()
        return f"{header}.{payload}.{_b64(hmac.new(self._key, signing_input, hashlib.sha256).digest())}"

    def verify(self, token: str) -> dict[str, Any]:
        """The token's claims; ``InvalidToken`` if it is forged, malformed, expired or from another issuer."""
        try:
            header_b64, payload_b64, mac = token.split(".")
        except ValueError as e:
            raise InvalidToken("malformed") from e
        signed = f"{header_b64}.{payload_b64}".encode()
        expected = [_b64(hmac.new(key, signed, hashlib.sha256).digest()) for key in self._keys]
        if not any(hmac.compare_digest(mac, candidate) for candidate in expected):
            raise InvalidToken("bad signature")
        try:
            header, claims = json.loads(_unb64(header_b64)), json.loads(_unb64(payload_b64))
        except ValueError as e:
            raise InvalidToken("malformed") from e
        if not isinstance(header, dict) or header.get("alg") != "HS256" or not isinstance(claims, dict):
            raise InvalidToken("unsupported token")
        now = time.time()
        if not isinstance(claims.get("exp"), (int, float)) or now > claims["exp"] + self.leeway:
            raise InvalidToken("expired")
        if isinstance(claims.get("nbf"), (int, float)) and now < claims["nbf"] - self.leeway:
            raise InvalidToken("not valid yet")
        if self.issuer is not None and claims.get("iss") != self.issuer:
            raise InvalidToken("wrong issuer")
        return claims

    def authenticator(
        self, load_user: Callable[[dict[str, Any]], Any] | None = None
    ) -> Callable[[Context], Awaitable[Any]]:
        """For ``app.authenticate``: a bearer token in ``Authorization`` signs the caller in.

        ``load_user(claims)`` (sync or async) turns claims into your user object; without it the
        claims themselves are the user. Requests without a token fall back to the session's user.
        """
        import inspect

        async def authenticate(ctx: Context) -> Any:
            request = ctx.request
            header = request.headers.get("authorization", "") if request is not None else ""
            if header[:7].lower() != "bearer ":
                session = ctx.peek_session()
                return None if session is None else session.user
            try:
                claims = self.verify(header[7:].strip())
            except InvalidToken:
                return None
            user = claims if load_user is None else load_user(claims)
            return await user if inspect.isawaitable(user) else user

        return authenticate
