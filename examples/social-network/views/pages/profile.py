from rational import Avatar, Button, Card, Column, Heading, Link, Page, Router, Row, Spacer, State, Style, Text

from models import ProfileView
from services import SocialService
from settings import NETWORK_NAME
from views.components import PostList, Shell

router = Router()


def Stat(value: int, label: str):  # noqa: N802 - a function component
    return Column(Text(str(value), weight=800, size="lg"), Text(label, muted=True, size="sm"), gap=0)


@router.page("/u/{handle}")
class Profile(Page):
    handle: str
    profile = State(None)
    posts = State(factory=list)

    async def mount(self):
        service = self.use(SocialService)
        self.profile = await service.profile(self.handle)  # NotFound -> 404 page
        self.posts = await service.posts_by(self.handle)
        self.title = f"{self.profile.name} (@{self.profile.handle}) · {NETWORK_NAME}"

    async def toggle_follow(self):
        self.profile = await self.use(SocialService).toggle_follow(self.profile.handle)

    def render(self):
        p: ProfileView = self.profile
        signed_in = bool(self.context.user)
        if p.is_me:
            action = Text("This is you.", muted=True, size="sm")
        elif signed_in:
            action = Button(
                "Following" if p.followed_by_me else "Follow",
                variant="secondary" if p.followed_by_me else "primary",
                aria_pressed="true" if p.followed_by_me else "false",
                on_click=self.toggle_follow,
            )
        else:
            action = Link("Sign in to follow", href=f"/login?next=/u/{p.handle}")
        return Shell(
            Card(
                Row(
                    Avatar(p.name, size=72),
                    Column(Heading(p.name, level=1), Text(f"@{p.handle}", muted=True), gap=0),
                    Spacer(),
                    action,
                    wrap=True,
                    gap="md",
                ),
                Text(p.bio) if p.bio else None,
                Row(Stat(p.posts, "posts"), Stat(p.followers, "followers"), Stat(p.following, "following"), gap="xl"),
                style=Style(shadow="none"),
            ),
            Column(
                Heading("Posts", level=2),
                PostList(self.posts, can_like=signed_in, empty=f"@{p.handle} hasn't posted yet."),
                gap="sm",
                style=Style(margin_top="lg"),
            ),
        )
