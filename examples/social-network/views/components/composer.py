"""Write a post: a debounced counter and a submit that only fires when the draft is valid."""

from collections.abc import Awaitable, Callable

from rational import Button, Card, Component, Form, Row, Spacer, State, Style, Text, Textarea

from models import ComposeForm
from services import SocialService
from settings import MAX_POST_LENGTH
from views.styles import PANEL


class Composer(Component):
    """Write a post. The counter follows your typing (debounced) and the button only enables
    when the post is valid; the server validates again on submit, because it never trusts the browser."""

    posted: Callable[[], Awaitable[None]]
    draft = State("")
    version = State(0)

    def set_draft(self, value: str):
        self.draft = value

    async def publish(self, form: ComposeForm):
        await self.use(SocialService).publish(form.body)
        self.draft = ""
        self.version += 1  # a fresh form: the text area is cleared
        await self.posted()

    def render(self):
        left = MAX_POST_LENGTH - len(self.draft)
        valid = bool(self.draft.strip()) and left >= 0
        return Card(
            Form(
                Textarea(
                    "What's happening?",
                    name="body",
                    rows=3,
                    hide_label=True,
                    placeholder="What's happening?",
                    on_input=self.set_draft,
                ),
                Row(
                    Spacer(),
                    Text(
                        str(left),
                        size="sm",
                        color="danger" if left < 0 else "muted",
                        aria_label=f"{left} characters left",
                    ),
                    Button("Post", type="submit", disabled=not valid),
                ),
                on_submit=self.publish,
                key=f"compose-{self.version}",
                style=Style(gap="sm"),
            ),
            style=PANEL,
        )
