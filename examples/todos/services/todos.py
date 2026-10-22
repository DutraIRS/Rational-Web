"""Every database operation lives here, scoped to the signed-in user.

The ``@remote`` methods are also a JSON API under ``/api/todo/...``.
"""

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from rational import NotFound, RemoteError
from rational.backend import Service, remote

from models import Todo, TodoOut


class TodoService(Service):
    """The signed-in user's todos."""

    @remote(method="GET", auth="required")
    async def list_todos(self) -> list[TodoOut]:
        """List your todos, oldest first."""
        async with self.db.session() as session:
            rows = await session.scalars(select(Todo).where(Todo.owner == self.user).order_by(Todo.id))
            return [TodoOut.model_validate(t) for t in rows]

    @remote(auth="required")
    async def add(self, title: str) -> TodoOut:
        """Create a todo."""
        title = title.strip()
        if not title:
            raise RemoteError("A todo needs a title", code="invalid")
        async with self.db.transaction() as session:
            todo = Todo(owner=self.user, title=title[:200])
            session.add(todo)
            await session.flush()
            return TodoOut.model_validate(todo)

    @remote(auth="required")
    async def set_done(self, todo_id: int, done: bool) -> TodoOut:
        """Mark a todo as done or not done."""
        async with self.db.transaction() as session:
            todo = await self._owned(session, todo_id)
            todo.done = done
            return TodoOut.model_validate(todo)

    @remote(auth="required")
    async def remove(self, todo_id: int) -> None:
        """Delete a todo."""
        async with self.db.transaction() as session:
            await session.delete(await self._owned(session, todo_id))

    @remote(auth="required")
    async def clear_done(self) -> int:
        """Delete every completed todo; returns how many were removed."""
        async with self.db.transaction() as session:
            result = await session.execute(delete(Todo).where(Todo.owner == self.user, Todo.done.is_(True)))
            return int(result.rowcount or 0)

    async def _owned(self, session: AsyncSession, todo_id: int) -> Todo:
        todo = await session.get(Todo, todo_id)
        if todo is None or todo.owner != self.user:  # never reveal that other users' rows exist
            raise NotFound("No such todo")
        return todo
