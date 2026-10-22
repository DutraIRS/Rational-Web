"""Test setup: import the project like ``python app.py`` does, with a throwaway database."""

import os
import sys
import tempfile
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))

# Settings are read when the app is imported, so point them at a temporary database first.
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{(Path(tempfile.mkdtemp()) / 'test.db').as_posix()}"
