"""Account emails: password recovery, email verification and sign-in links.

Subclass :class:`Accounts` with the four lookups your user model needs, then call the flows from
your pages and services::

    class ShopAccounts(Accounts):
        async def find(self, email):                   # the user with this address, or None
            return (await users.find(User.email == email.lower(), limit=1) or [None])[0]

        async def get(self, user_id):                  # the user with this id, or None
            return await users.get(int(user_id))

        async def save_password(self, user, password_hash):
            await users.update(user.id, password=password_hash)

        async def mark_verified(self, user):
            await users.update(user.id, verified=True)

    accounts = ShopAccounts(app, mailer, base_url="https://shop.example")

    await accounts.send_reset(form.email)              # "If that address has an account, ..."
    user = await accounts.reset(token, form.password)  # on /reset-password?token=...

Links are signed with the app's secret key and expire. A reset link is tied to the current password,
so it works once; a verification link is tied to the address; a sign-in link works once. The
``send_*`` methods answer the same whether or not an account exists, and send at most one message
per address and purpose every ``resend_after`` seconds.
"""

from __future__ import annotations

import base64
import hashlib
from typing import TYPE_CHECKING, Any, ClassVar
from urllib.parse import urlencode

from .components.basic import ButtonLink, Heading, Text
from .components.layout import Column
from .errors import FieldError
from .jobs import JobStore, MemoryJobStore
from .security import InvalidToken, Signer, hash_password

if TYPE_CHECKING:
    from .app import App
    from .mail import Mailer
    from .rendering.nodes import Node


