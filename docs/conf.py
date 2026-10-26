"""Sphinx configuration for the Rational Web documentation.

Build locally:  python -m sphinx -W -b html docs docs/_build/html
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import rational  # noqa: E402

project = "Rational Web"
author = "Iago Riveiro Santos Dutra"
copyright = "2026, Iago Riveiro Santos Dutra (public domain, Unlicense)"
release = rational.__version__.split("+")[0]  # the tag, or e.g. 0.2.0.dev3 between tags
version = ".".join(release.split(".")[:2])

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.intersphinx",
    "sphinx.ext.viewcode",
]

autodoc_member_order = "bysource"
autodoc_typehints = "description"
autodoc_default_options = {"members": True, "show-inheritance": True}
intersphinx_mapping = {"python": ("https://docs.python.org/3", None)}

exclude_patterns = ["_build"]
html_theme = "furo"
html_title = f"Rational Web {release}"
