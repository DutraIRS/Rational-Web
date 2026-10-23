# Rational Web

*Trying to make web development less irrational.*

[![PyPI](https://img.shields.io/pypi/v/rational.svg)](https://pypi.org/project/rational/)
[![Python](https://img.shields.io/pypi/pyversions/rational.svg)](https://pypi.org/project/rational/)
[![License: Unlicense](https://img.shields.io/badge/license-Unlicense-blue.svg)](LICENSE)

Rational Web is a Python-first, object-oriented web framework. Pages, components, services
and models are Python objects. HTML, CSS and JavaScript still exist, but as implementation
details behind one consistent, typed, inspectable API. It is built on FastAPI, Pydantic and
(optionally) SQLAlchemy.

```python
from rational import App, Button, Column, Component, Page, State, Text

app = App()


class Counter(Component):
    count = State(0)

    def increment(self):
        self.count += 1

    def render(self):
        return Column(Text(f"Count: {self.count}"), Button("Increment", on_click=self.increment))


@app.page("/")
class Home(Page):
    def render(self):
        return Counter()


if __name__ == "__main__":
    app.run()
```

```console
$ pip install rational
$ python app.py --dev     # hot reload, live browser reload, readable errors
$ python app.py --prod    # production: pages at /, JSON API at /api, one origin
$ python app.py --export site/   # static pages as plain HTML, for any static host
```

> **Status: alpha (0.1).** The architecture is implemented and tested end to end, including in
> a real browser, but the public API may still change before 1.0.

## Why

Full-stack Python today usually means two codebases: a Python API and a JavaScript front end,
glued together by hand-written fetch calls, duplicated validation and a build pipeline.
Rational Web keeps the whole application in Python **without pretending the browser isn't
there**:

- **Server-rendered first.** Every page is real HTML before any script runs. Static pages ship
  zero JavaScript. Interactive pages load a 4 KiB (gzipped) runtime that wires events and
  morphs updated HTML into place, preserving focus and typing.
- **Explicit boundaries.** Event handlers always run on the server. Only methods marked
  `@remote` become an HTTP API. Nothing is callable from the browser by accident.
- **Typed boundaries.** Path parameters, event payloads and API bodies are validated from your
  annotations by Pydantic. Invalid form input never reaches your handler and shows up next to
  the right field. Component prop annotations support static typing; runtime checks cover required
  and unexpected prop names.
- **Styles as values.** Immutable `Style` objects compile to deduplicated, hashed CSS classes,
  with theme tokens, pseudo-states, `@media` breakpoints and `@container` queries. You get no
  specificity wars, no class-name soup and no CSS injection.
- **Secure by default.** Escaped output, session-bound events, CSRF tokens, session rotation,
  rate and size limits, and an optional nonce-based CSP.

## Features

| | |
|---|---|
| Components | Props from annotations, `State` (component/page/session scope), keyed identity, async `mount()`/`render()` |
| Primitives | `Text`, `Heading`, `Button`, `Link`, `Image`, `Badge`, `Avatar`, `Modal`, `Tabs`, `Table`, `Toast`, `Row`/`Column`/`Stack`/`Grid`, `Card`, `Container`, `Form`, `Input`, `Textarea`, `Select`, `Checkbox`, semantic regions, `h()` for anything else |
| Events | `on_click`, `on_input` (debounced), `on_change`, `on_submit`, `on_enter`, `on_keydown`, `on_blur`; sync or async; lambdas capture values server-side |
| Forms | Pydantic validation from handler annotations; `FieldError` for business rules; messages shown under the right field |
| Local interactions | `js.confirm`, `js.toggle_class`, `js.set_attr`, `js.focus`, `js.set_theme`... run with no round trip |
| Styling | `Style` merging with `\|`, four theme presets, light/dark/system, responsive breakpoints and container queries |
| Backend | `Service` + `@remote` → typed JSON API under `/api`, interactive **Swagger UI** at `/api/docs`; async SQLAlchemy |
| Projects | `Router` (pages and services in their own modules, with prefixes) and a composition root in `app.py` |
| Developer experience | `--dev` hot reload on every OS, live browser reload, error pages that point at *your* line with hints |
| Deployment | `--prod`, `python -m rational`, any ASGI server, mountable under a sub-path, proxy-aware, static export with `--export` |
| Testing | `rational.testing.TestClient` drives pages by accessible name: `page.click("Save")` |

## Examples

Ten complete applications, each laid out like a real project (see [`examples/`](examples/)):

| Example | What you'll learn |
|---|---|
| [hello](examples/hello/) | The smallest app: pages, primitives, zero-JS output |
| [counter](examples/counter/) | State, keys, events, debounced input |
| [media](examples/media/) | Favicons, local and remote images, links, video and document embeds |
| [dashboard](examples/dashboard/) | Breakpoints, container queries, fluid grids, no custom CSS |
| [cv-portfolio](examples/cv-portfolio/) | Content as data, function components, a honeypot contact form |
| [todos](examples/todos/) | Databases, services, per-user isolation, the JSON API |
| [blog](examples/blog/) | Path parameters, safe rich text, a live-preview editor, RSS |
| [user-platform](examples/user-platform/) | Password hashing, authenticators, `FieldError`, roles and an admin area |
| [marketplace](examples/marketplace/) | A session cart shared across tabs, transactional checkout, money |
| [social-network](examples/social-network/) | Follows, likes and timelines with a fixed number of queries |

```console
$ pip install "rational[db]"
$ cd examples/marketplace
$ python app.py --dev
```

## Documentation

The documentation is a Sphinx site in [`docs/`](docs/), published online at
[rational-web.readthedocs.io](https://rational-web.readthedocs.io) and mirrored on
[GitHub Pages](https://dutrairs.github.io/Rational-Web/):

- **Tutorial:** build a guestbook step by step, from one file to a tested, deployed project. Every
  step is a runnable file, executed by the test suite.
- **Examples:** a file-by-file walkthrough of all ten examples.
- **Guide:** components, styling, services and the API, project structure, running and deploying,
  security, testing.
- **Background and reference:** the design record, benchmarks and the full API reference.

Preview it locally, rebuilding as you edit:

```console
$ pip install -e ".[docs]"
$ sphinx-autobuild docs docs/_build/html      # then open http://127.0.0.1:8000
```

Both hosts build from this repository. The `Docs` GitHub Actions workflow builds the site with
warnings as errors and deploys it to GitHub Pages, and `.readthedocs.yaml` configures Read the Docs.

## Benchmarks

Is it blazingly fast? It's Python, so not in the Rust or Go sense. It is built so that the
framework is never the bottleneck of a typical page, and so that the browser does very little
work. The numbers below are measured, not claimed: run `python benchmarks/run.py` to
reproduce them.

These are full requests through the ASGI stack in-process (routing, rendering, CSS compilation,
sessions, JSON) on **one CPU core**, with no network. The baseline is plain FastAPI returning
an equivalent *pre-built* HTML string. Measured on Python 3.14.7, Windows 11, Intel Core
(Tiger Lake).

| Scenario | Requests/s | p50 | p95 |
|---|---:|---:|---:|
| FastAPI baseline: prebuilt HTML string | 2,651 | 0.35 ms | 0.56 ms |
| **Rational: static page** | 1,942 | 0.48 ms | 0.76 ms |
| **Rational: interactive page** (counter) | 1,390 | 0.66 ms | 0.88 ms |
| **Rational: event round trip** (click → patch) | 1,390 | 0.69 ms | 0.92 ms |
| Rational: 100-row styled table page | 390 | 2.39 ms | 2.91 ms |

| On the wire | gzip |
|---|---:|
| `runtime.js` (interactive pages only, cached) | 4.0 KiB |
| Theme CSS (immutable, cached) | 1.2 KiB |
| A click's response | 0.2 KiB |

- A static page keeps ~73% of raw FastAPI throughput while rendering components and
  compiling CSS.
- An interaction costs well under 1 ms of server time, so network latency dominates.
- Rendering costs about 18 µs per element, so pages with thousands of rows should paginate.

See [docs/benchmarks.rst](docs/benchmarks.rst) for the method and the micro-benchmarks.

## Manifesto

1. **Python is the interface; the web platform is the implementation.** We don't hide HTML,
   CSS, JavaScript or HTTP. We give them one coherent, typed front door.
2. **The network is a boundary, not a detail.** Where code runs must always be obvious. Nothing
   crosses the wire unless you said so.
3. **HTML first.** A page should be useful before a single script runs. JavaScript is an
   enhancement, measured in kilobytes.
4. **Secure is the default, not a setting.** Escaping, CSRF, validation and isolation are on
   before you know you need them.
5. **Values over magic.** Styles are immutable values, render output is plain data, and state
   changes are explicit. What happens can be inspected.
6. **Composition over inheritance.** Small pieces combine: `Style | Style`, components in
   components, services in services.
7. **Escape hatches, always.** Raw CSS, raw HTML, FastAPI routes, SQLAlchemy queries and
   custom JavaScript are always available. The framework should never trap you.
8. **Measure, don't claim.** Performance, accessibility and security are tested, not
   asserted.

## Roadmap

**0.1: foundation** *(this release)*
- [x] Component model, `State` scopes, dependency tracking, keyed identity
- [x] Safe HTML IR and serializer, typed `Style` compiler, four themes, responsive variants
- [x] HTTP event protocol with morph patches, CSRF, session binding, validation, rate limits
- [x] Services with `@remote` → typed JSON API, async SQLAlchemy integration
- [x] `--dev` (hot reload, live reload, readable errors) and `--prod` modes
- [x] `Router` for multi-file projects; Swagger UI that works with sessions and CSRF
- [x] Test client, Playwright browser tests, benchmarks
- [x] Sphinx documentation with a step-by-step tutorial and ten example projects

**0.2: interactivity**
- [ ] WebSocket transport (optional) and server push for collaborative pages
  (server push over SSE, page-scoped background tasks and live cross-tab session sync have landed)
- [x] Client-side navigation between pages, with no full reload (`App(client_nav=True)`)
- [ ] Finer-grained server diffs (text and attribute patches)
- [ ] More components: `Menu` (`Modal`, `Tabs`, `Table` and `Toast` have landed)
- [ ] Pluggable session store (for example Redis); page runtimes remain worker-local, so
      multi-worker deployments still need sticky routing

**0.3: productivity**
- [ ] `rational new` project scaffolding and an Alembic migration workflow
- [x] Structured logging and request telemetry (`app.logging`): request IDs, event timing,
      slow-render tracing, standard-library logs + optional OpenTelemetry spans
- [ ] Streaming SSR and loading states
- [ ] Form helpers bound to Pydantic models
- [ ] Internationalization
- [ ] Optional Bootstrap and Tailwind adapters

**1.0: stability**
- [ ] Frozen public API with a deprecation policy
- [ ] Accessibility audit and an automated a11y suite
- [ ] Browser matrix in CI (Chromium, Firefox, WebKit) and load tests
- [ ] Independent security review

Have an idea? Open an issue. The roadmap is a conversation. Longer-term design notes on
concurrency, cross-tab state, client rendering and serverless deployment live in
[`ideas/concurrency-and-state.md`](ideas/concurrency-and-state.md).

## Contributing

```console
git clone https://github.com/DutraIRS/Rational-Web.git
cd Rational-Web
python -m venv .venv
. .venv/bin/activate                                  # Windows: .venv\Scripts\activate
pip install -e ".[dev,docs,browser]"
pytest                                                # browser tests run if Chromium is available
ruff check . && ruff format --check . && mypy
```

See [CONTRIBUTING.md](CONTRIBUTING.md). Report security issues privately as described in
[SECURITY.md](SECURITY.md).

## Sponsor

Rational Web is free, public-domain software built in the open. If it saves you time, or you
want to see the roadmap happen sooner, please consider sponsoring:

- **Ko-fi:** https://ko-fi.com/dutrairs
- **Companies:** sponsorship can fund a specific roadmap item. Get in touch through GitHub.

Sponsors are thanked in the release notes. Thank you for helping keep web development
rational. ❤️

## License

Public domain, under the [Unlicense](LICENSE).
