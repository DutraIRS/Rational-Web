"""The home page: the form and the entries."""

from rational import (
    Button,
    Card,
    Column,
    Container,
    Form,
    Grid,
    Heading,
    Input,
    Page,
    Router,
    Row,
    State,
    Style,
    Text,
    Textarea,
    js,
)

from models import SignForm
from services import GuestbookService
from views.components import EntryCard

router = Router()


@router.page("/")
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
