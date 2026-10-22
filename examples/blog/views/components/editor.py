from rational import Badge, Button, ButtonLink, Card, Checkbox, Component, Form, Heading, Input, Row, State, Textarea

from .markup import render_body
from models import PostIn, PostOut
from services import BlogService
from views.styles import EDITOR_HALF, PREVIEW


class Editor(Component):
    """The form on one side and a live preview on the other (stacked on narrow screens).

    Typing in the title or body sends the debounced value to the server, which re-renders
    the preview with the same ``render_body`` the public page uses.
    """

    post: PostOut | None = None
    body = State("")
    heading = State("")

    def mount(self):
        if self.post is not None:
            self.body, self.heading = self.post.body, self.post.title

    def set_body(self, value: str):
        self.body = value

    def set_heading(self, value: str):
        self.heading = value

    async def save(self, form: PostIn):
        await self.use(BlogService).save_post(form, self.post.id if self.post else None)
        self.navigate("/admin")

    def render(self):
        p = self.post
        form = Form(
            Input("Title", name="title", value=p.title if p else None, required=True, on_input=self.set_heading),
            Input("Address", name="slug", value=p.slug if p else None, help="Leave empty to derive it from the title."),
            Input("Summary", name="summary", value=p.summary if p else None),
            Input("Tags", name="tags", value=", ".join(p.tags) if p else None, help="Comma-separated."),
            Textarea(
                "Body",
                name="body",
                value=p.body if p else "",
                rows=14,
                on_input=self.set_body,
                help="## Heading, ### Subheading, - list items; blank lines separate paragraphs.",
            ),
            Checkbox("Published", name="published", checked=bool(p and p.published)),
            Row(Button("Save", type="submit"), ButtonLink("Cancel", href="/admin", variant="ghost")),
            on_submit=self.save,
            style=EDITOR_HALF,
        )
        preview = Card(
            Badge("Preview", tone="primary"),
            Heading(self.heading or "Untitled", level=1),
            *render_body(self.body),
            style=PREVIEW,
            aria_live="polite",
        )
        return Row(form, preview, align="start", gap="lg", collapse="narrow")
