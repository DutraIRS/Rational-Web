"""Development mode (readable errors, live reload) and the command line."""

import contextlib
import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time
import types
from pathlib import Path

import anyio
import pytest

from rational import App, Button, Page, Style, Text, cli
from rational.dev import broken_app as make_broken_app
from rational.dev import describe
from rational.testing import TestClient

EXAMPLES = Path(__file__).parent.parent / "examples"

sys.path.insert(0, str(Path(__file__).parent / "examples"))

from conftest import forget_project_modules  # noqa: E402


def broken_app(debug):
    app = App(debug=debug)

    @app.page("/")
    class Broken(Page):
        def render(self):
            return Text("x", style=Style(color="red;}"))

    @app.page("/event")
    class EventBroken(Page):
        def explode(self):
            {}["missing"]

        def render(self):
            return Button("explode", on_click=self.explode)

    return app


def test_dev_error_page_points_at_user_code():
    response = TestClient(broken_app(debug=True)).http.get("/")
    assert response.status_code == 500
    body = response.text
    assert "StyleError" in body and "test_dev_and_cli.py" in body
    assert "in <b>render()</b>" in body and "💡" in body and "while rendering Broken at page" in body
    assert "/_rational/dev.js" in body  # reloads itself once the code is fixed


def test_production_hides_errors():
    client = TestClient(broken_app(debug=False))
    client.http.__init__(client.app, raise_server_exceptions=False)
    response = client.http.get("/")
    assert response.status_code == 500 and "StyleError" not in response.text


def test_event_errors_carry_debug_info_only_in_dev():
    dev = TestClient(broken_app(debug=True)).open("/event")
    data = dev.fire(dev.find("explode", "click").get("data-rw-on-click"), {}, check=False)
    assert data["error"]["debug"]["type"] == "KeyError"
    assert data["error"]["debug"]["function"] == "explode"
    prod = TestClient(broken_app(debug=False)).open("/event")
    data = prod.fire(prod.find("explode", "click").get("data-rw-on-click"), {}, check=False)
    assert "debug" not in data["error"] and data["error"]["message"] == "Something went wrong"


def test_dev_routes_exist_only_in_debug():
    dev, prod = TestClient(App(debug=True)), TestClient(App(debug=False))
    assert dev.http.get("/_rational/dev/boot").text == dev.app.boot_id
    assert "location.reload" in dev.http.get("/_rational/dev.js").text
    assert prod.http.get("/_rational/dev/boot").status_code == 404
    assert prod.http.get("/_rational/dev.js").status_code == 404


def test_debug_defaults_from_environment(monkeypatch):
    monkeypatch.setenv("RATIONAL_DEV", "1")
    assert App().debug is True
    monkeypatch.delenv("RATIONAL_DEV")
    assert App().debug is False


def test_mode_resolution(monkeypatch):
    monkeypatch.delenv("RATIONAL_ENV", raising=False)
    assert cli.resolve_mode(None) == "dev"
    monkeypatch.setenv("RATIONAL_ENV", "production")
    assert cli.resolve_mode(None) == "prod"
    assert cli.resolve_mode("dev") == "dev"


@pytest.fixture
def uvicorn_calls(monkeypatch):
    import uvicorn

    calls = []
    monkeypatch.setattr(uvicorn, "run", lambda target, **kw: calls.append((target, kw)))
    monkeypatch.delenv("PORT", raising=False)
    monkeypatch.delenv("HOST", raising=False)
    monkeypatch.delenv("RATIONAL_ENV", raising=False)
    yield calls
    monkeypatch.delenv("RATIONAL_DEV", raising=False)


def test_dev_mode_supervises_an_importable_app(uvicorn_calls, monkeypatch, capsys):
    supervised = []
    monkeypatch.setattr(cli, "supervise", lambda target, args, host, port: supervised.append((target, host, port)))
    app, target = cli.load_target(str(EXAMPLES / "hello" / "app.py"))
    cli.serve(app, ["--dev", "--port", "8123"], target=target)
    assert supervised == [(target, "127.0.0.1", 8123)] and uvicorn_calls == []
    assert app.debug is True and "hot reload on" in capsys.readouterr().out


