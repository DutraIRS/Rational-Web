"""Settings, read once from the environment."""

import os
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent

SHOP_NAME = "Rational Market"
DATABASE_URL = os.environ.get("DATABASE_URL", f"sqlite+aiosqlite:///{(PROJECT_DIR / 'market.db').as_posix()}")
