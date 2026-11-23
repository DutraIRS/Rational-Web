"""Command line: ``python app.py --dev | --prod`` and ``python -m rational <target> ...``.

Modes
-----
``--dev``   auto-reload on code changes, live browser reload, readable error pages and
            overlays, binds to 127.0.0.1. The default unless ``RATIONAL_ENV=production``.
``--prod``  one origin serving pages at ``/``, the JSON API under ``/api`` and framework
            assets under ``/_rational``; no debug output; honours ``HOST``/``PORT``;
            trusts proxy headers from ``FORWARDED_ALLOW_IPS`` (default 127.0.0.1).

Hot reload uses a small supervisor rather than uvicorn's reloader (which can hang on
Windows): the app runs in a child process that restarts whenever a ``*.py`` file changes.

``--export DIR`` does not serve at all: it writes the app's static pages to ``DIR`` as plain
HTML (see :mod:`rational.export`).

``rational new NAME`` writes a small runnable project (see :mod:`rational.scaffold`).

Page views live in process memory, so ``--workers`` > 1 needs sticky sessions or page snapshots
(``App(page_snapshots=...)``).
"""

from __future__ import annotations

import argparse
import contextlib
import importlib
import importlib.util
import os
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .dev import DEV_ENV, hide_reload_checks

if TYPE_CHECKING:
    from .app import App

Target = tuple[str, str, str]  # (module, attribute, directory) to re-import the app in a child process

SUPERVISED_ENV = "RATIONAL_SUPERVISED"
STOP_SECONDS = 10  # how long the app may take to shut down (its hooks, its tasks) on a restart or a stop
# Signals that end the dev supervisor at once unless it handles them, leaving the app running.
if sys.platform == "win32":
    _SUPERVISOR_STOP_SIGNALS = (signal.SIGBREAK,)
else:
    _SUPERVISOR_STOP_SIGNALS = (signal.SIGTERM, signal.SIGHUP)
# Seconds open connections get when the server stops: a live stream would otherwise hold it up forever.
GRACEFUL_SECONDS = {"dev": 1, "prod": 30}


class TargetError(Exception):
    """The requested target could not be loaded as a Rational app."""


_IGNORED_DIRS = {".git", ".venv", "venv", "__pycache__", "node_modules", ".mypy_cache", ".ruff_cache", ".pytest_cache"}


def build_parser(prog: str | None = None) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=prog, description="Run a Rational Web app.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--dev",
        dest="mode",
        action="store_const",
        const="dev",
        help="development: hot reload, readable errors (default)",
    )
    mode.add_argument(
        "--prod",
        dest="mode",
        action="store_const",
        const="prod",
        help="production: no debug output, proxy-aware, HOST/PORT from the environment",
    )
    parser.add_argument("--host", help="bind address (dev: 127.0.0.1, prod: $HOST or 0.0.0.0)")
    parser.add_argument("--port", type=int, help="port (default: $PORT or 8000)")
    parser.add_argument("--workers", type=int, default=1, help="prod only; >1 needs sticky sessions or page snapshots")
    parser.add_argument("--root-path", default="", help="URL prefix when served under a sub-path by a proxy")
    parser.add_argument("--no-reload", action="store_true", help="dev only: disable auto-reload")
    parser.add_argument("--log-level", default=None, help="uvicorn log level (default: info)")
    parser.add_argument("--app-dir", default=None, help="directory to import the app from (python -m rational)")
    parser.add_argument(
        "--export",
        metavar="DIR",
        default=None,
        help="write the app's static pages to DIR as plain HTML instead of serving (use --root-path for sub-paths)",
    )
    parser.add_argument(
        "--relative",
        action="store_true",
        help="export: link assets relative to each page, so the site also works from disk",
    )
    parser.add_argument("--no-404", action="store_true", help="export: write no 404.html")
    return parser


