"""Settings, read once from the environment."""

import os
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent

DATABASE_URL = os.environ.get("DATABASE_URL", f"sqlite+aiosqlite:///{(PROJECT_DIR / 'users.db').as_posix()}")