def test_dev_mode_without_reload_serves_directly(uvicorn_calls):
    app = App()
    cli.serve(app, ["--dev", "--no-reload"])
    ((where, options),) = uvicorn_calls
    assert where is app and options["host"] == "127.0.0.1"


def test_poll_watcher_reports_changed_python_files(tmp_path):
    import threading

    (tmp_path / "app.py").write_text("x = 1")
    (tmp_path / ".venv").mkdir()
    changes = cli._poll(tmp_path, 0.05)

    def edit():
        (tmp_path / ".venv" / "ignored.py").write_text("y = 1")
        (tmp_path / "app.py").write_text("x = 2  # changed")

    threading.Timer(0.2, edit).start()
    assert next(changes) == "app.py"


def test_prod_mode_is_proxy_aware_and_honours_port(uvicorn_calls, monkeypatch):
    monkeypatch.setenv("PORT", "9123")
    app = App()
    app.debug = True
    cli.serve(app, ["--prod", "--root-path", "/shop"])
    ((where, options),) = uvicorn_calls
    assert where is app and options["host"] == "0.0.0.0" and options["port"] == 9123
    assert options["proxy_headers"] is True and options["root_path"] == "/shop" and app.debug is False


def test_prod_workers_need_an_import_string(uvicorn_calls):
    with pytest.raises(SystemExit, match="importable"):
        cli.serve(App(), ["--prod", "--workers", "2"])


def test_module_entry_point_requires_a_target():
    with pytest.raises(SystemExit, match="usage"):
        cli.main([])


def test_broken_app_serves_error_page_and_dev_assets():
    import httpx

    exc = ImportError("cannot import name 'thing' from 'app'")
    transport = httpx.ASGITransport(app=make_broken_app(exc, "while importing the app"))

    async def run():
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
            return (
                await http.get("/"),
                await http.get("/_rational/dev.js"),
                await http.get("/_rational/dev/boot"),
            )

    page, script, boot = anyio.run(run)
    assert page.status_code == 500
    assert "ImportError" in page.text and "while importing the app" in page.text
    assert "location.reload" in script.text
    assert boot.status_code == 200


def test_startup_hook_failure_shows_error_page_in_dev():
    def boom():
        raise RuntimeError("database is on fire")

    app = App(debug=True)
    app.on_startup(boom)
    with TestClient(app) as client:
        response = client.http.get("/")
        assert response.status_code == 500
        assert "RuntimeError" in response.text and "while starting the app" in response.text
        # The dev assets stay up, so the browser reloads once the fix is saved.
        assert client.http.get("/_rational/dev/boot").status_code == 200


def test_startup_hook_failure_raises_in_production():
    def boom():
        raise RuntimeError("database is on fire")

    app = App(debug=False)
    app.on_startup(boom)
    client = TestClient(app)
    client.http.__init__(client.app, raise_server_exceptions=False)
    with pytest.raises(RuntimeError, match="database is on fire"), client:
        client.http.get("/")


def test_describe_points_at_the_broken_syntax_file(tmp_path):
    import linecache

    file = tmp_path / "broken_module.py"
    file.write_text("def f():\n    return (1,\n")
    linecache.clearcache()
    try:
        compile(file.read_text(), str(file), "exec")
    except SyntaxError as exc:
        info = describe(exc)
    else:  # pragma: no cover
        raise AssertionError("expected a SyntaxError")
    assert info["file"] is not None and info["file"].endswith("broken_module.py")
    assert info["line"] == 2


def test_a_project_inside_the_python_installation_is_still_user_code():
    import asyncio

    from rational import dev

    # A Linux distribution's Python lives in /usr, and so may a project (/usr/src/app): only the
    # standard library and installed packages are left out of "your code".
    assert dev._is_user_frame(os.path.join(sys.base_prefix, "src", "app", "app.py"))
    assert not dev._is_user_frame(asyncio.__file__)
    assert not dev._is_user_frame(pytest.__file__)
    assert not dev._is_user_frame("/usr/lib/python3/dist-packages/starlette/routing.py")  # Debian's packages