def export(app: App, directory: str, root_path: str = "", *, relative: bool = False, not_found: bool = True) -> int:
    """Run a static export and print what was written and skipped. Returns the exit code."""
    import asyncio

    from .export import export_site

    os.environ.pop(DEV_ENV, None)
    report = asyncio.run(export_site(app, directory, base_path=root_path, relative=relative, not_found=not_found))
    for page in report.pages:
        print(f"  exported  {page}")
    for page, reason in report.skipped:
        print(f"  skipped   {page}  ({reason})")
    print(f"\n{len(report.pages)} page(s) written to {directory}")
    return 0 if report.pages else 1


def resolve_mode(requested: str | None) -> str:
    if requested:
        return requested
    return "prod" if os.environ.get("RATIONAL_ENV", "").lower() in ("prod", "production") else "dev"


def serve(app: App, argv: Sequence[str] | None = None, *, target: Target | None = None, **overrides: Any) -> None:
    """Parse ``argv`` (default: ``sys.argv[1:]``) and run ``app`` with uvicorn."""
    args = build_parser().parse_args(sys.argv[1:] if argv is None else list(argv))
    if args.export:
        raise SystemExit(export(app, args.export, args.root_path, relative=args.relative, not_found=not args.no_404))
    mode = resolve_mode(overrides.pop("mode", None) or args.mode)
    target = target or _main_target(app)
    port = overrides.pop("port", None) or args.port or int(os.environ.get("PORT", 8000))
    options: dict[str, Any] = {"port": port, "root_path": args.root_path, "log_level": args.log_level or "info"}
    overrides.setdefault("timeout_graceful_shutdown", GRACEFUL_SECONDS[mode])
    run = _serve_dev if mode == "dev" else _serve_prod
    run(app, args, target, options, overrides)


def _serve_dev(
    app: App, args: argparse.Namespace, target: Target | None, options: dict[str, Any], overrides: dict[str, Any]
) -> None:
    import uvicorn

    os.environ[DEV_ENV] = "1"
    app.debug = True
    host = options["host"] = overrides.pop("host", None) or args.host or "127.0.0.1"
    reload = target is not None and not args.no_reload
    if not os.environ.get(SUPERVISED_ENV):  # the supervisor already printed the banner
        notes = [
            "hot reload on" if reload else "hot reload off (run the app file as a script to enable it)",
            "readable errors, live browser reload",
            *_api_note(app, host, options["port"]),
            "not for production: use --prod",
        ]
        _banner("development", host, options["port"], notes)
        if host not in ("127.0.0.1", "localhost", "::1"):
            print("  !  dev mode on a public interface exposes tracebacks and source code.\n")
    if reload and target is not None:
        supervise(target, args, host, options["port"])
    else:
        hide_reload_checks()
        uvicorn.run(app, **options, **overrides)


def _serve_prod(
    app: App, args: argparse.Namespace, target: Target | None, options: dict[str, Any], overrides: dict[str, Any]
) -> None:
    import uvicorn

    os.environ.pop(DEV_ENV, None)
    app.debug = False
    options.update(
        host=overrides.pop("host", None) or args.host or os.environ.get("HOST", "0.0.0.0"),
        proxy_headers=True,
        forwarded_allow_ips=os.environ.get("FORWARDED_ALLOW_IPS", "127.0.0.1"),
        server_header=False,
    )
    notes = [f"pages at /, API at {app.api_prefix}, assets at /_rational"]
    notes += _api_note(app, options["host"], options["port"])
    if args.workers > 1 and app.resume is None:
        notes.append(f"{args.workers} workers: page views are per process, so use sticky sessions or page snapshots")
    _banner("production", options["host"], options["port"], notes)
    if args.workers <= 1:
        uvicorn.run(app, **options, **overrides)
        return
    if target is None:
        raise SystemExit("--workers > 1 needs an importable app: python -m rational module:app --prod")
    module, attr, directory = target
    uvicorn.run(f"{module}:{attr}", workers=args.workers, app_dir=directory, **options, **overrides)


