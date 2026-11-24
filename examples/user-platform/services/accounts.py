from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from rational import FieldError
from rational.backend import Service, remote
from rational.security import ahash_password, averify_password

from models import FirstAccount, User, UserOut


async def _claim_first_account(db: AsyncSession, user_id: int) -> bool:
    """True for the first account only, even when two are created at the same moment.

    Counting users and then inserting is not enough: two sign-ups on an empty database would both count
    zero. Only one insert of the ``first_account`` row can succeed; the other fails on its primary key.
    """
    if await db.scalar(select(func.count(User.id))) != 1:  # other accounts exist: an older database
        return False
    try:
        async with db.begin_nested():  # a savepoint: losing the race leaves the sign-up itself intact
            db.add(FirstAccount(id=1, user_id=user_id))
    except IntegrityError:
        return False
    return True


class AccountService(Service):
    """Sign-up, sign-in and the signed-in user's own profile."""

    async def register(self, name: str, email: str, password: str) -> UserOut:
        email = email.strip().lower()
        password_hash = await ahash_password(password)  # slow on purpose: not while holding a transaction open
        async with self.db.transaction() as db:
            if await db.scalar(select(User.id).where(User.email == email)) is not None:
                raise FieldError("email", "An account with this email already exists")
            user = User(name=name.strip(), email=email, password_hash=password_hash, role="member")
            db.add(user)
            await db.flush()
            if await _claim_first_account(db, user.id):
                user.role = "admin"
            return UserOut.model_validate(user)

    async def authenticate(self, email: str, password: str) -> UserOut:
        async with self.db.session() as db:
            user = await db.scalar(select(User).where(User.email == email.strip().lower()))
        # With no such user it does the same work, so the time it takes does not reveal who has an account.
        if not await averify_password(password, user.password_hash if user else None) or user is None:
            raise FieldError("password", "Incorrect email or password")  # one message: don't reveal which
        return UserOut.model_validate(user)

    @remote(method="GET", auth="required")
    async def me(self) -> UserOut:
        """The signed-in user."""
        return self.user

    @remote(auth="required")
    async def update_profile(self, name: str, bio: str = "") -> UserOut:
        """Change your display name and bio."""
        if not name.strip():
            raise FieldError("name", "Your name cannot be empty")
        async with self.db.transaction() as db:
            user = await db.get(User, self.user.id)
            user.name, user.bio = name.strip()[:60], bio.strip()[:280]
            return UserOut.model_validate(user)

    @remote(auth="required")
    async def change_password(self, current: str, new: str) -> None:
        """Change your password (requires the current one)."""
        if len(new) < 8:
            raise FieldError("new", "Use at least 8 characters")
        async with self.db.session() as db:
            user = await db.get(User, self.user.id)
        if not await averify_password(current, user.password_hash):
            raise FieldError("current", "That is not your current password")
        password_hash = await ahash_password(new)
        async with self.db.transaction() as db:
            user = await db.get(User, self.user.id)
            user.password_hash = password_hash