def test_cli_serves_broken_app_in_supervised_dev_mode(monkeypatch, capsys, tmp_path):
    import uvicorn

    monkeypatch.delitem(sys.modules, "app", raising=False)
    calls = []
    monkeypatch.setattr(uvicorn, "run", lambda target, **kw: calls.append((target, kw)))
    monkeypatch.setenv(cli.SUPERVISED_ENV, "1")
    monkeypatch.delenv("RATIONAL_ENV", raising=False)
    monkeypatch.delitem(sys.modules, "app", raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "app.py").write_text("from rational import App\napp = App()\nraise RuntimeError('boom at import')\n")
    cli.main(["app.py", "--dev"])
    ((target, options),) = calls
    assert callable(target)
    assert options["host"] == "127.0.0.1"
    assert "RuntimeError: boom at import" in capsys.readouterr().err


def test_load_target_by_module_string(monkeypatch):
    forget_project_modules(EXAMPLES / "counter")
    monkeypatch.syspath_prepend(str(EXAMPLES / "counter"))
    monkeypatch.chdir(EXAMPLES / "counter")
    sys.modules.pop("app", None)
    app, target = cli.load_target("app:app")
    assert isinstance(app, App) and target[:2] == ("app", "app")
    forget_project_modules(EXAMPLES / "counter")
    sys.modules.pop("app", None)


def test_every_public_name_of_the_package_exists():
    import rational

    assert sorted(rational.__all__) == list(rational.__all__)
    for name in rational.__all__:
        assert getattr(rational, name) is not None


def test_a_file_deleted_while_watching_counts_as_a_change(tmp_path):
    from rational.cli import _poll

    keep, gone = tmp_path / "keep.py", tmp_path / "gone.py"
    keep.write_text("x = 1")
    gone.write_text("x = 2")
    watcher = _poll(tmp_path, 0.001)
    deleter = threading.Timer(0.02, gone.unlink)
    deleter.start()
    assert next(watcher) == "gone.py"
    deleter.join()


def test_watching_falls_back_to_polling_when_the_os_refuses(tmp_path, monkeypatch, capsys):
    def refuse(*paths, **options):  # inotify on Linux: too many folders, or one this user cannot read
        raise OSError("OS file watch limit reached.")
        yield

    monkeypatch.setitem(sys.modules, "watchfiles", types.SimpleNamespace(watch=refuse, PythonFilter=lambda: None))
    (tmp_path / "app.py").write_text("x = 1")
    changes = cli.watch(str(tmp_path), interval=0.05)
    threading.Timer(0.3, lambda: (tmp_path / "app.py").write_text("x = 2  # changed")).start()
    assert next(changes) == "app.py"
    assert "polling for changes instead" in capsys.readouterr().out


@pytest.mark.skipif(sys.platform == "win32" or os.geteuid() == 0, reason="POSIX permissions; root reads everything")
def test_the_poller_skips_folders_it_cannot_read(tmp_path):
    locked = tmp_path / "pgdata"  # a container's data volume, say
    locked.mkdir()
    (tmp_path / "app.py").write_text("x = 1")
    locked.chmod(0)
    try:
        changes = cli._poll(tmp_path, 0.05)
        threading.Timer(0.2, lambda: (tmp_path / "app.py").write_text("x = 2  # changed")).start()
        assert next(changes) == "app.py"
    finally:
        locked.chmod(0o700)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX signals")
