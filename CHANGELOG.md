# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/) (pre-1.0: minor versions may break the API).

## [Unreleased]

### Added
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
