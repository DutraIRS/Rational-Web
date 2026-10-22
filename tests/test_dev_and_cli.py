"""Development mode (readable errors, live reload) and the command line."""

import sys
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
