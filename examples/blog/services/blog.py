"""Posts and comments. Reading is public; writing posts needs the admin session.

The ``@remote`` methods are also a JSON API under ``/api/blog/...``.
"""

import re

from sqlalchemy import select

from rational import FieldError, NotFound
from rational.backend import Service, remote

from models import Comment, CommentOut, Post, PostIn, PostOut


def slugify(text: str) -> str:
    """``"Hello, World!"`` -> ``"hello-world"``: the post's address."""
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:80] or "post"


class BlogService(Service):
    """Posts and comments."""

    @property
    def is_admin(self) -> bool:
        return self.user == "admin"

    @remote(method="GET")
    async def list_posts(self, tag: str | None = None) -> list[PostOut]:
        """Published posts, newest first (drafts too, for the admin)."""
        query = select(Post).order_by(Post.created_at.desc(), Post.id.desc())
        if not self.is_admin:
            query = query.where(Post.published.is_(True))
        async with self.db.session() as db:
            posts = [PostOut.model_validate(p) for p in await db.scalars(query)]
        return [p for p in posts if tag is None or tag in p.tags]

    @remote(method="GET")
    async def get_post(self, slug: str) -> PostOut:
        """One post by its slug."""
        async with self.db.session() as db:
            post = await db.scalar(select(Post).where(Post.slug == slug))
        if post is None or not (post.published or self.is_admin):
            raise NotFound("No such post")  # drafts don't exist for readers
        return PostOut.model_validate(post)

    async def get_post_by_id(self, post_id: int) -> PostOut:
        self.require_admin()
        async with self.db.session() as db:
            post = await db.get(Post, post_id)
        if post is None:
            raise NotFound("No such post")
        return PostOut.model_validate(post)

    @remote(method="GET")
    async def comments(self, slug: str) -> list[CommentOut]:
        """A post's comments, oldest first."""
        post = await self.get_post(slug)
        async with self.db.session() as db:
            rows = await db.scalars(select(Comment).where(Comment.post_id == post.id).order_by(Comment.id))
            return [CommentOut.model_validate(c) for c in rows]

    @remote
    async def add_comment(self, slug: str, author: str, body: str) -> CommentOut:
        """Comment on a post."""
        if not author.strip() or not body.strip():
            raise FieldError("body", "Please write a name and a comment")
        post = await self.get_post(slug)
        async with self.db.transaction() as db:
            comment = Comment(post_id=post.id, author=author.strip()[:60], body=body.strip()[:2000])
            db.add(comment)
            await db.flush()
            return CommentOut.model_validate(comment)

    @remote(auth="required")
    async def save_post(self, post: PostIn, post_id: int | None = None) -> PostOut:
        """Create a post, or update one when ``post_id`` is given."""
        self.require_admin()
        slug = slugify(post.slug or post.title)
        async with self.db.transaction() as db:
            taken = await db.scalar(select(Post.id).where(Post.slug == slug))
            if taken is not None and taken != post_id:
                raise FieldError("slug", f"The address /posts/{slug} is already used")
            row = Post() if post_id is None else await db.get(Post, post_id)
            if row is None:
                raise NotFound("No such post")
            row.slug, row.title, row.summary = slug, post.title.strip(), post.summary.strip()
            row.tags = ", ".join(t.strip().lower() for t in post.tags.split(",") if t.strip())
            row.body, row.published = post.body, post.published
            db.add(row)
            await db.flush()
            return PostOut.model_validate(row)

    @remote(auth="required")
    async def delete_post(self, post_id: int) -> None:
        """Delete a post and its comments."""
        self.require_admin()
        async with self.db.transaction() as db:
            post = await db.get(Post, post_id)
            if post is None:
                raise NotFound("No such post")
            await db.delete(post)

    def require_admin(self) -> None:
        if not self.is_admin:
            raise NotFound("No such post")  # don't even confirm the post exists
