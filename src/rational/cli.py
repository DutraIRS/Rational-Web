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

Page views live in process memory, so ``--workers`` > 1 needs sticky sessions.
"""

from __future__ import annotations

import argparse
import importlib
import importlib.util
import os
import subprocess
import sys
import time
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .dev import DEV_ENV

if TYPE_CHECKING:
    from .app import App

Target = tuple[str, str, str]  # (module, attribute, directory) to re-import the app in a child process

SUPERVISED_ENV = "RATIONAL_SUPERVISED"


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
    parser.add_argument("--workers", type=int, default=1, help="prod only; >1 requires sticky sessions")
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
    return parser


def export(app: App, directory: str, root_path: str = "") -> int:
    """Run a static export and print what was written and skipped. Returns the exit code."""
    import asyncio

    from .export import export_site

    os.environ.pop(DEV_ENV, None)
    report = asyncio.run(export_site(app, directory, base_path=root_path))
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
    import uvicorn

    args = build_parser().parse_args(sys.argv[1:] if argv is None else list(argv))
    if args.export:
        raise SystemExit(export(app, args.export, args.root_path))
    mode = resolve_mode(overrides.pop("mode", None) or args.mode)
    target = target or _main_target(app)
    port = overrides.pop("port", None) or args.port or int(os.environ.get("PORT", 8000))
    options: dict[str, Any] = {"port": port, "root_path": args.root_path, "log_level": args.log_level or "info"}

    if mode == "dev":
        os.environ[DEV_ENV] = "1"
        app.debug = True
        options["host"] = overrides.pop("host", None) or args.host or "127.0.0.1"
        reload = target is not None and not args.no_reload
        if not os.environ.get(SUPERVISED_ENV):
            _banner(
                "development",
                options["host"],
                port,
                [
                    "hot reload on" if reload else "hot reload off (run the app file as a script to enable it)",
                    "readable errors, live browser reload",
                    *_api_note(app, options["host"], port),
                    "not for production: use --prod",
                ],
            )
            if options["host"] not in ("127.0.0.1", "localhost", "::1"):
                print("  !  dev mode on a public interface exposes tracebacks and source code.\n")
        if reload and target is not None:
            supervise(target, args, options["host"], port)
        else:
            uvicorn.run(app, **options, **overrides)
        return

    os.environ.pop(DEV_ENV, None)
    app.debug = False
    options.update(
        host=overrides.pop("host", None) or args.host or os.environ.get("HOST", "0.0.0.0"),
        proxy_headers=True,
        forwarded_allow_ips=os.environ.get("FORWARDED_ALLOW_IPS", "127.0.0.1"),
        server_header=False,
    )
    notes = [f"pages at /, API at {app.api_prefix}, assets at /_rational", *_api_note(app, options["host"], port)]
    if args.workers > 1:
        notes.append(f"{args.workers} workers: page sessions are per process, so use sticky sessions")
    _banner("production", options["host"], port, notes)
    if args.workers > 1:
        if target is None:
            raise SystemExit("--workers > 1 needs an importable app: python -m rational module:app --prod")
        module, attr, directory = target
        uvicorn.run(f"{module}:{attr}", workers=args.workers, app_dir=directory, **options, **overrides)
    else:
        uvicorn.run(app, **options, **overrides)


def main(argv: Sequence[str] | None = None) -> None:
    """``python -m rational path/to/app.py|module:attr [--dev|--prod] [options]``"""
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0].startswith("-"):
        raise SystemExit("usage: python -m rational <app.py | module:attr> [--dev | --prod] [options]")
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
    """Run the app in a child process and restart it whenever a Python file changes."""
    module, attr, directory = target
    spec = f"{module}:{attr}" if attr else module
    command = [sys.executable, "-m", "rational", spec, "--app-dir", directory, "--dev", "--no-reload",
               "--host", host, "--port", str(port), "--root-path", args.root_path]  # fmt: skip
    if args.log_level:
        command += ["--log-level", args.log_level]
    env = {**os.environ, DEV_ENV: "1", SUPERVISED_ENV: "1"}
    child = subprocess.Popen(command, env=env)
    try:
        for changed in watch(directory):
            print(f"  ->  {changed} changed, restarting", flush=True)
            _stop(child)
            child = subprocess.Popen(command, env=env)
    except KeyboardInterrupt:
        pass
    finally:
        _stop(child)


def watch(directory: str, interval: float = 0.4) -> Iterator[str]:
    """Yield the (relative) path of a changed ``*.py`` file, forever."""
    try:
        import watchfiles
    except ImportError:
        yield from _poll(Path(directory), interval)
        return
    for changes in watchfiles.watch(directory, watch_filter=watchfiles.PythonFilter()):
        yield _relative(sorted(path for _, path in changes)[0], directory)


def _poll(root: Path, interval: float) -> Iterator[str]:
    def snapshot() -> dict[Path, float]:
        files = (p for p in root.rglob("*.py") if not _IGNORED_DIRS.intersection(p.relative_to(root).parts))
        return {p: p.stat().st_mtime for p in files}

    before = snapshot()
    while True:
        time.sleep(interval)
        now = snapshot()
        if now != before:
            changed = sorted(p for p in now.keys() | before.keys() if now.get(p) != before.get(p))
            before = now
            yield _relative(str(changed[0]), str(root))


def _stop(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
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
