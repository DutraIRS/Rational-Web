from sqlalchemy import func, select

from rational import FieldError
from rational.backend import Service, remote

from .security import hash_password, verify_password
from models import User, UserOut


class AccountService(Service):
    """Sign-up, sign-in and the signed-in user's own profile."""

    async def register(self, name: str, email: str, password: str) -> UserOut:
        email = email.strip().lower()
        async with self.db.transaction() as db:
            if await db.scalar(select(User.id).where(User.email == email)) is not None:
                raise FieldError("email", "An account with this email already exists")
            first_user = await db.scalar(select(func.count(User.id))) == 0
            user = User(
                name=name.strip(),
                email=email,
                password_hash=hash_password(password),
                role="admin" if first_user else "member",
            )
            db.add(user)
            await db.flush()
            return UserOut.model_validate(user)

    async def authenticate(self, email: str, password: str) -> UserOut:
        async with self.db.session() as db:
            user = await db.scalar(select(User).where(User.email == email.strip().lower()))
        if user is None or not verify_password(password, user.password_hash):
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
        async with self.db.transaction() as db:
            user = await db.get(User, self.user.id)
            if not verify_password(current, user.password_hash):
                raise FieldError("current", "That is not your current password")
            user.password_hash = hash_password(new)
