"""One post, and a list of posts."""

from datetime import UTC, datetime

from rational import Avatar, Button, Card, Column, Component, Link, Row, Spacer, State, Style, Text

from models import PostView
from services import SocialService
from views.styles import PANEL


def ago(moment: datetime, now: datetime | None = None) -> str:
    """``"just now"``, ``"5m"``, ``"3h"``, ``"2d"``, then a date."""
    if moment.tzinfo is None:  # SQLite returns naive datetimes; we always store UTC
        moment = moment.replace(tzinfo=UTC)
    seconds = ((now or datetime.now(UTC)) - moment).total_seconds()
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{int(seconds // 60)}m"
    if seconds < 86400:
        return f"{int(seconds // 3600)}h"
    if seconds < 7 * 86400:
        return f"{int(seconds // 86400)}d"
    return f"{moment:%b %d}"


class PostCard(Component):
    """One post. Liking updates this card only: its state starts from the props and then
    follows the server's answer, without reloading the whole timeline."""

    post: PostView
    can_like: bool = False
    likes = State(0)
    liked = State(False)

    def mount(self):
        self.likes, self.liked = self.post.likes, self.post.liked

    async def toggle_like(self):
        updated = await self.use(SocialService).toggle_like(self.post.id)
        self.likes, self.liked = updated.likes, updated.liked

    def render(self):
        p = self.post
        hearts = f"♥ {self.likes}"
        count = f"{self.likes} like{'s' if self.likes != 1 else ''}"
        like = (
            Button(
                hearts,
                size="sm",
                variant="secondary" if self.liked else "ghost",
                aria_pressed="true" if self.liked else "false",
                aria_label=f"{'Unlike' if self.liked else 'Like'} post by {p.author_name} ({count})",
                on_click=self.toggle_like,
            )
            if self.can_like
            else Text(hearts, muted=True, size="sm", aria_label=count)
        )
        return Card(
            Row(
                Avatar(p.author_name, size=40),
                Column(
                    Row(
                        Link(p.author_name, href=f"/u/{p.author_handle}", style=Style(font_weight=700)),
                        Text(f"@{p.author_handle} · {ago(p.created_at)}", muted=True, size="sm", tag="span"),
                        gap="xs",
                        wrap=True,
                    ),
                    Text(p.body, style=Style(white_space="pre-wrap", raw={"overflow-wrap": "anywhere"})),
                    Row(Spacer(), like),
                    gap="xs",
                    style=Style(grow=1, min_width=0),
                ),
                align="start",
                gap="sm",
            ),
            style=PANEL,
        )


def PostList(posts: list[PostView], can_like: bool, empty: str = "Nothing here yet."):  # noqa: N802
    if not posts:
        return Text(empty, muted=True)
    return Column(*[PostCard(post=p, can_like=can_like, key=p.id) for p in posts], gap="sm")
