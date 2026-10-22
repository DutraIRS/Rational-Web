"""RSS 2.0 at ``/feed.xml``, as a plain FastAPI router: the escape hatch for anything that isn't a page."""

from xml.sax.saxutils import escape

from fastapi import APIRouter, Response
from sqlalchemy import select

import settings
from models import Post, database

router = APIRouter()


@router.get("/feed.xml", include_in_schema=False)
async def feed() -> Response:
    async with database.session() as db:
        posts = await db.scalars(select(Post).where(Post.published.is_(True)).order_by(Post.created_at.desc()))
        items = "".join(
            f"<item><title>{escape(p.title)}</title><link>/posts/{escape(p.slug)}</link>"
            f"<description>{escape(p.summary)}</description></item>"
            for p in posts
        )
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel>'
        f"<title>{escape(settings.BLOG_TITLE)}</title><link>/</link><description>Notes</description>{items}"
        "</channel></rss>"
    )
    return Response(xml, media_type="application/rss+xml")
