"""Tutorial step 5: a database, a service and a JSON API."""

import os
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import String, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from rational import (
    App,
    Avatar,
    Button,
    Card,
    Column,
    Component,
    Container,
    FieldError,
    Form,
    Grid,
    Heading,
    Input,
    Page,
    Row,
    State,
    Style,
    Text,
    Textarea,
    js,
)
from rational.backend import Service, remote

app = App(title="Guestbook", theme="soft", database=os.environ.get("DATABASE_URL", "sqlite+aiosqlite:///guestbook.db"))


# -- the table ------------------------------------------------------------------------------------


class Base(DeclarativeBase):
    pass


class EntryRow(Base):
    __tablename__ = "entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(40))
    message: Mapped[str] = mapped_column(String(280))
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))


@app.on_startup
async def create_tables() -> None:
    await app.db.create_all(Base)


# -- the service: used by the page *and* published as a JSON API -----------------------------------


class Entry(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    message: str


@app.service
class GuestbookService(Service):
    """Read and sign the guestbook."""

    @remote(method="GET")
    async def entries(self) -> list[Entry]:
        """Every entry, newest first."""
        async with self.db.session() as db:
            rows = await db.scalars(select(EntryRow).order_by(EntryRow.id.desc()))
            return [Entry.model_validate(row) for row in rows]

    @remote
    async def sign(self, name: str, message: str) -> Entry:
        """Add an entry."""
        if "http://" in message or "https://" in message:
            raise FieldError("message", "Links are not allowed")  # shown under the field
        async with self.db.transaction() as db:
            row = EntryRow(name=name.strip(), message=message.strip())
            db.add(row)
            await db.flush()
            return Entry.model_validate(row)


# -- the page ----------------------------------------------------------------------------------------


class SignForm(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    message: str = Field(min_length=1, max_length=280)


ACCENT = Style(border_left="4px solid var(--rw-color-primary)")


class EntryCard(Component):
    entry: Entry
    hearts = State(0)

    def like(self):
        self.hearts += 1

    def render(self):
        return Card(
            Text(self.entry.message, size="lg"),
            Row(
                Avatar(self.entry.name, size=28),
                Text(self.entry.name, muted=True, size="sm"),
                Button(
                    f"♥ {self.hearts}", variant="ghost", size="sm", on_click=self.like, style=Style(margin_left="auto")
                ),
            ),
            style=ACCENT,
        )


@app.page("/")
class Home(Page):
    title = "Guestbook"
    entries = State(factory=list)

    async def mount(self):
        await self.reload()

    async def reload(self):
        self.entries = await self.use(GuestbookService).entries()

    async def sign(self, form: SignForm):
        await self.use(GuestbookService).sign(form.name, form.message)
        await self.reload()

    def render(self):
        return Container(
            Row(
                Heading("Guestbook", level=1),
                Button("Dark mode", variant="outline", size="sm", on_click=js.toggle_theme()),
                justify="between",
            ),
            Row(
                Card(
                    Form(
                        Input("Your name", name="name", required=True),
                        Textarea("Message", name="message", required=True, rows=4),
                        Button("Sign the guestbook", type="submit", full_width=True),
                        on_submit=self.sign,
                        key=f"form-{len(self.entries)}",
                    ),
                    style=Style(width=320, shrink=0, viewport={"mobile": Style(width="100%")}),
                ),
                Column(
                    Grid(*[EntryCard(entry=e, key=e.id) for e in self.entries], min_column_width=240),
                    Text("API: /api/guestbook/entries · interactive docs: /api/docs", muted=True, size="sm"),
                    style=Style(grow=1, min_width=0),
                ),
                align="start",
                collapse="mobile",
            ),
            tag="main",
            max_width=1000,
            style=Style(layout="vertical", gap="lg", padding_y="xl"),
        )


if __name__ == "__main__":
    app.run()
