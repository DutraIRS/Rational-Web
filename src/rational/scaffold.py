"""``rational new NAME``: write a small, runnable project to start from."""

from __future__ import annotations

import re
from pathlib import Path

NAME_RE = re.compile(r"[A-Za-z][A-Za-z0-9_-]*\Z")

APP = '''"""The composition root: build the app from its parts.

Run:  python app.py --dev     # hot reload, readable errors
      python app.py --prod    # production server
"""

from rational import App

from views.pages import router

app = App(title={title!r}, theme="modern")
app.include(router)

if __name__ == "__main__":
    app.run()
'''

PAGES_INIT = """from .home import router

__all__ = ["router"]
"""

HOME = '''"""The home page. Components render on the server; handlers run there too."""

from rational import Button, Column, Container, Heading, Page, Router, State, Text, js

router = Router()


@router.page("/")
class Home(Page):
    title = {title!r}
    count = State(0)

    def increment(self):
        self.count += 1

    def render(self):
        return Container(
            Column(
                Heading("Welcome to " + {title!r}, level=1),
                Text(f"Clicked {{self.count}} times", muted=True),
                Button("Click me", on_click=self.increment),
                Button("Toggle theme", variant="outline", size="sm", on_click=js.toggle_theme()),
            ),
            tag="main",
            max_width=720,
        )
'''

CONFTEST = '''"""Import the project the way ``python app.py`` does."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
'''

TEST_HOME = """from app import app
from rational.testing import TestClient


def test_home_counts_clicks():
    with TestClient(app) as client:
        page = client.open("/")
        assert "Clicked 0 times" in page.text
        page.click("Click me")
        page.click("Click me")
        assert "Clicked 2 times" in page.text
"""

README = """# {title}

A [Rational Web](https://github.com/DutraIRS/Rational-Web) app.

```console
python -m venv .venv
. .venv/bin/activate          # Windows: .venv\\Scripts\\activate
pip install -r requirements.txt
python app.py --dev           # http://127.0.0.1:8000, hot reload
pytest                        # tests use rational.testing, no browser needed
python app.py --prod          # production server
```

Layout: `app.py` builds the app, `views/pages/` holds pages (add one file per page and
register it in `views/pages/__init__.py`), `tests/` holds the tests.
"""

REQUIREMENTS = "rational[testing]\npytest\n"
GITIGNORE = ".venv/\n__pycache__/\n.pytest_cache/\n.env\nbuild/\n*.db\n"


class ScaffoldError(Exception):
    """The project could not be created."""


def scaffold(name: str, parent: Path | None = None) -> list[Path]:
    """Create ``parent/name`` and return the files written (relative to it)."""
    if not NAME_RE.match(name):
        raise ScaffoldError(f"{name!r} is not a usable project name: start with a letter, then letters, digits, - or _")
    target = (parent or Path.cwd()) / name
    if target.exists() and any(target.iterdir()):
        raise ScaffoldError(f"{target} already exists and is not empty")
    title = name.replace("-", " ").replace("_", " ").title()
    files = {
        "app.py": APP.format(title=title),
        "views/__init__.py": "",
        "views/pages/__init__.py": PAGES_INIT,
        "views/pages/home.py": HOME.format(title=title),
        "tests/conftest.py": CONFTEST,
        "tests/test_home.py": TEST_HOME,
        "requirements.txt": REQUIREMENTS,
        "README.md": README.format(title=title),
        ".gitignore": GITIGNORE,
    }
    for relative, content in files.items():
        path = target / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="\n")
    return [Path(p) for p in files]