def main(argv: Sequence[str] | None = None) -> None:
    """``python -m rational path/to/app.py|module:attr [--dev|--prod] [options]`` or ``rational new NAME``"""
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "new":
        _new(argv[1:])
        return
    if argv and argv[0] == "db":
        _db(argv[1:])
        return
    if not argv or argv[0].startswith("-"):
        raise SystemExit(
            "usage: python -m rational <app.py | module:attr> [--dev | --prod] [options]\n"
            "       python -m rational new <name>\n"
            "       python -m rational db <init|revision|upgrade|downgrade|current|history> ..."
        )
    args = build_parser().parse_known_args(argv[1:])[0]
    mode = resolve_mode(args.mode)
    try:
        app, target = load_target(argv[0], args.app_dir)
    except TargetError as exc:
        raise SystemExit(str(exc)) from None
    except Exception:
        if mode != "dev":
            raise
        _serve_broken(argv, args)
        return
    serve(app, argv[1:], target=target)


def _db(argv: Sequence[str]) -> None:
    parser = argparse.ArgumentParser(prog="rational db", description="Database migrations (Alembic).")
    parser.add_argument("action", choices=["init", "revision", "upgrade", "downgrade", "current", "history"])
    parser.add_argument("target", nargs="?", default="app.py", help="app file or module:attr (default: app.py)")
    parser.add_argument(
        "revision", nargs="?", help="upgrade: revision (default head); downgrade: revision (default -1)"
    )
    parser.add_argument("-m", "--message", help="revision: message")
    parser.add_argument("--autogenerate", action="store_true", help="revision: diff the models against the database")
    parser.add_argument("--directory", default="migrations", help="migrations folder (default: migrations)")
    parser.add_argument("--app-dir", default=None)
    args = parser.parse_args(list(argv))
    try:
        from .backend import migrations

        if args.action == "init":
            print(f"Created {migrations.init(args.directory)}/")
            return
        app, _target = load_target(args.target, args.app_dir)
        if app.db is None:
            raise SystemExit("rational db: the app has no database; pass App(database=Database(...))")
        db = app.db
        if args.action == "revision":
            if not args.message:
                raise SystemExit("rational db revision: -m MESSAGE is required")
            migrations.revision(db, args.directory, args.message, args.autogenerate)
        elif args.action == "upgrade":
            migrations.upgrade(db, args.directory, args.revision or "head")
        elif args.action == "downgrade":
            migrations.downgrade(db, args.directory, args.revision or "-1")
        elif args.action == "current":
            migrations.current(db, args.directory)
        else:
            migrations.history(db, args.directory)
    except ImportError as exc:
        if (exc.name or "").partition(".")[0] not in ("alembic", "sqlalchemy"):
            raise  # the app's own import failed: its traceback says more than a hint could
        raise SystemExit(f"rational db: {exc}; pip install 'rational[migrations]'") from None
    except (TargetError, migrations.MigrationError) as exc:
        raise SystemExit(f"rational db: {exc}") from None


def _new(argv: Sequence[str]) -> None:
    from .scaffold import ScaffoldError, scaffold

    parser = argparse.ArgumentParser(prog="rational new", description="Create a new Rational Web project.")
    parser.add_argument("name", help="project name; also the directory to create")
    args = parser.parse_args(list(argv))
    try:
        scaffold(args.name)
    except ScaffoldError as exc:
        raise SystemExit(f"rational new: {exc}") from None
    print(f"Created {args.name}/\n\n  cd {args.name}\n  pip install -r requirements.txt\n  python app.py --dev")


