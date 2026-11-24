"""The blog: the composition root.

Run:  pip install "rational[db]"
      python app.py --dev     # hot reload, readable errors
      python app.py --prod    # production server
"""

import logging

from rational import App

import settings
from models import create_tables, database
from services import BlogService, seed_demo_posts
from views.pages import feed_router, router
from views.styles import THEME

app = App(
    title=settings.BLOG_TITLE, description="Posts and comments.", theme=THEME, database=database, login_path="/login"
)
app.include(router)
app.service(BlogService)  # JSON API under /api/blog/..., docs at /api/docs
app.fastapi.include_router(feed_router)  # a plain FastAPI route: /feed.xml
app.on_startup(create_tables)
app.on_startup(seed_demo_posts)


@app.on_startup
def require_a_password():
    """A copy deployed without BLOG_PASSWORD would be open to anyone who has read this repository."""
    if settings.ADMIN_PASSWORD:
        return
    if not app.debug:
        raise RuntimeError("set BLOG_PASSWORD to the admin password before running the blog in production")
    logging.getLogger("blog").warning("BLOG_PASSWORD is not set: sign in with %r (--dev only)", settings.DEV_PASSWORD)


if __name__ == "__main__":
    app.run()
