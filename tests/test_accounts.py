"""Account emails: password reset, email verification and sign-in links."""

import re
import time
from dataclasses import dataclass
from html import unescape

import pytest

from rational import App, FieldError
from rational.accounts import Accounts
from rational.mail import Mailer, Memory
from rational.security import InvalidToken, hash_password, verify_password

SECRET = "s" * 40


@dataclass
class User:
    id: int
    email: str
    password: str
    verified: bool = False


class ShopAccounts(Accounts):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.users = {1: User(1, "ada@example.com", hash_password("old password"))}

    async def find(self, email):
        return next((u for u in self.users.values() if u.email == email.lower()), None)

    async def get(self, user_id):
        return self.users.get(int(user_id))

    async def save_password(self, user, password_hash):
        user.password = password_hash

    async def mark_verified(self, user):
        user.verified = True


def setup():
    outbox = Memory()
    app = App(secret_key=SECRET)
    accounts = ShopAccounts(app, Mailer(app, outbox, sender="hi@shop.example"), base_url="https://shop.example/")
    return accounts, outbox


def token_in(email, path):
    match = re.search(rf"https://shop\.example{re.escape(path)}\?token=([^\"&\s)]+)", unescape(email.html))
    assert match, email.html
    assert match.group(0) in email.text  # the plain-text version carries the link too
    return match.group(1)


async def test_password_reset_works_once():
    accounts, outbox = setup()
    await accounts.send_reset(" ADA@example.com ")
    (email,) = outbox.outbox
    assert email.to == ["ada@example.com"] and email.subject == "Reset your password"
    token = token_in(email, "/reset-password")

    with pytest.raises(FieldError):
        await accounts.reset(token, "short")
    user = await accounts.reset(token, "new password")
    assert verify_password("new password", user.password)
    with pytest.raises(InvalidToken, match="no longer valid"):  # the password changed: the link is spent
        await accounts.reset(token, "another password")


async def test_sending_reveals_nothing_and_does_not_flood():
    accounts, outbox = setup()
    await accounts.send_reset("nobody@example.com")  # no account: no error, no message
    await accounts.send_reset("ada@example.com")
    await accounts.send_reset("ada@example.com")  # again within a minute: not sent
    assert len(outbox.outbox) == 1


async def test_links_are_bound_to_their_purpose_and_expire(monkeypatch):
    accounts, outbox = setup()
    await accounts.send_reset("ada@example.com")
    token = token_in(outbox.outbox[0], "/reset-password")
    with pytest.raises(InvalidToken):
        await accounts.sign_in(token)  # a reset link is not a sign-in link
    with pytest.raises(InvalidToken):
        await accounts.reset(token[:-2] + "xx", "new password")

    class Later:
        @staticmethod
        def time():
            return time.time() + accounts.reset_ttl + 5

    monkeypatch.setattr("rational.security.time", Later)
    with pytest.raises(InvalidToken, match="expired"):
        await accounts.reset(token, "new password")


async def test_email_verification_follows_the_address():
    accounts, outbox = setup()
    user = accounts.users[1]
    await accounts.send_verification(user)
    token = token_in(outbox.outbox[0], "/verify-email")
    assert (await accounts.verify(token)).verified

    user.verified, user.email = False, "ada@new.example"  # a link for the old address no longer counts
    with pytest.raises(InvalidToken):
        await accounts.verify(token)


async def test_sign_in_links_work_once():
    accounts, outbox = setup()
    await accounts.send_sign_in_link("ada@example.com")
    assert outbox.outbox[0].subject == "Your sign-in link"
    token = token_in(outbox.outbox[0], "/sign-in/link")
    assert (await accounts.sign_in(token)).id == 1
    with pytest.raises(InvalidToken, match="already used"):
        await accounts.sign_in(token)


async def test_the_lookups_must_be_written():
    app = App(secret_key=SECRET)
    accounts = Accounts(app, Mailer(app, Memory(), sender="a@x"), base_url="https://x")
    lookups = (accounts.find("a@x"), accounts.get("1"), accounts.save_password(None, ""), accounts.mark_verified(None))
    for call in lookups:
        with pytest.raises(NotImplementedError):
            await call
