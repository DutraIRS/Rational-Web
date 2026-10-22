from collections.abc import Awaitable, Callable

from rational import Button, Checkbox, Component, Style, h, js

from models import TodoOut
from services import TodoService
from views.styles import DONE, TODO_ROW


class TodoItem(Component):
    """One row. ``changed`` is a callback prop: the list reloads after a change."""

    todo: TodoOut
    changed: Callable[[], Awaitable[None]]

    async def toggle(self, done: bool):
        await self.use(TodoService).set_done(self.todo.id, done)
        await self.changed()

    async def remove(self):
        await self.use(TodoService).remove(self.todo.id)
        await self.changed()

    def render(self):
        return h(
            "li",
            Checkbox(
                self.todo.title,
                checked=self.todo.done,
                on_change=self.toggle,
                style=Style(grow=1) | (DONE if self.todo.done else None),
            ),
            Button(
                "Delete",
                variant="ghost",
                size="sm",
                aria_label=f"Delete {self.todo.title}",
                on_click=[js.confirm(f"Delete “{self.todo.title}”?"), self.remove],  # asks in the browser first
            ),
            style=TODO_ROW,
        )
