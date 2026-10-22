"""Load each example project the way ``python app.py`` does: its folder first on ``sys.path``.

Every example uses the same top-level names (``models``, ``services``, ``views``, ``settings``),
so the previous example's modules are forgotten before the next one is imported.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"


def project_modules(folder: Path) -> set[str]:
    """The top-level modules and packages of a project, other than its ``app.py`` entry point."""
    packages = {p.name for p in folder.iterdir() if p.is_dir() and (p / "__init__.py").exists()}
    modules = {p.stem for p in folder.glob("*.py") if p.stem != "app"}
    return packages | modules


def forget_project_modules(folder: Path) -> None:
    names = project_modules(folder)
    for module_name in list(sys.modules):
        if module_name.split(".")[0] in names:
            del sys.modules[module_name]


def load_example(name: str):
    folder = EXAMPLES / name
    forget_project_modules(folder)  # settings are read at import time, and names are shared
    sys.path.insert(0, str(folder))
    try:
        spec = importlib.util.spec_from_file_location(f"example_{name.replace('-', '_')}", folder / "app.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(folder))
    return module


@pytest.fixture
def example(tmp_path, monkeypatch):
    """``example("todos")`` -> the example's ``app`` module, with a private, empty database."""

    def load(name: str):
        monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{(tmp_path / 'test.db').as_posix()}")
        return load_example(name)

    return load