def _serve_broken(argv: Sequence[str], args: argparse.Namespace) -> None:
    """Dev mode with an unimportable app: keep the server up showing the error page."""
    import traceback as traceback_module

    import uvicorn

    exc = sys.exc_info()[1]
    assert exc is not None
    traceback_module.print_exception(type(exc), exc, exc.__traceback__)
    host = args.host or "127.0.0.1"
    port = args.port or int(os.environ.get("PORT", 8000))
    if os.environ.get(SUPERVISED_ENV) or args.no_reload:
        from . import dev

        hide_reload_checks()
        uvicorn.run(dev.broken_app(exc, "while importing the app"), host=host, port=port, log_level="info")
        return
    # Reload without a supervised child only works for a file target we can watch.
    supervise_target: Target | None = None
    first = argv[0] if argv else None
    if first and first.endswith(".py"):
        p = Path(first).resolve()
        supervise_target = (p.stem, "", str(p.parent))
    if supervise_target is None:
        from . import dev

        hide_reload_checks()
        uvicorn.run(dev.broken_app(exc, "while importing the app"), host=host, port=port, log_level="info")
        return
    supervise(supervise_target, args, host, port)


def load_target(spec: str, app_dir: str | None = None) -> tuple[App, Target]:
    from .app import App

    if spec.endswith(".py"):
        path = Path(spec).resolve()
        module_name, attr, directory = path.stem, None, str(path.parent)
    else:
        module_name, _, attr = spec.partition(":")
        directory = str(Path(app_dir).resolve()) if app_dir else os.getcwd()
    if directory not in sys.path:
        sys.path.insert(0, directory)
    module = importlib.import_module(module_name)
    if attr:
        app = getattr(module, attr)
    else:
        found = [(name, value) for name, value in vars(module).items() if isinstance(value, App)]
        if not found:
            raise TargetError(f"no rational.App instance found in {spec}")
        attr, app = found[0]
    if not isinstance(app, App):
        raise TargetError(f"{spec} is not a rational.App")
    return app, (module_name, attr, directory)


def supervise(target: Target, args: argparse.Namespace, host: str, port: int) -> None:
    """Run the app in a child process and restart it whenever a Python file changes.

    Ctrl+C stops the child too. So do SIGTERM and SIGHUP (on Windows, Ctrl+Break) sent to the supervisor
    alone (``kill``, systemd, ``docker stop``), which would otherwise leave the child serving on the port.
    Restarts and stops let the child shut down its way, so its ``on_shutdown`` hooks run.
    """
    module, attr, directory = target
    spec = f"{module}:{attr}" if attr else module
    command = [sys.executable, "-m", "rational", spec, "--app-dir", directory, "--dev", "--no-reload",
               "--host", host, "--port", str(port), "--root-path", args.root_path]  # fmt: skip
    if args.log_level:
        command += ["--log-level", args.log_level]
    env = {**os.environ, DEV_ENV: "1", SUPERVISED_ENV: "1"}
    received: list[int] = []
    with _interrupt_on_termination(received):
        child = _start(command, env)
        try:
            for changed in watch(directory):
                print(f"  ->  {changed} changed, restarting", flush=True)
                _stop(child)
                child = _start(command, env)
        except KeyboardInterrupt:
            pass
        finally:
            _stop(child)
    for signum in received[:1]:
        signal.raise_signal(signum)  # the child is gone: now end the way that signal ends a process


@contextlib.contextmanager
def _interrupt_on_termination(received: list[int]) -> Iterator[None]:
    """Turn SIGTERM and SIGHUP (on Windows, SIGBREAK) into the KeyboardInterrupt that Ctrl+C raises, once.

    Their default action ends the process at once, without the ``finally`` that stops the child.
    Only signals left at that default are taken (``nohup`` ignores SIGHUP, and so do we). They are
    appended to ``received``, and the previous handlers are back on exit.
    """
    if threading.current_thread() is not threading.main_thread():
        yield
        return

    def interrupt(signum: int, frame: object) -> None:
        received.append(signum)
        if len(received) == 1:  # a second signal must not cut the child's shutdown short
            raise KeyboardInterrupt

    previous = {}
    for signum in _SUPERVISOR_STOP_SIGNALS:
        if signal.getsignal(signum) is signal.SIG_DFL:
            previous[signum] = signal.signal(signum, interrupt)
    try:
        yield
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)


