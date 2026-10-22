"""Settings, read once from the environment."""

import os
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent

BLOG_TITLE = "The Rational Blog"
DATABASE_URL = os.environ.get("DATABASE_URL", f"sqlite+aiosqlite:///{(PROJECT_DIR / 'blog.db').as_posix()}")
ADMIN_PASSWORD = os.environ.get("BLOG_PASSWORD", "rational")  # demo default: set BLOG_PASSWORD for real use
