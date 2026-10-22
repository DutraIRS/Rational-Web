"""What readers see. The index and tag pages have no handlers, so they ship zero JavaScript."""

from rational import Column, Heading, Link, Page, Router, State, Text, h

import settings
from models import PostOut
from services import BlogService
from views.components import Comments, PostList, PostMeta, Shell, render_body
from views.styles import ARTICLE

router = Router()


@router.page("/")
class Index(Page):
    title = settings.BLOG_TITLE
    description = "Notes on building web apps in Python."
    posts = State(factory=list)

    async def mount(self):
        self.posts = await self.use(BlogService).list_posts()

    def render(self):
        return Shell(
            Column(Heading("Notes", level=1), Text(self.description, muted=True), gap="xs"),
            PostList(self.posts),
            admin=self.context.user == "admin",
        )


@router.page("/tag/{tag}")
class TagPage(Page):
    tag: str  # a path parameter is a prop
    posts = State(factory=list)

    async def mount(self):
        self.title = f"Posts tagged “{self.tag}”"
        self.posts = await self.use(BlogService).list_posts(tag=self.tag)

    def render(self):
        return Shell(Heading(self.title, level=1), PostList(self.posts), Link("← All posts", href="/"))


@router.page("/posts/{slug}")
class PostPage(Page):
    slug: str
    post = State(None)

    async def mount(self):
        self.post = await self.use(BlogService).get_post(self.slug)  # NotFound becomes a 404 page
        self.title = self.post.title
        self.description = self.post.summary

    def render(self):
        post: PostOut = self.post
        return Shell(
            h("article", Heading(post.title, level=1), PostMeta(post), *render_body(post.body), style=ARTICLE),
            Comments(slug=post.slug),
            admin=self.context.user == "admin",
        )