def watch(directory: str, interval: float = 0.4) -> Iterator[str]:
    """Yield the (relative) path of a changed ``*.py`` file, forever."""
    try:
        import watchfiles
    except ImportError:
        yield from _poll(Path(directory), interval)
        return
    try:
        for changes in watchfiles.watch(directory, watch_filter=watchfiles.PythonFilter()):
            yield _relative(sorted(path for _, path in changes)[0], directory)
    except OSError as exc:
        # Linux's inotify needs a watch for every folder, .venv and node_modules included, up to
        # fs.inotify.max_user_watches, and refuses folders this user cannot read (a container's volume).
        print(f"  !  cannot watch the files for changes: {exc}\n  !  polling for changes instead", flush=True)
        yield from _poll(Path(directory), interval)


def _poll(root: Path, interval: float) -> Iterator[str]:
    def snapshot() -> dict[Path, float]:
        times = {}
        for folder, folders, files in os.walk(root):  # unreadable folders are skipped
            folders[:] = [name for name in folders if name not in _IGNORED_DIRS]  # never walk into .venv
            for name in files:
                if os.path.normcase(name).endswith(".py"):
                    path = Path(folder, name)
                    with contextlib.suppress(OSError):  # deleted a moment ago
                        times[path] = path.stat().st_mtime
        return times

    before = snapshot()
    while True:
        time.sleep(interval)
        now = snapshot()
        if now != before:
            changed = sorted(p for p in now.keys() | before.keys() if now.get(p) != before.get(p))
            before = now
            yield _relative(str(changed[0]), str(root))


def _start(command: list[str], env: dict[str, str]) -> subprocess.Popen[bytes]:
    # On Windows, a process group of its own, so that it can be sent Ctrl+Break alone (see _stop). The
    # console's Ctrl+C then reaches only the supervisor, which stops it the same way.
    if sys.platform == "win32":
        return subprocess.Popen(command, env=env, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
    return subprocess.Popen(command, env=env)


def _stop(process: subprocess.Popen[bytes]) -> None:
    """Ask the app to stop, as Ctrl+C does, so that it shuts down its way; kill it if it takes too long.

    On Windows, ``terminate()`` ends a process at once, without its ``on_shutdown`` hooks: Ctrl+Break is
    the signal it handles.
    """
    if process.poll() is None:
        if sys.platform == "win32":
            process.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            process.terminate()  # SIGTERM
        try:
            process.wait(timeout=STOP_SECONDS)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def _relative(path: str, root: str) -> str:
    try:
        return str(Path(path).relative_to(root))
    except ValueError:
        return path


def _main_target(app: App) -> Target | None:
    """Where uvicorn can re-import ``app`` when it was defined in the script being run."""
    main = sys.modules.get("__main__")
    file = getattr(main, "__file__", None)
    if main is None or file is None:
        return None
    path = Path(file).resolve()
    if not path.stem.isidentifier():
        return None
    for name, value in vars(main).items():
        if value is app:
            return path.stem, name, str(path.parent)
    return None


def _api_note(app: App, host: str, port: int) -> list[str]:
    if not (app.services and app.api_docs):
        return []
    shown = "127.0.0.1" if host in ("0.0.0.0", "::") else host
    return [f"API docs (Swagger UI): http://{shown}:{port}{app.api_prefix}/docs"]


def _banner(mode: str, host: str, port: int, notes: list[str]) -> None:
    shown = "127.0.0.1" if host in ("0.0.0.0", "::") else host
    # ASCII only: many Windows consoles cannot encode arrows or emoji.
    lines = ["", f"  Rational Web - {mode}", f"  ->  http://{shown}:{port}"] + [f"  ->  {n}" for n in notes]
    print("\n".join(lines) + "\n", flush=True)
