"""Every tutorial step must run as printed in the docs."""

import importlib.util
import sys
from pathlib import Path

from rational.testing import TestClient

STEPS = Path(__file__).resolve().parent.parent / "docs" / "tutorial" / "steps"


def load(step: int):
    spec = importlib.util.spec_from_file_location(f"tutorial_step{step}", STEPS / f"step{step}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_step1_a_page():
    page = TestClient(load(1).app).open("/")
    assert "Leave a message for the next visitor." in page.text and page.manifest is None


def test_step2_components():
    page = TestClient(load(2).app).open("/")
    assert "What a lovely place!" in page.text and "— Grace" in page.text


def test_step3_state_events_forms():
    page = TestClient(load(3).app).open("/")
    page.click("♥ 0")
    assert "♥ 1" in page.text
    data = page.submit({"name": "", "message": ""})
    assert {e["field"] for e in data["error"]["details"]} == {"name", "message"}
    page.submit({"name": "Alan", "message": "Can machines sign guestbooks?"})
    assert page.text.index("Can machines sign guestbooks?") < page.text.index("What a lovely place!")
    assert "♥ 1" in page.text  # the liked card kept its state: keys follow the entries


def test_step4_styles():
    page = TestClient(load(4).app).open("/")
    css = page.dom.find_all("style", id="rw-styles")[0].text
    assert "border-left:4px solid var(--rw-color-primary)" in css and "@media (max-width: 639.98px)" in css


def test_step5_database_and_api(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{(tmp_path / 'step5.db').as_posix()}")
    step5 = load(5)
    with TestClient(step5.app) as client:
        page = client.open("/")
        page.submit({"name": "Ada", "message": "Persisted!"})
        assert "Persisted!" in page.text
        data = page.submit({"name": "Bot", "message": "see https://spam.example"})
        assert data["error"]["details"] == [{"field": "message", "message": "Links are not allowed"}]
        assert client.http.get("/api/guestbook/entries").json()[0]["message"] == "Persisted!"


def test_guestbook_project_tests_run_in_a_subprocess():
    """The finished project's tests run in their own process: same module names, no clashes."""
    import subprocess
    import sys

    project = Path(__file__).resolve().parent.parent / "docs" / "tutorial" / "guestbook"
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests", "-q"],
        cwd=project,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
