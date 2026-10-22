from sqlalchemy import select

from rational import FieldError, Forbidden, NotFound
from rational.backend import Service, remote

from models import ROLES, User, UserOut


class AdminService(Service):
    """User administration. Every operation requires the admin role."""

    def require_admin(self) -> UserOut:
        user = self.require_user()
        if not user.is_admin:
            raise Forbidden("Administrators only")
        return user

    @remote(method="GET", auth="required")
    async def list_users(self) -> list[UserOut]:
        """Every account, oldest first."""
        self.require_admin()
        async with self.db.session() as db:
            return [UserOut.model_validate(u) for u in await db.scalars(select(User).order_by(User.id))]

    @remote(auth="required")
    async def set_role(self, user_id: int, role: str) -> UserOut:
        """Make someone a member or an admin."""
        me = self.require_admin()
        if role not in ROLES:
            raise FieldError("role", f"Role must be one of: {', '.join(ROLES)}")
        if user_id == me.id:
            raise Forbidden("You cannot change your own role")
        async with self.db.transaction() as db:
            user = await db.get(User, user_id)
            if user is None:
                raise NotFound("No such user")
            user.role = role
            return UserOut.model_validate(user)

    @remote(auth="required")
    async def delete_user(self, user_id: int) -> None:
        """Delete an account."""
        me = self.require_admin()
        if user_id == me.id:
            raise Forbidden("You cannot delete your own account here")
        async with self.db.transaction() as db:
            user = await db.get(User, user_id)
            if user is None:
                raise NotFound("No such user")
            await db.delete(user)