class Accounts:
    """Password recovery, email verification and sign-in links for your users.

    ``store`` remembers used sign-in links and recent messages: pass ``jobs.store`` (Redis) when the
    app runs on several workers.
    """

    reset_path: ClassVar[str] = "/reset-password"
    verify_path: ClassVar[str] = "/verify-email"
    sign_in_path: ClassVar[str] = "/sign-in/link"
    reset_ttl: ClassVar[float] = 60 * 60
    verify_ttl: ClassVar[float] = 3 * 24 * 60 * 60
    sign_in_ttl: ClassVar[float] = 15 * 60
    resend_after: ClassVar[float] = 60
    min_password_length: ClassVar[int] = 8

    def __init__(
        self, app: App, mailer: Mailer, *, base_url: str, secret: str | None = None, store: JobStore | None = None
    ) -> None:
        self.app = app
        self.mailer = mailer
        self.base_url = base_url.rstrip("/")
        self._secret = secret
        self.store: JobStore = MemoryJobStore() if store is None else store

    # -- your user model ----------------------------------------------------------------------------

    async def find(self, email: str) -> Any | None:
        """The user with this email address, or ``None``."""
        raise NotImplementedError

    async def get(self, user_id: str) -> Any | None:
        """The user with this id (as text), or ``None``."""
        raise NotImplementedError

    async def save_password(self, user: Any, password_hash: str) -> None:
        """Store a new password hash (from :func:`~rational.security.hash_password`)."""
        raise NotImplementedError

    async def mark_verified(self, user: Any) -> None:
        """Record that the user controls their email address."""
        raise NotImplementedError

    def user_id(self, user: Any) -> str:
        return str(user.id)

    def email_of(self, user: Any) -> str:
        return str(user.email)

    def password_of(self, user: Any) -> str:
        return str(user.password)

    # -- the messages: override to change the wording or translate ----------------------------------

    def reset_message(self, user: Any, link: str) -> tuple[str, Node]:
        return "Reset your password", Column(
            Heading("Reset your password", level=2),
            Text("Someone asked to reset the password of this account. If it was you, choose a new one:"),
            ButtonLink("Choose a new password", href=link),
            Text(f"The link works once, for {int(self.reset_ttl // 60)} minutes. If it was not you, ignore this."),
            gap="md",
        )

    def verify_message(self, user: Any, link: str) -> tuple[str, Node]:
        return "Confirm your email address", Column(
            Heading("Confirm your email address", level=2),
            ButtonLink("Confirm my address", href=link),
            Text("If you did not create an account, ignore this message."),
            gap="md",
        )

    def sign_in_message(self, user: Any, link: str) -> tuple[str, Node]:
        return "Your sign-in link", Column(
            Heading("Sign in", level=2),
            ButtonLink("Sign in", href=link),
            Text(f"The link works once, for {int(self.sign_in_ttl // 60)} minutes. If it was not you, ignore this."),
            gap="md",
        )

    # -- flows --------------------------------------------------------------------------------------

    async def send_reset(self, email: str) -> None:
        """Email a password reset link, if ``email`` belongs to an account."""
        user = await self._recipient("reset", email)
        if user is not None:
            link = self._link(self.reset_path, "reset", user, self.password_of(user))
            await self._send(user, self.reset_message(user, link))

    async def reset(self, token: str, password: str) -> Any:
        """Set a new password from a reset link and return the user. Raises ``InvalidToken`` or ``FieldError``."""
        if len(password) < self.min_password_length:
            raise FieldError("password", f"Use at least {self.min_password_length} characters")
        user = await self._check("reset", token, self.reset_ttl, self.password_of)
        await self.save_password(user, hash_password(password))
        return user

    async def send_verification(self, user: Any) -> None:
        """Email a link that confirms the user's address."""
        if await self.store.once(f"verify:{self.email_of(user).lower()}", self.resend_after):
            link = self._link(self.verify_path, "verify", user, self.email_of(user))
            await self._send(user, self.verify_message(user, link))

    async def verify(self, token: str) -> Any:
        """Confirm an address from a verification link and return the user. Raises ``InvalidToken``."""
        user = await self._check("verify", token, self.verify_ttl, self.email_of)
        await self.mark_verified(user)
        return user

    async def send_sign_in_link(self, email: str) -> None:
        """Email a one-time sign-in link, if ``email`` belongs to an account."""
        user = await self._recipient("sign_in", email)
        if user is not None:
            link = self._link(self.sign_in_path, "sign_in", user, "")
            await self._send(user, self.sign_in_message(user, link))

    async def sign_in(self, token: str) -> Any:
        """The user a sign-in link belongs to; the link then stops working. Raises ``InvalidToken``.

        Sign them in yourself: ``self.context.session.login(accounts.user_id(user))``.
        """
        user = await self._check("sign_in", token, self.sign_in_ttl, lambda _: "")
        if not await self.store.once(f"used:{token.rpartition('.')[2]}", self.sign_in_ttl):
            raise InvalidToken("already used")
        return user

    # -- internals ----------------------------------------------------------------------------------

    def _signer(self, purpose: str) -> Signer:
        return Signer(self._secret or self.app.secret_key, salt=f"rational.accounts.{purpose}")

    @staticmethod
    def _fingerprint(purpose: str, value: str) -> str:  # never the secret itself in a link
        digest = hashlib.sha256(f"{purpose}\0{value}".encode()).digest()[:12]
        return base64.urlsafe_b64encode(digest).decode()

    def _link(self, path: str, purpose: str, user: Any, bound_to: str) -> str:
        token = self._signer(purpose).sign([self.user_id(user), self._fingerprint(purpose, bound_to)])
        return f"{self.base_url}{path}?{urlencode({'token': token})}"

    async def _check(self, purpose: str, token: str, ttl: float, bound_to: Any) -> Any:
        user_id, fingerprint = self._signer(purpose).unsign(token, max_age=ttl)
        user = await self.get(str(user_id))
        if user is None or fingerprint != self._fingerprint(purpose, bound_to(user)):
            raise InvalidToken("no longer valid")
        return user

    async def _recipient(self, purpose: str, email: str) -> Any | None:
        if not await self.store.once(f"{purpose}:{email.strip().lower()}", self.resend_after):
            return None  # sent a moment ago: do not flood the inbox
        return await self.find(email.strip())

    async def _send(self, user: Any, message: tuple[str, Node]) -> None:
        subject, body = message
        await self.mailer.send(self.email_of(user), subject, body)
