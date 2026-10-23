# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/) (pre-1.0: minor versions may break the API).

## [Unreleased]

### Added
- More browser-local `js.*` operations: `show`, `hide`, `toggle`, `remove`, `set_text`, `set_value`,
  `copy`, `scroll_to`, `open_dialog`, `close_dialog`. Browser tests now cover them in real Chromium.
- Handler time limits: `App(handler_timeout=seconds)` and the `@timeout(seconds | None)` decorator.
  A handler or remote method that overruns answers `504` with code `timeout`.
- Optional thread offload for synchronous handlers: `App(sync_handlers="thread")` and the
  `@threaded` / `@threaded(enabled=False)` decorators. The default stays `"loop"`.
- A concurrency guide (`docs/concurrency.rst`).
- API-only apps: `App(api_only=True)` serves just the `@remote` services (no pages, runtime script or
  sessions needed), and `App(cors_origins=[...])` lets listed browser origins call the API prefix
  with a bearer token. Credentials are never allowed cross-origin.
- Live sessions: `App(live_session=True)` pushes session-data changes made in one tab to the other
  tabs of the same browser over the stream, with no click needed. Off by default.
- Client-side navigation: `App(client_nav=True)` swaps same-origin links in place (history, title,
  focus and styles handled), and falls back to a normal load on any failure. Events `rw:navigating`
  and `rw:navigated` are fired on `document`.
- Background tasks: `Component.run_task(async_fn, *args)` runs work for as long as the component is
  mounted, and the state it changes is pushed to the browser over a server-sent-events stream
  (`GET /_rational/stream`). Tasks are cancelled on unmount and when the page expires.
- Protocol: responses carry a `seq` number, so the browser applies pushed and event-driven patches in
  render order, and reloads if a reconnect shows it missed a batch.

## [0.1.0a2] - 2026-10-22

### Added
- Static export: `python app.py --export DIR` (and `rational.export.export_site`) writes the
  app's static pages, theme CSS, mounted static directories and a `404.html` as plain HTML for
  any static host, skipping interactive, authenticated and parameterised pages with a reason.
- A `media` example and walkthrough covering local and remote images, multiple favicon sources,
  internal and external links, video sources, and embedded PDF documents through `h()`.
- Structured request logging and telemetry through `app.logging`: request IDs, request and event
  timings, slow-render warnings, and optional OpenTelemetry spans.
- A broken app no longer kills the dev server: import failures and failing startup hooks serve the
  readable error page instead (with live reload, so the browser recovers once you save a fix).
  `rational.cli.TargetError` replaces the `SystemExit` raised for unusable targets.

### Changed
- Examples and the tutorial project use a new layout: `app.py`, `settings.py`, `models/`,
  `services/` and `views/{styles,components,pages}`. Imports are relative inside a layer and
  absolute across layers (`from views.styles import X`).
- Development tooling: CI enforces 88% branch coverage and lints the browser runtime with ESLint
  (`npm ci && npm run lint:js`).

### Fixed
- Sessions are finalized (including id rotation) on handled error and failure responses.
- Page renders, remote service calls and events for one session are serialized, so shared session
  state no longer races across pages.
- Replayed or stale events are rejected with HTTP 409 `stale_revision` and a reload action instead
  of running twice.
- The declared minimum dependency versions (FastAPI 0.110, Pydantic 2.6, Uvicorn 0.27) work; CI
  tests them.
- Every response, including framework assets and the API, carries baseline security headers
  (`X-Content-Type-Options`, `Referrer-Policy`, `X-Frame-Options`).
- The `docs` extra installs the optional dependencies the API reference imports.
- Documentation no longer claims runtime validation of component prop values (annotations are
  static typing hints) and states that multi-worker deployments need sticky routing.

## [0.1.0a1] - 2026-10-22

First public alpha.

### Added
- Component model: `Component`, `Page`, props from annotations, `State` with component, page
  and session scopes, dependency tracking, keyed identity, async `mount()`/`render()`.
- Safe node IR and deterministic HTML serializer (escaping, tag/attribute/URL validation).
- Typed `Style` objects compiled to hashed, deduplicated CSS classes; pseudo-states,
  viewport breakpoints, container queries; four theme presets with light/dark/system modes.
- Primitives: text, headings, buttons, links, images, layout, cards, accessible form controls.
- HTTP event protocol v1 with DOM morphing, CSRF, session binding, payload validation,
  rate and size limits, stale-handler resynchronization.
- `Service` and `@remote`: a typed JSON API under `/api` with OpenAPI docs.
- Async SQLAlchemy integration (`Database`, `Model`).
- `python app.py --dev` (supervised hot reload, live browser reload, readable error pages
  and overlays) and `--prod` (single origin, proxy-aware); `python -m rational`.
- `rational.testing.TestClient`, Playwright browser tests, benchmarks, Sphinx documentation.
- `Router` for declaring pages, services and startup hooks in their own modules (`App.include`).
- Swagger UI at `/api/docs` that sends the session's CSRF token, so "Try it out" works when signed in;
  `App(description=..., version=...)`, API tags from service docstrings.
- `FieldError` for business-rule errors shown under form fields; validator messages without the
  "Value error, " prefix.
- `Badge` and `Avatar` primitives; `js.confirm()` to ask before a server event.
- `rational.testing` finds controls by accessible name (`aria-label`, then text).
- Examples, each laid out as a project: hello, counter, dashboard, cv-portfolio, todos, blog,
  user-platform, marketplace, social-network.
- Documentation: a step-by-step tutorial (tested), example walkthroughs, a project-structure guide,
  GitHub Pages and Read the Docs publishing.
