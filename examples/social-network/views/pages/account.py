from rational import Avatar, Button, Card, Column, Form, Grid, Heading, Input, Page, Router, State, Style, Text

from models import JoinForm
from services import SocialService
from settings import NETWORK_NAME
from views.components import Shell

router = Router()


def safe_next(value: str | None) -> str:
    return value if value and value.startswith("/") and not value.startswith("//") else "/"


@router.page("/login")
class Login(Page):
    """Demo sign-in: continue as a seeded member, or join with a new handle. (No passwords here:
    see the user-platform example for real password handling.)"""

    title = f"Sign in · {NETWORK_NAME}"
    members = State(factory=list)
    next_url = State("/")

    async def mount(self):
        self.next_url = safe_next(self.request.query_params.get("next"))
        self.members = await self.use(SocialService).members()

    def sign_in_as(self, handle: str):
        self.context.session.login(handle)
        self.navigate(self.next_url)

    async def join(self, form: JoinForm):
        member = await self.use(SocialService).join(form.handle, form.name)
        self.sign_in_as(member.handle)

    def render(self):
        demo = Grid(
            *[
                Button(
                    Avatar(m.name, size=24),
                    f"@{m.handle}",
                    variant="outline",
                    aria_label=f"Continue as @{m.handle}",
                    on_click=lambda handle=m.handle: self.sign_in_as(handle),
                )
                for m in self.members
            ],
            min_column_width=150,
            gap="sm",
        )
        return Shell(
            Column(
                Card(Heading("Continue as a demo member", level=2), demo, style=Style(shadow="none")),
                Card(
                    Heading("Or join", level=2),
                    Form(
                        Input("Handle", name="handle", required=True, help="3 to 20 lowercase letters, digits or _."),
                        Input("Name", name="name", required=True, autocomplete="name"),
                        Button("Join", type="submit"),
                        on_submit=self.join,
                    ),
                    style=Style(shadow="none"),
                ),
                Text("Demo only: there are no passwords in this example.", muted=True, size="sm"),
                gap="lg",
                style=Style(max_width=560, margin_x="auto"),
            )
        )
