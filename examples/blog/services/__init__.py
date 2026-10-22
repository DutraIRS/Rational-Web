"""The rules: drafts, slugs, comments and who may write. Also a JSON API (see /api/docs)."""

from .blog import BlogService, slugify
from .seed import seed_demo_posts

__all__ = ["BlogService", "seed_demo_posts", "slugify"]
