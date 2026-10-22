from rational import Aside, Column, Heading, Page, Router, Row, State, Style

from services import SocialService
from settings import NETWORK_NAME
from views.components import Composer, PostList, Shell, WhoToFollow
from views.styles import NARROW_SIDEBAR

router = Router()


@router.page("/", auth="required")
class Home(Page):
    """Your timeline, a composer, and suggestions beside it (below it on narrow screens)."""

    title = f"Home · {NETWORK_NAME}"
    posts = State(factory=list)

    async def mount(self):
        await self.reload()

    async def reload(self):
        self.posts = await self.use(SocialService).timeline()

    def render(self):
        return Shell(
            Row(
                Column(
                    Heading("Home", level=1),
                    Composer(posted=self.reload),
                    PostList(self.posts, can_like=True, empty="Follow people to fill your timeline."),
                    gap="md",
                    style=Style(grow=1, min_width=0),
                ),
                Aside(
                    WhoToFollow(followed=self.reload),
                    style=NARROW_SIDEBAR,
                ),
                align="start",
                gap="lg",
                collapse="narrow",
            )
        )
