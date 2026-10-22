"""Settings, read once from the environment."""

import os
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent

NETWORK_NAME = "Murmur"
MAX_POST_LENGTH = 280
DATABASE_URL = os.environ.get("DATABASE_URL", f"sqlite+aiosqlite:///{(PROJECT_DIR / 'social.db').as_posix()}")
