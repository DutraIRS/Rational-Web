# Checks needed on Windows

Requests from the Linux review (`LINUX_REVIEW_PLAN.md` on the Linux machine's desktop) for whoever works
on the Windows machine. Some Linux fixes touch shared code, so Windows needs to confirm nothing
changed there. Tick an item when it's done and write the result under it.

## Regression checks after the Linux changes

- [ ] **Full test suite on Windows:** `python -m pytest --ignore=tests/browser --cov`, all passing,
  coverage at least 90%. Report any failure.
- [ ] **`--dev` reload and stop** (`src/rational/cli.py`): SIGTERM/SIGHUP handling is skipped on
  Windows by design. Check that Ctrl+C still stops both the supervisor and the app, and that saving a
  file still restarts the app once. The polling watcher now walks folders with `os.walk` and skips
  `.venv`.
- [ ] **Dev error pages** (`src/rational/dev.py`): an error in your own code still points at your file
  and line, and frames from the standard library and `site-packages` are still treated as library code
  (the check now uses `sysconfig` paths instead of `sys.base_prefix`).
- [ ] **Translation catalogues** (`src/rational/i18n.py`): catalogues still load (now read with
  `iterdir()` and a case-insensitive `.json` suffix).
- [ ] **Migrations:** `rational db revision --autogenerate` on an example (e.g. `examples/todos`)
  creates the tables in the first revision; on an app whose metadata has no tables it now refuses
  with a readable message (a change for every OS, approved).
- [ ] **Line endings:** `tests/test_client_components.py::test_windows_and_linux_line_endings_compile_alike`
  passes on a checkout with CRLF line endings (`core.autocrlf=true`).

## Windows behaviour the Linux review needs to know

- [ ] **Wrong-case static file URLs:** on Linux, `/static/Logo.svg` is a 404 when the file is
  `logo.svg`. Check what Windows does (NTFS ignores case, so it probably serves the file): in
  `examples/media`, run
  `python -c "from app import app; from rational.testing import TestClient; c = TestClient(app).http; print([c.get(p).status_code for p in ['/static/logo.svg', '/static/Logo.svg', '/static/LOGO.SVG']])"`
  and report the three status codes. If Windows answers 200, links written on Windows with the wrong
  case break only after deploying to Linux.

## More regression checks (added later by the Linux review)

- [ ] **Bus messages across workers** (`src/rational/app.py`, `src/rational/sockets.py`): socket rooms and
  live sessions now sign bus messages with the boot id plus the process id. Run
  `python -m pytest tests/test_sockets_and_repository.py tests/test_bus.py tests/test_live_session.py`
  (the new fork test is skipped on Windows) and report the result. With Redis available, also check that
  a `Socket.publish` from one `--workers 2` worker reaches connections held by the other.
- [ ] **Screenshots to compare with Linux (Segoe UI vs Noto Sans):** run each example with
  `python app.py --prod` and take a full-page screenshot of `/` in Edge at 1280 px wide, light and dark
  (Edge dev tools, "Capture full size screenshot"): hello, counter, dashboard (also at 390 and 820 px),
  cv-portfolio, marketplace, social-network `/explore`. Put them in a folder and report its path. The
  Linux screenshots are on the Linux machine in `~/Desktop/LINUX_REVIEW_LOG/rationalweb-artifacts/screenshots/`;
  the review compares wrapping and overflow.
- [ ] **Stopping with an open tab** (`src/rational/concurrency.py` `on_stop_signal`, `App.end_streams`): the
  app now adds a handler for SIGINT, SIGTERM and SIGBREAK in front of the server's while it runs. Run an
  app with a page that pushes updates (e.g. `tests/test_dev_and_cli.py`'s clock page, or any page using
  `run_task`) with `python app.py --prod`, open it in Edge, then press Ctrl+C in the console: report how
  long it takes to stop (it used to take about 30 seconds) and whether `on_shutdown` hooks ran. Also check
  `python app.py --dev`: Ctrl+C and a hot reload with the tab open still work as before.
- [ ] **Root path on the app's own links** (`src/rational/runtime.py`, `pages.py`, `rendering/nodes.py`,
  `static/islands.js`, `client/compiler.py`): run `python -m pytest tests/test_protocol.py tests/test_export.py
  tests/test_client_components.py`, then `python app.py --export site --root-path /repo` in
  `examples/media` and report the `href`/`src` values in `site/index.html` (expected `/repo/about`,
  `/repo/static/logo.svg`).
- [ ] **Connection pre-checks** (`src/rational/stores.py` `redis_from_url`, `backend/database.py`): run
  `python -m pytest tests/test_session_drivers.py tests/test_bus.py tests/test_jobs.py` and report the result.
