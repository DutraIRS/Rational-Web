# Checks needed on Windows

Requests from the Linux review (`LINUX_REVIEW_PLAN.md` on the Linux machine's desktop) for whoever works
on the Windows machine. Some Linux fixes touch shared code, so Windows needs to confirm nothing
changed there. Tick an item when it's done and write the result under it.

## Regression checks after the Linux changes

- [x] **Full test suite on Windows:** `python -m pytest --ignore=tests/browser --cov`, all passing,
  coverage at least 90%. Report any failure.
- [x] **`--dev` reload and stop** (`src/rational/cli.py`): SIGTERM/SIGHUP handling is skipped on
  Windows by design. Check that Ctrl+C still stops both the supervisor and the app, and that saving a
  file still restarts the app once. The polling watcher now walks folders with `os.walk` and skips
  `.venv`.
- [x] **Dev error pages** (`src/rational/dev.py`): an error in your own code still points at your file
  and line, and frames from the standard library and `site-packages` are still treated as library code
  (the check now uses `sysconfig` paths instead of `sys.base_prefix`).
- [x] **Translation catalogues** (`src/rational/i18n.py`): catalogues still load (now read with
  `iterdir()` and a case-insensitive `.json` suffix).
- [x] **Migrations:** `rational db revision --autogenerate` on an example (e.g. `examples/todos`)
  creates the tables in the first revision; on an app whose metadata has no tables it now refuses
  with a readable message (a change for every OS, approved).
- [x] **Line endings:** `tests/test_client_components.py::test_windows_and_linux_line_endings_compile_alike`
  passes on a checkout with CRLF line endings (`core.autocrlf=true`).
  **Result (Windows 11, Python 3.14.7, branch `linux-port` at `00b1573`, checked 2026-11-22):** 618 passed, 5 skipped (POSIX-only: forked workers, signals, file permissions), coverage 91.57%. No failures.
  **Partial result:** with `CTRL_BREAK_EVENT` sent to the process group (the console's other stop key; Ctrl+C itself needs a person at the console), the supervisor and the app both stopped in 0.1 s and the port was freed. One save of `app.py` restarted the app exactly once. `tests/test_dev_and_cli.py` passes. Still to do by hand: press Ctrl+C in a real console.
  **Result:** an exception raised inside `json.loads` from a page in `myapp.py` gives a dev error page that points at `myapp.py`; the standard library's `json\decoder.py` (under `C:\Program Files\Python314\Lib`) is not shown as user code.
  **Result:** `tests/test_i18n.py` passes.
  **Result:** on a copy of `examples/todos`, `db init` then `db revision --autogenerate` wrote a first revision with `op.create_table('todos', ...)` (its only table). An app whose `Database` metadata has no tables refuses with: `rational db: the database's metadata has no tables to compare with; import your models in the app and pass their base's metadata: Database(url, metadata=Base.metadata)`.
  **Result:** passes with `core.autocrlf=true` (the test file is checked out with CRLF line endings).
  **By hand (2026-11-22), and a bug found and fixed:** Ctrl+C stopped `--dev` at once, but the supervisor ended the app with `terminate()`, which on Windows is `TerminateProcess`: no "Shutting down", no `on_shutdown` hooks, on Ctrl+C and on every hot reload. `cli.py` now starts the app in its own process group and stops it with Ctrl+Break (handled by every uvicorn since 0.27), killing it only after 10 s; Ctrl+Break sent to the supervisor alone is now taken like Ctrl+C instead of leaving the app serving. Re-tested by hand: Ctrl+C shows "Shutting down", the hook runs, and it is still immediate. New test: `test_the_windows_dev_supervisor_lets_the_app_shut_down_its_way` (fails on the old code). Hot reload, including from a file with a syntax error and back, works.

## Windows behaviour the Linux review needs to know

- [x] **Wrong-case static file URLs:** on Linux, `/static/Logo.svg` is a 404 when the file is
  `logo.svg`. Check what Windows does (NTFS ignores case, so it probably serves the file): in
  `examples/media`, run
  `python -c "from app import app; from rational.testing import TestClient; c = TestClient(app).http; print([c.get(p).status_code for p in ['/static/logo.svg', '/static/Logo.svg', '/static/LOGO.SVG']])"`
  and report the three status codes. If Windows answers 200, links written on Windows with the wrong
  case break only after deploying to Linux.
  **Result:** `[200, 200, 200]`. Windows serves `logo.svg` for `/static/Logo.svg` and `/static/LOGO.SVG` too, so a link with the wrong case works on Windows and breaks only after deploying to Linux.
  **Follow-up:** `--dev` now logs a warning the first time a URL under `app.static` is spelled differently from its file (`StaticDirectory` in `src/rational/http.py`).

## More regression checks (added later by the Linux review)

- [ ] **Bus messages across workers** (`src/rational/app.py`, `src/rational/sockets.py`): socket rooms and
  live sessions now sign bus messages with the boot id plus the process id. Run
  `python -m pytest tests/test_sockets_and_repository.py tests/test_bus.py tests/test_live_session.py`
  (the new fork test is skipped on Windows) and report the result. With Redis available, also check that
  a `Socket.publish` from one `--workers 2` worker reaches connections held by the other.
- [x] **Screenshots to compare with Linux (Segoe UI vs Noto Sans):** run each example with
  `python app.py --prod` and take a full-page screenshot of `/` in Edge at 1280 px wide, light and dark
  (Edge dev tools, "Capture full size screenshot"): hello, counter, dashboard (also at 390 and 820 px),
  cv-portfolio, marketplace, social-network `/explore`. Put them in a folder and report its path. The
  Linux screenshots are on the Linux machine in `~/Desktop/LINUX_REVIEW_LOG/rationalweb-artifacts/screenshots/`;
  the review compares wrapping and overflow.
- [x] **Stopping with an open tab** (`src/rational/concurrency.py` `on_stop_signal`, `App.end_streams`): the
  app now adds a handler for SIGINT, SIGTERM and SIGBREAK in front of the server's while it runs. Run an
  app with a page that pushes updates (e.g. `tests/test_dev_and_cli.py`'s clock page, or any page using
  `run_task`) with `python app.py --prod`, open it in Edge, then press Ctrl+C in the console: report how
  long it takes to stop (it used to take about 30 seconds) and whether `on_shutdown` hooks ran. Also check
  `python app.py --dev`: Ctrl+C and a hot reload with the tab open still work as before.
- [x] **Root path on the app's own links** (`src/rational/runtime.py`, `pages.py`, `rendering/nodes.py`,
  `static/islands.js`, `client/compiler.py`): run `python -m pytest tests/test_protocol.py tests/test_export.py
  tests/test_client_components.py`, then `python app.py --export site --root-path /repo` in
  `examples/media` and report the `href`/`src` values in `site/index.html` (expected `/repo/about`,
  `/repo/static/logo.svg`).
- [x] **Connection pre-checks** (`src/rational/stores.py` `redis_from_url`, `backend/database.py`): run
  `python -m pytest tests/test_session_drivers.py tests/test_bus.py tests/test_jobs.py` and report the result.
  **Partial result:** the clock page (a `run_task` that pushes every 0.2 s) with a stream held open by an HTTP client instead of Edge, stopped with `CTRL_BREAK_EVENT`: `--prod` stopped in 0.2 s (exit code 3) and `--dev` in 0.1 s, and the `on_shutdown` hook ran in both. In `--dev`, a save with the stream open restarted the app once. Still to do by hand: Ctrl+C in a console with the page open in Edge.
  **Result:** the three test files pass (86 tests). The export from PowerShell gives `/repo/about`, `/repo/static/logo.svg` (as `href` and `src`) and `/repo/_rational/theme.css?v=...`. Note: from Git Bash, `--root-path /repo` arrives as `C:/Program Files/Git/repo` because Git Bash rewrites arguments that look like paths; use PowerShell, or `MSYS_NO_PATHCONV=1`, or write `//repo`.
  **Result:** 42 passed (fakeredis and SQLite; no real Redis or Postgres on this machine).
  **Result:** taken with Playwright driving Edge 158, full page, light and dark: `C:\Users\quiia\Desktop\WINDOWS_SCREENSHOTS\` (16 files, named `<example>-<width>-<light|dark>.png`). None has horizontal overflow at any width.
  **By hand (2026-11-22):** `--prod`, the clock page open in a browser with its stream connected, Ctrl+C pressed in the console: it stopped at once (it used to take about 30 s), and the `on_shutdown` hook ran (the test app's hook had a typo, so it raised; the error was logged and shutdown went on). `--dev`: see the first section (it stops at once, and now runs the hooks).

  **Partial result:** 32 passed, 1 skipped (the fork test, POSIX only). Not done: the `--workers 2` check with Redis, because there is no Redis server on this machine.