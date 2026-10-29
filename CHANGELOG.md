# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/) (pre-1.0: minor versions may break the API).

## [Unreleased]

### Added
- Sign in with Apple (`rational.oauth.apple(client_id=..., team_id=..., key_id=..., private_key=...)`):
  the client secret is an ES256 JWT signed for every token request, the callback arrives as a
  cross-site form POST and the identity (and the first sign-in name) is read from the ID token,
  whose issuer, audience, expiry and nonce are checked. Needs HTTPS and the `rational[crypto]`
  extra. Every provider's sign-in state now lives in a short-lived signed cookie instead of the
  session (`SameSite=None; Secure` for Apple's cross-site POST). `Provider` gained `secret()` (per-request client secrets),
  `pkce=False` and `response_mode` for providers that deviate from the redirect + PKCE flow.
- Stripe (`rational.stripe`): `Stripe(app, secret_key=...)` with no SDK — `checkout_url(...)`
  signs the parameters into a link that creates the Checkout Session on click (no API call while
  rendering), `checkout(...)`/`portal(...)`/`customer(...)` call the REST API directly, and
  `@stripe.handler` receives only webhook events whose `Stripe-Signature` header verifies against
  the exact raw body (stale or mismatched signatures are rejected before any handler runs; any
  of several `v1` signatures is accepted while the endpoint secret is rolled). Without
  `webhook_secret`, every webhook call is refused.
- `app.on_error` hooks (`rational.errors.ErrorInfo`): one registration receives the unhandled
  exceptions of pages, event handlers, `@remote` methods and jobs, with the kind, request and
  per-kind detail (handler, service/method, job and attempt). Exceptions raised by a hook are
  logged and discarded, so reporting can never break error handling.
- Secret-key rotation: `App(secret_key=..., old_secret_keys=[...])` signs cookies and tokens with
  the newest key while the older ones still verify, so a key change logs nobody out and breaks no
  link: cookies, reset and sign-in links, form checks and checkout links all use `app.signer(salt)`.
  `RATIONAL_OLD_SECRET_KEYS` sets the old keys from the environment. `Signer`, `Box` and `Tokens` take
  `extra_secrets=` for the same behaviour anywhere.
- Per-page HTTP control: `Page.status`, `Page.cache_control` and `Page.etag` (class attributes
  or set in `mount()`). A matching `If-None-Match` (strong or weak) is answered with `304`.
  Pages that load the browser runtime stay `no-store` (they carry a visitor's page id and CSRF
  token), and a response that sets a cookie is never publicly cached.
- Cacheable pages with client components: a page that sets `cache_control` leaves the CSRF token
  out of its HTML, and `rational.call` fetches it from `/_rational/csrf` (and retries) the first
  time a call is refused for lack of one.
- `State(..., query="q")`: state kept in the page URL (read on load, replaced on change, dropped at
  its default), for search and filter pages that are shared, bookmarked and resumed.
- Snapshot restore checks saved state against the deployed components (class, `State` names and
  value types); anything that no longer fits makes the browser reload the page instead.
- `SQLSessionDriver`: sessions, page snapshots and rate-limit counts in a SQL database through
  SQLAlchemy (Postgres in production, SQLite in tests), with compare-and-swap as one guarded
  `UPDATE`. CI now runs the Redis and SQL drivers and the Redis job store against real Postgres
  and Redis servers.

## [0.3.0a1] - 2026-10-29

Production batteries: background jobs, email, account emails, SEO, bot protection and sign-in
with other providers, plus static export for existing sites.

### Added
- Static sites that already exist can be rebuilt exactly: routes ending in `.html` export under
  that name; `@app.page(path, paths=[...])` exports one page per path-parameter value;
  `export_site(relative=True)` / `--relative` links assets relative to each page;
  `not_found=False` / `--no-404` skips the 404 page (a page at `/404.html` replaces it);
  `App(theme=None)` drops the theme stylesheet; `App(favicon=False)` writes no icon link.
- `Page.lang`, `Page.dir`, `Page.favicon`, `Page.head_start` and `Page.head_end`, settable on the
  class or in `mount()`.
- Background jobs (`rational.jobs`): `@jobs.job(retries=...)`, `enqueue`, `enqueue_in`,
  `@jobs.every(...)` schedules that run once per interval across workers; in memory or in Redis
  (`RedisJobStore`), at-least-once with leases.
- Email (`rational.mail`): `Mailer` sends components as HTML email with inline styles and a
  plain-text version, through `SMTP`, `Resend` or `Postmark` (`Console` and `Memory` for
  development and tests), now or in the background through jobs.
- Account emails (`rational.accounts`): subclass `Accounts` with four lookups to get password
  reset (single-use links), email verification and one-time sign-in links, with no account
  discovery and at most one message per address a minute. `Mailer` also sends element trees.
- SEO (`rational.seo`): `Seo(app, site_url=...)` adds canonical URLs, Open Graph and Twitter
  tags, `hreflang` alternates, JSON-LD (`structured(...)`) and `noindex` to pages, and serves
  `/sitemap.xml` (with `paths=` routes) and `/robots.txt`; a static export writes both. Pages gain
  `image`, `canonical`, `noindex`, `alternates` and `structured_data`; a `{lang}` path parameter
  sets the page's language.
- Bot protection (`rational.bots`): `@limit("5/minute", per=...)` for pages, event handlers and
  `@remote` methods (HTTP 429, memory or Redis counters); `HumanCheck()` + `@human` for forms
  (honeypot, signed timing); `Captcha(app, "turnstile" | "hcaptcha" | "recaptcha", ...)` with
  server-side verification and CSP `frame-src`. `TestClient.submit` sends hidden fields like a
  browser; `PageView.click` takes `check=`.
- Sign-in with other providers (`rational.oauth`): `OAuth(app, base_url=..., on_login=...)` with
  `google`, `github`, `microsoft` and any OpenID Connect `oidc(...)` provider; one-time state,
  nonce and PKCE, ending in `session.login`.

### Changed
- `MemorySessionDriver` drops expired keys as it goes, not only when they are read again.
- `Page.title` and `Page.description` can be set in `mount()` (they are no longer class variables).
- Pages without the browser runtime have no `<style>` element unless they use styles, and no
  `data-rw-c` attributes; with `theme=None`, `<html>` has no `data-theme`.
- Releases no longer install a browser: the browser tests run in CI on the same commit, and the
  Playwright install depends on an Ubuntu package mirror that can stall for many minutes.

## [0.2.0a1] - 2026-10-26

The 0.2 series starts here. Its features shipped first in 0.1.0a5 (below) and are large enough to
need a new minor version: from here on, API changes come with a new minor version.

- **Client components**: Python compiled to JavaScript, rendered first by the server.
- **Reactivity**: `@computed`, `@watch`, two-way `bind`, `provide`/`inject`, view transitions.
- **Batteries**: passwords, JSON Web Tokens, signing and encryption, cookies, a typed
  `Repository`, `@app.socket` websockets with rooms.
- **Sessions**: safe across workers (compare-and-swap with merge) and against fixation.
- **Releases**: the version comes from the git tag.

### Changed
- Linux CI runs on `ubuntu-24.04` rather than `ubuntu-latest`, so runner upgrades cannot change or
  stall the build (Ubuntu 26 package mirrors held Playwright installs for over ten minutes).
- Docs deploy from `main` only, and a new deploy no longer cancels one in progress.

## [0.1.0a5] - 2026-10-26

### Added
- `rational.security`: scrypt password hashing (`hash_password`, `verify_password`,
  `password_needs_rehash`), JSON Web Tokens (`Tokens`, HS256 only, expiry and issuer checks, and a
  bearer-token `authenticator` for `app.authenticate`), tamper-proof `Signer` values and AES-GCM
  `Box` encryption (`pip install "rational[crypto]"`). Standard library only, except `Box`.
- App cookies: `ctx.cookies.get/set/delete`, plain, signed or encrypted, with safe defaults;
  `App(secret_key=...)` / `RATIONAL_SECRET_KEY`.
- `Repository(db, Model)`: typed CRUD and `page()` pagination, each call in its own transaction.
- WebSockets: `@app.socket(path)` with `Socket` classes (validated JSON messages, origin, session and
  auth checks, size and rate limits) and rooms that reach every worker through the bus.
- A "batteries" guide: auth, tokens, secrets, cookies, data, sessions and live connections.
- Reactivity: `@computed` (derived values cached until their state changes, with correct dependencies
  for every reader), `@watch("name")` (batched, sync or async reactions that run before re-rendering),
  `bind=self.bind("name")` two-way binding on `Input`, `Textarea`, `Select` and `Checkbox` (typed,
  ignores input that is not valid yet), and `self.provide()` / `self.inject()`. All but provide/inject
  also work in client components.
- `App(view_transitions=True)` animates page changes (cross-document and client navigation).
- Docs: a capability map for developers coming from Vue.
- Client components: `ClientComponent` subclasses are written in a checked subset of Python and
  compiled to JavaScript, so their event handlers run in the browser with no request. The server
  renders them first (real HTML before any script), then the browser hydrates them. They support
  props (including callbacks), JSON state, `mount()`/`hydrated()`, `await self.remote(Service.method, ...)`,
  nested client components, server components passed in as children, and the existing primitives and
  styles, which are traced at compile time. Unsupported code is a compile error naming the file and
  line. Python semantics (truthiness, `==` on lists, `//`, `%`, negative indexes, `str()`, format specs,
  common `str`/`list`/`dict` methods) are kept; a browser test checks the compiled code against Python
  value by value. Pages that only use client components need no session and can be statically exported.
  The extra runtime (`islands.js`, about 10 KiB gzipped) loads only on pages that use them.
- Browser tests run on any Playwright engine via `RATIONAL_BROWSER` (chromium, firefox, webkit); CI runs
  all three. Firefox and WebKit have not been run locally.
- `tests/browser/test_a11y.py`: structural accessibility checks (lang, title, one `<main>`, labels,
  names, duplicate ids, ARIA references, visible focus). Not a full audit; contrast is not measured.
- `App(bus=MemoryBus() | RedisBus(...))`: workers announce session changes so `live_session` pages
  update across workers. `app.bus` is available for custom channels.
- Resumable pages: `App(page_snapshots=driver)` rebuilds a page the server no longer holds from a saved
  JSON snapshot (eviction, restart, another worker). `PersistentSessionStore` now carries JSON-compatible
  session-scope state. `Database(serverless=True)` uses `NullPool`. New "Serverless and ASGI hosts" page.
- `js.optimistic(*ops)`: apply client operations immediately, with rollback when the event fails.
- `App(websocket=True)`: server push over a same-origin, session-checked WebSocket with SSE fallback;
  new `websockets` extra.
- `App(adapter=bootstrap() | tailwind(...), stylesheets=, scripts=)` with `Asset` (integrity, https-only),
  CSP origins for external assets, and `cx()` for class names.
- `Suspense` and `Skeleton`: respond with a fallback immediately and push slow content when ready;
  `data-rw-busy` on `<html>` plus a progress bar while events are in flight.
- Migrations: `rational db init|revision|upgrade|downgrade|current|history` drives Alembic from the
  app's `Database` (no `alembic.ini`), plus `await db.upgrade()` and `Database(metadata=...)`.
  Install with `rational[migrations]`.
- Internationalization: `App(i18n=I18n(...))`, `self.t()` / `ctx.t()` with params and plurals, locale
  negotiation (cookie, `Accept-Language`), `<html lang>`, `js.set_locale()`.
- Fine-grained patches: after an event the server diffs each re-rendered component against its
  previous tree and sends text/attribute edits (or a morph of the smallest changed subtree) instead
  of the whole component, so client-side `js.*` changes survive unrelated updates. Turn off with
  `App(fine_patches=False)`.
- `rational new NAME` scaffolds a small runnable project (app, page, test, README, requirements).
- Persistent sessions: `App(session_store=PersistentSessionStore(driver))` keeps the CSRF token and
  `session.data` (JSON, never pickle) outside the process, through a five-method async
  `SessionDriver` (`get`, `set`, `cas`, `touch`, `delete`). Ships `RedisSessionDriver`
  (`pip install "rational[redis]"`) and a memory driver. Logins and API calls then work on any
  worker and survive restarts; logout is seen everywhere. Writes are compare-and-swap: concurrent
  changes from two workers are merged key by key, and a logged-out session is never written back.
- `SessionBackend` gained async `load`, `rotate` and `save` hooks (trivial for the in-memory store).
- `rational.local_path(value, default="/")` for `?next=` style redirect targets.
- `rational.call(service, method, args, {verb, path})` reaches GET and custom-path `@remote` methods.
- `ModelForm(Model, on_submit=...)`: a form generated from a Pydantic model (labels, help text, HTML
  constraints, selects for enums and literals, pre-filled values, server-side errors).
- Components `Modal` (native `<dialog>`), `Tabs`, `Table`, `Toast`, `Toasts`, `Menu` and `MenuItem`.
  Modal, tabs, menus and toast dismissal run in the browser with no round trip; tabs and menus
  have arrow-key navigation.
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

### Changed
- The version comes from the git tag (hatch-vcs): tagging `vX.Y.Z` releases X.Y.Z and the docs show
  it; releases no longer fail because `__version__` was not bumped.
- Tests enforce 90% branch coverage and a 60-second limit per test; CI jobs stop after 20 minutes.
- Resumable pages work without sticky routing: a worker whose copy of a page is older than the
  browser's rebuilds it from the snapshot instead of answering 409, and snapshot writes are
  compare-and-swap, so two workers cannot both advance one page.
- Live-session sync across workers uses one bus channel (`rational:sessions`) per worker instead of
  one subscription per session, which grew without bound.
- `Checkbox` takes `help=` and `error=` like the other fields (and `ModelForm` passes them); its
  root is now a `<div>` wrapping the label row and the messages.
- `Redirect` raised by an event now also follows `http(s)` URLs on other origins (a payment page,
  say), as it already did during a page render.
- Badges use darker `success_text`, `warning_text` and `danger_text` theme tokens for AA contrast.
- The style compiler's cache is a bounded LRU.
- The repository has no npm files any more (`package.json`, lockfile, `node_modules`): CI checks the
  browser runtime with `node --check` and `npx eslint@10.12.0` using a self-contained config.
  GitHub workflow tokens are read-only by default.

### Fixed
- Form fields had no visible keyboard focus in Safari/WebKit; they now use the theme's focus ring.
- A login in an event handler with a persistent session store answered with the old CSRF token, so
  the next event failed with 403.
- Session rotation state was kept on the shared `App` object, so concurrent requests could rotate
  each other's sessions.
- A request that failed after `session.login()` stored the signed-in session under the old,
  pre-login id before rotating it.
- A component that read `context.user` before any session existed never re-rendered after a login.
- An empty custom session store that defines `__len__` was silently replaced by the default store.
- A `CSRF` header with non-ASCII characters crashed the request instead of failing the check.
- The redirect to `login_path` did not encode `next` and dropped the query string.

### Security
- `srcdoc` is rejected like `on*` attributes; `data` is checked as a URL attribute.
- `js.set_attr` and `js.toggle_attr` apply the renderer's attribute rules (they could set
  `onclick`, `srcdoc` or a `javascript:` URL before).
- `Redirect` refuses `javascript:`, `vbscript:` and `data:` targets; `self.navigate()` refuses
  whitespace and backslash tricks; the examples' `safe_next` helpers, which let `/\host` and
  `/<TAB>/host` through as open redirects, are replaced by `local_path`.
- `js.set_theme` checks its argument before it reaches a cookie.

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
