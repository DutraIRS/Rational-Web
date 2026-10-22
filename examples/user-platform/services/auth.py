"""Who is making this request? Registered with ``app.authenticate(current_user)``."""

from rational import Context

from models import User, UserOut


async def current_user(ctx: Context) -> UserOut | None:
    """The session stores only the user id; the user is loaded fresh on every request, so role
    changes and deleted accounts take effect immediately."""
    session = ctx.peek_session()
    user_id = session.user if session is not None else None
    if user_id is None:
        return None
    async with ctx.db.session() as db:
        user = await db.get(User, user_id)
    return UserOut.model_validate(user) if user is not None else None
