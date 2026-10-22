# Contributing

Thanks for helping make web development less irrational!

## Setup

```console
$ python -m venv .venv && . .venv/bin/activate      # Windows: .venv\Scripts\activate
$ pip install -e ".[dev,docs,browser]"
$ playwright install chromium                         # optional: real-browser tests
```

## Checks

Every change should pass:

```console
$ pytest                         # unit, integration, examples (+ browser tests if Chromium is present)
$ ruff check . && ruff format --check .
$ mypy                           # strict
$ python -m sphinx -W -b html docs docs/_build/html
```

## Guidelines

- Keep the core small. A feature that can live in user code or an optional module should.
- Every behaviour change needs a test; security-relevant code needs a test for the *attack*,
  not only the happy path.
- Public API changes need docs (`docs/`) and a `CHANGELOG.md` entry under *Unreleased*.
- Performance claims need a benchmark (`benchmarks/run.py`).
- Write code that reads like the code around it.

## Releasing (maintainers)

1. Update `__version__` in `src/rational/__init__.py` and move *Unreleased* entries in
   `CHANGELOG.md` under the new version.
2. Tag `vX.Y.Z` and push the tag. The *Release* workflow builds, checks, and publishes to PyPI
   through trusted publishing.