def test_the_supervisor_takes_sigterm_and_sighup_like_ctrl_c_but_leaves_nohup_alone():
    previous = {signum: signal.getsignal(signum) for signum in (signal.SIGTERM, signal.SIGHUP)}
    try:
        signal.signal(signal.SIGTERM, signal.SIG_DFL)
        signal.signal(signal.SIGHUP, signal.SIG_DFL)
        received = []
        with pytest.raises(KeyboardInterrupt), cli._interrupt_on_termination(received):
            handlers = {signal.getsignal(signal.SIGTERM), signal.getsignal(signal.SIGHUP)}
            assert signal.SIG_DFL not in handlers and signal.SIG_IGN not in handlers  # or raising ends pytest
            try:
                signal.raise_signal(signal.SIGHUP)
            finally:
                signal.raise_signal(signal.SIGTERM)  # while the child stops: noted, not a second interrupt
        assert received == [signal.SIGHUP, signal.SIGTERM]
        assert signal.getsignal(signal.SIGTERM) is signal.SIG_DFL

        signal.signal(signal.SIGHUP, signal.SIG_IGN)  # what nohup does
        with cli._interrupt_on_termination([]):
            assert signal.getsignal(signal.SIGHUP) is signal.SIG_IGN
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX signals")
def test_sigterm_to_the_dev_supervisor_stops_the_app_it_runs(tmp_path):
    (tmp_path / "app.py").write_text(
        "from rational import App\n\napp = App()\n\nif __name__ == '__main__':\n    app.run()\n"
    )
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    env = {name: value for name, value in os.environ.items() if not name.startswith("RATIONAL_") and name != "PORT"}
    supervisor = subprocess.Popen(
        [sys.executable, "app.py", "--dev", "--port", str(port)],
        cwd=tmp_path,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )

    def serving():
        with socket.socket() as s:
            return s.connect_ex(("127.0.0.1", port)) == 0

    try:
        deadline = time.monotonic() + 30
        while not serving():
            assert supervisor.poll() is None and time.monotonic() < deadline, "the dev server did not start"
            time.sleep(0.05)
        supervisor.send_signal(signal.SIGTERM)  # to the supervisor alone, as kill, systemd or docker stop do
        assert supervisor.wait(timeout=20) == -signal.SIGTERM
        assert not serving()  # the app stopped with it, instead of serving on with nobody to restart it
    finally:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(supervisor.pid, signal.SIGKILL)  # whatever is left of its process group


@pytest.mark.skipif(sys.platform != "win32", reason="Windows console signals")
def test_the_windows_dev_supervisor_lets_the_app_shut_down_its_way(tmp_path):
    # terminate() is TerminateProcess on Windows: the app died without its on_shutdown hooks, on every hot
    # reload and on Ctrl+C. A Ctrl+Break to the supervisor alone also left the app serving.
    source = (
        "import pathlib\n"
        "from rational import App\n\n"
        "app = App()\n\n\n"
        "@app.on_shutdown\n"
        "def bye():\n"
        "    with open('stopped.txt', 'a') as f:\n"
        "        f.write('x')\n\n\n"
        "if __name__ == '__main__':\n"
        "    app.run()\n"
    )
    (tmp_path / "app.py").write_text(source)
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    env = {name: value for name, value in os.environ.items() if not name.startswith("RATIONAL_") and name != "PORT"}
    supervisor = subprocess.Popen(
        [sys.executable, "app.py", "--dev", "--port", str(port)],
        cwd=tmp_path,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
    )
    stopped = tmp_path / "stopped.txt"

    def serving():
        with socket.socket() as s:
            return s.connect_ex(("127.0.0.1", port)) == 0

    def wait_for(condition, what):
        deadline = time.monotonic() + 30
        while not condition():
            assert supervisor.poll() is None and time.monotonic() < deadline, what
            time.sleep(0.05)

    try:
        wait_for(serving, "the dev server did not start")
        (tmp_path / "app.py").write_text(source + "# changed\n")
        wait_for(stopped.exists, "the reload did not run on_shutdown")
        wait_for(serving, "the dev server did not come back")
        supervisor.send_signal(signal.CTRL_BREAK_EVENT)  # to the supervisor alone: the app has its own group
        supervisor.wait(timeout=30)
        assert stopped.read_text() == "xx"  # on the reload, and on the stop
        assert not serving()
    finally:
        if supervisor.poll() is None:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(supervisor.pid)], capture_output=True)


def test_live_reload_checks_stay_out_of_the_request_log():
    import logging

    from rational.dev import BOOT_PATH, hide_reload_checks

    def logged(path):
        record = logging.LogRecord("uvicorn.access", logging.INFO, "", 0, '%s - "%s %s HTTP/%s" %d',
                                   ("127.0.0.1:1", "GET", path, "1.1", 200), None)  # fmt: skip
        return logging.getLogger("uvicorn.access").filter(record)

    hide_reload_checks()
    hide_reload_checks()  # once is enough, twice is harmless
    assert not logged(BOOT_PATH) and not logged("/prefix" + BOOT_PATH + "?t=1")
    assert logged("/") and logged("/_rational/stream?page=x")
    record = logging.LogRecord("uvicorn.access", logging.INFO, "", 0, "no arguments", None, None)
    assert logging.getLogger("uvicorn.access").filter(record)


