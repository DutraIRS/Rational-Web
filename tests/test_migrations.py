import sqlite3
import sys
import textwrap

import pytest

pytest.importorskip("alembic")

from rational.cli import main  # noqa: E402

APP = """
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from rational import App
from rational.backend.database import Database


class Base(DeclarativeBase):
    pass


class Note(Base):
    __tablename__ = "notes"
    id: Mapped[int] = mapped_column(primary_key=True)
    body: Mapped[str]


app = App(database=Database("sqlite+aiosqlite:///notes.db", metadata=Base.metadata))
"""


@pytest.fixture
def project(tmp_path, monkeypatch):
    (tmp_path / "app.py").write_text(textwrap.dedent(APP), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.syspath_prepend(str(tmp_path))
    yield tmp_path
    sys.modules.pop("app", None)


def tables(path):
    with sqlite3.connect(path) as conn:
        return {row[0] for row in conn.execute("select name from sqlite_master where type='table'")}


def test_init_revision_upgrade_downgrade(project, capsys):
    main(["db", "init"])
    assert (project / "migrations" / "env.py").exists()

    main(["db", "revision", "app.py", "-m", "add notes", "--autogenerate"])
    versions = list((project / "migrations" / "versions").glob("*.py"))
    assert len(versions) == 1 and "notes" in versions[0].read_text(encoding="utf-8")

    main(["db", "upgrade", "app.py"])
    assert {"notes", "alembic_version"} <= tables(project / "notes.db")

    main(["db", "current", "app.py"])
    main(["db", "history", "app.py"])
    main(["db", "downgrade", "app.py", "base"])
    assert "notes" not in tables(project / "notes.db")


def test_errors_are_readable(project):
    with pytest.raises(SystemExit, match="rational db init"):
        main(["db", "upgrade", "app.py"])
    main(["db", "init"])
    with pytest.raises(SystemExit, match="already contains"):
        main(["db", "init"])
    with pytest.raises(SystemExit, match="-m MESSAGE"):
        main(["db", "revision", "app.py"])


def test_app_without_a_database_is_rejected(tmp_path, monkeypatch):
    (tmp_path / "plain.py").write_text("from rational import App\napp = App()\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    main(["db", "init"])
    with pytest.raises(SystemExit, match="no database"):
        main(["db", "upgrade", "plain.py"])
