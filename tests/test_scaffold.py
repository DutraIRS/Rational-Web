import subprocess
import sys

import pytest

from rational.cli import main
from rational.scaffold import ScaffoldError, scaffold


def test_scaffold_writes_the_project(tmp_path):
    files = scaffold("my-site", tmp_path)
    assert (tmp_path / "my-site" / "app.py").read_text().count("My Site") == 1
    assert {"app.py", "tests/test_home.py", "README.md"} <= {f.as_posix() for f in files}


@pytest.mark.parametrize("bad", ["", "1abc", "has space", "../escape", "a/b"])
def test_bad_names_are_rejected(tmp_path, bad):
    with pytest.raises(ScaffoldError):
        scaffold(bad, tmp_path)


def test_existing_nonempty_directory_is_refused(tmp_path):
    (tmp_path / "site").mkdir()
    (tmp_path / "site" / "keep.txt").write_text("mine")
    with pytest.raises(ScaffoldError):
        scaffold("site", tmp_path)
    assert (tmp_path / "site" / "keep.txt").read_text() == "mine"


def test_an_empty_existing_directory_is_fine(tmp_path):
    (tmp_path / "site").mkdir()
    scaffold("site", tmp_path)
    assert (tmp_path / "site" / "app.py").exists()


def test_cli_creates_a_project_and_reports_errors(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    main(["new", "demo"])
    assert (tmp_path / "demo" / "app.py").exists() and "cd demo" in capsys.readouterr().out
    with pytest.raises(SystemExit) as exc:
        main(["new", "demo"])
    assert "not empty" in str(exc.value)


def test_generated_project_passes_its_own_tests(tmp_path):
    scaffold("fresh", tmp_path)
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"],
        cwd=tmp_path / "fresh",
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