def test_the_stop_signal_reaches_the_app_and_then_the_server():
    from rational.concurrency import on_stop_signal

    heard, previous = [], signal.getsignal(signal.SIGTERM)
    signal.signal(signal.SIGTERM, lambda signum, frame: heard.append("server"))  # the server's own handler
    try:
        undo = on_stop_signal(lambda: heard.append("app"))
        signal.raise_signal(signal.SIGTERM)
        assert heard == ["app", "server"]  # the app first, and the server still shuts down its way
        undo()
        signal.raise_signal(signal.SIGTERM)
        assert heard == ["app", "server", "server"]
    finally:
        signal.signal(signal.SIGTERM, previous)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX signals")
def test_an_open_push_stream_does_not_hold_up_stopping(tmp_path):
    # A live page's stream never ends by itself: stopping used to wait the whole graceful timeout (30 s), and
    # longer than a docker stop or a systemd stop allows, so on_shutdown hooks never ran.
    import httpx

    (tmp_path / "app.py").write_text(
        "import asyncio\n"
        "from rational import App, Page, State, Text\n\n"
        "app = App()\n\n\n"
        "@app.on_shutdown\n"
        "def bye():\n"
        "    open('stopped.txt', 'w').close()\n\n\n"
        "@app.page('/')\n"
        "class Clock(Page):\n"
        "    ticks = State(0)\n\n"
        "    async def mount(self):\n"
        "        self.run_task(self.tick)\n\n"
        "    async def tick(self):\n"
        "        while True:\n"
        "            await asyncio.sleep(0.2)\n"
        "            self.ticks += 1\n\n"
        "    def render(self):\n"
        "        return Text(f'ticks {self.ticks}')\n\n\n"
        "if __name__ == '__main__':\n"
        "    app.run()\n"
    )
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    env = {name: value for name, value in os.environ.items() if not name.startswith("RATIONAL_") and name != "PORT"}
    env["RATIONAL_SECRET_KEY"] = "k" * 43
    server = subprocess.Popen(
        [sys.executable, "app.py", "--prod", "--host", "127.0.0.1", "--port", str(port)],
        cwd=tmp_path,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        base = f"http://127.0.0.1:{port}"
        with httpx.Client(base_url=base, timeout=10) as client:
            for _ in range(300):
                try:
                    page = client.get("/", headers={"accept": "text/html"})
                    break
                except httpx.TransportError:
                    time.sleep(0.05)
            manifest = json.loads(page.text.split('id="rw-manifest">')[1].split("</script>")[0])
            with client.stream("GET", f"{manifest['stream']}?page={manifest['page']}") as stream:
                lines = stream.iter_lines()
                assert next(lines).startswith("data:")  # the stream is open
                started = time.monotonic()
                server.send_signal(signal.SIGTERM)
                assert server.wait(timeout=10) in (0, -signal.SIGTERM)  # newer uvicorn re-raises it when done
                assert time.monotonic() - started < 5
        assert (tmp_path / "stopped.txt").exists()  # and on_shutdown ran
    finally:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(server.pid, signal.SIGKILL)


def test_the_servers_do_not_wait_for_ever_on_open_streams(monkeypatch):
    seen = {}
    monkeypatch.setattr("uvicorn.run", lambda app, **options: seen.update(options))
    cli.serve(App(), ["--prod"])
    assert seen["timeout_graceful_shutdown"] == 30
    cli.serve(App(), ["--dev", "--no-reload"])
    assert seen["timeout_graceful_shutdown"] == 1
    cli.serve(App(), ["--prod"], timeout_graceful_shutdown=5)
    assert seen["timeout_graceful_shutdown"] == 5


def test_an_import_error_in_the_app_is_not_blamed_on_alembic(tmp_path, monkeypatch):
    (tmp_path / "brokenapp.py").write_text("import no_such_module_at_all\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.syspath_prepend(str(tmp_path))
    with pytest.raises(ImportError, match="no_such_module_at_all"):
        cli.main(["db", "upgrade", "brokenapp.py"])
