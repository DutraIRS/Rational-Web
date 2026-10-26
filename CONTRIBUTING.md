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
$ pytest --cov=rational --cov-branch   # CI requires >= 88% branch coverage (add --ignore=tests/browser to skip the browser)
$ ruff check . && ruff format --check .
$ mypy                           # strict
$ npx --yes eslint@10.12.0 src/rational/static   # the browser runtime; installs nothing here
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

1. Move *Unreleased* entries in `CHANGELOG.md` under the new version and commit.
2. Tag `vX.Y.Z` and push the commit and tag together: `git push --atomic origin main vX.Y.Z`.
   The version comes from the tag (there is no version number to edit). The *Release* workflow
   builds, checks, and, once a maintainer approves the `pypi` environment, publishes to PyPI
   through trusted publishing; the docs are rebuilt from `main` with that version.
