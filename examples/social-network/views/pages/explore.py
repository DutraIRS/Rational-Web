from rational import Column, Heading, Page, Router, State, Text

from services import SocialService
from settings import NETWORK_NAME
from views.components import PostList, Shell

router = Router()


@router.page("/explore")
class Explore(Page):
    """Everyone's latest posts. Public: anyone can read; signed-in members can like."""

    title = f"Explore · {NETWORK_NAME}"
    posts = State(factory=list)

    async def mount(self):
        self.posts = await self.use(SocialService).explore()

    def render(self):
        return Shell(
            Column(
                Heading("Explore", level=1),
                Text("The latest from everyone.", muted=True),
                PostList(self.posts, can_like=bool(self.context.user)),
                gap="md",
            )
        )
