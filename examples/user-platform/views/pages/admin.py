"""User administration, under /admin. Members get a 403 page."""

from rational import Avatar, Badge, Button, Card, Column, Heading, Page, Router, Row, Select, State, Text, h, js

from models import ROLES, UserOut
from services import AdminService
from views.components import Shell
from views.styles import CELL, SCROLL_X, TABLE

router = Router(prefix="/admin")


@router.page("/", auth="required")
class Admin(Page):
    title = "Admin · User platform"
    users = State(factory=list)

    async def mount(self):
        self.use(AdminService).require_admin()  # raises Forbidden -> 403 page for members
        await self.reload()

    async def reload(self):
        self.users = await self.use(AdminService).list_users()

    async def set_role(self, user_id: int, role: str):
        await self.use(AdminService).set_role(user_id, role)
        await self.reload()

    async def delete(self, user_id: int):
        await self.use(AdminService).delete_user(user_id)
        await self.reload()

    def row(self, user: UserOut, me: UserOut):
        own = user.id == me.id
        if own:
            role, delete = Badge("you", tone="primary"), None
        else:
            role = Select(
                f"Role of {user.name}",
                list(ROLES),
                value=user.role,
                hide_label=True,
                on_change=lambda role, uid=user.id: self.set_role(uid, role),
            )
            delete = Button(
                "Delete",
                variant="danger",
                size="sm",
                aria_label=f"Delete {user.name}",
                on_click=[js.confirm(f"Delete {user.name}'s account?"), lambda uid=user.id: self.delete(uid)],
            )
        person = Row(
            Avatar(user.name, size=28),
            Column(Text(user.name, weight=600), Text(user.email, size="sm", muted=True), gap=0),
            gap="sm",
        )
        return h("tr", h("td", person, style=CELL), h("td", role, style=CELL), h("td", delete, style=CELL), key=user.id)

    def render(self):
        me: UserOut = self.context.user
        count = len(self.users)
        table = h("table", h("tbody", *[self.row(user, me) for user in self.users]), style=TABLE)
        return Shell(
            Heading("Users", level=1),
            Text(f"{count} account{'s' if count != 1 else ''}", muted=True),
            Card(h("div", table, style=SCROLL_X)),
        )
