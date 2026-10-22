from rational import Button, Card, Component, Form, Heading, Input, Row, State, Text, Textarea, h

from models import CommentIn
from services import BlogService
from views.styles import COMMENT, COMMENTS


class Comments(Component):
    """The only interactive part of a post page, so the only reason it loads the runtime."""

    slug: str
    comments = State(factory=list)
    version = State(0)

    async def mount(self):
        self.comments = await self.use(BlogService).comments(self.slug)

    async def add(self, form: CommentIn):
        await self.use(BlogService).add_comment(self.slug, form.author, form.body)
        self.comments = await self.use(BlogService).comments(self.slug)
        self.version += 1  # a form with a new key is a fresh form: the fields are cleared

    def render(self):
        return h(
            "section",
            Heading(f"Comments ({len(self.comments)})", level=2),
            *[
                Card(
                    Row(Text(c.author, weight=600, tag="span"), Text(f"{c.created_at:%b %d}", muted=True, tag="span")),
                    Text(c.body),
                    key=c.id,
                    style=COMMENT,
                )
                for c in self.comments
            ],
            Form(
                Input("Name", name="author", required=True, autocomplete="name"),
                Textarea("Comment", name="body", required=True, rows=3),
                Button("Post comment", type="submit"),
                on_submit=self.add,
                key=f"comment-form-{self.version}",
            ),
            aria_label="Comments",
            style=COMMENTS,
        )
