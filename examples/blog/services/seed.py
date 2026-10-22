"""Demo content, inserted on the first start."""

from datetime import UTC, datetime

from sqlalchemy import select

from .blog import slugify
from models import Post, PostIn, database

POSTS = [
    PostIn(
        title="Hello, Rational Web",
        summary="Why we wanted one language from the database to the button.",
        tags="intro, python",
        published=True,
        body="Most web apps are two programs glued together.\n\n"
        "## One model\n\n"
        "Pages, components and services are Python objects.\n\n"
        "- Server-rendered first\n- Explicit boundaries\n- Typed styles",
    ),
    PostIn(
        title="Pages that ship no JavaScript",
        summary="This page has no event handlers, so the browser gets HTML and CSS only.",
        tags="performance",
        published=True,
        body="Open your browser's network tab: no scripts were downloaded for this page.\n\n"
        "Interactive pages get a small runtime, and only they do.",
    ),
    PostIn(
        title="An unfinished draft",
        summary="Only the admin can see drafts.",
        tags="meta",
        body="Work in progress.",
    ),
]


async def seed_demo_posts() -> None:
    async with database.transaction() as db:
        if await db.scalar(select(Post.id).limit(1)) is not None:
            return  # only on an empty database
        for i, post in enumerate(POSTS):
            db.add(
                Post(
                    slug=slugify(post.title),
                    title=post.title,
                    summary=post.summary,
                    body=post.body,
                    tags=post.tags,
                    published=post.published,
                    created_at=datetime(2026, 10, 1 + i * 7, tzinfo=UTC),
                )
            )
