"""Writing: sign in, list every post (drafts too), create, edit, publish and delete."""

import hmac

from rational import (
    Button,
    ButtonLink,
    Card,
    Column,
    FieldError,
    Form,
    Heading,
    Input,
    Link,
    Page,
    Router,
    Row,
    Spacer,
    State,
    Style,
    js,
)

import settings
from models import LoginForm, PostIn, PostOut
from services import BlogService
from views.components import Editor, PostMeta, Shell
from views.styles import FLAT_CARD, NARROW_CARD

router = Router()


@router.page("/login")
class Login(Page):
    title = f"Sign in · {settings.BLOG_TITLE}"

    def sign_in(self, form: LoginForm):
        if not hmac.compare_digest(form.password.encode(), settings.ADMIN_PASSWORD.encode()):  # constant time
            raise FieldError("password", "Wrong password")
        self.context.session.login("admin")
        self.navigate("/admin")

    def render(self):
        return Shell(
            Card(
                Heading("Admin sign in", level=1),
                Form(
                    Input("Password", name="password", type="password", required=True, autocomplete="current-password"),
                    Button("Sign in", type="submit"),
                    on_submit=self.sign_in,
                ),
                style=NARROW_CARD,
            )
        )


@router.page("/admin", auth="required")
class Dashboard(Page):
    title = f"Admin · {settings.BLOG_TITLE}"
    posts = State(factory=list)

    async def mount(self):
        await self.reload()

    async def reload(self):
        self.posts = await self.use(BlogService).list_posts()

    async def toggle(self, post: PostOut):
        changes = post.model_dump(include={"title", "slug", "summary", "body"})
        await self.use(BlogService).save_post(
            PostIn(**changes, tags=", ".join(post.tags), published=not post.published), post.id
        )
        await self.reload()

    async def delete(self, post_id: int):
        await self.use(BlogService).delete_post(post_id)
        await self.reload()

    def sign_out(self):
        self.context.session.logout()
        self.navigate("/")

    def row(self, post: PostOut):
        return Card(
            Row(
                Column(
                    Link(post.title, href=f"/posts/{post.slug}", style=Style(font_weight=600)), PostMeta(post), gap="xs"
                ),
                Spacer(),
                ButtonLink("Edit", href=f"/admin/posts/{post.id}", variant="outline", size="sm"),
                Button(
                    "Unpublish" if post.published else "Publish",
                    variant="secondary",
                    size="sm",
                    on_click=lambda: self.toggle(post),
                ),
                Button(
                    "Delete",
                    variant="danger",
                    size="sm",
                    aria_label=f"Delete {post.title}",
                    on_click=[js.confirm(f"Delete “{post.title}” and its comments?"), lambda: self.delete(post.id)],
                ),
                wrap=True,
            ),
            key=post.id,
            style=FLAT_CARD,
        )

    def render(self):
        return Shell(
            Row(
                Heading("Posts", level=1),
                Spacer(),
                ButtonLink("New post", href="/admin/posts/new"),
                Button("Sign out", variant="ghost", on_click=self.sign_out),
            ),
            Column(*[self.row(post) for post in self.posts], gap="sm"),
            admin=True,
        )


@router.page("/admin/posts/new", auth="required")
class NewPost(Page):
    title = f"New post · {settings.BLOG_TITLE}"

    def render(self):
        return Shell(Heading("New post", level=1), Editor(), admin=True)


@router.page("/admin/posts/{post_id}", auth="required")
class EditPost(Page):
    post_id: int
    post = State(None)

    async def mount(self):
        self.post = await self.use(BlogService).get_post_by_id(self.post_id)
        self.title = f"Edit “{self.post.title}”"

    def render(self):
        return Shell(Heading("Edit post", level=1), Editor(post=self.post), admin=True)
