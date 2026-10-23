import asyncio

import pytest

from rational import App, Button, Column, Component, Heading, Page, State, Text
from rational.cli import main
from rational.export import export_site


class Counter(Component):
    count = State(0)

    def bump(self):
        self.count += 1

    def render(self):
        return Button("Bump", on_click=self.bump)


def make_app(static_dir=None):
    app = App(title="Site")

    @app.page("/")
    class Home(Page):
        def render(self):
            return Column(Heading("Hello"), Text("static"))

    @app.page("/about")
    class About(Page):
        def render(self):
            return Text("About us")

    @app.page("/live")
    class Live(Page):
        def render(self):
            return Counter()

    @app.page("/users/{name}")
    class User(Page):
        name: str

        def render(self):
            return Text(self.name)

    @app.page("/private", auth="required")
    class Private(Page):
        def render(self):
            return Text("secret")

    if static_dir is not None:
        app.static("/static", str(static_dir))
    return app


def test_exports_static_pages_and_assets(tmp_path):
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "logo.txt").write_text("logo")
    out = tmp_path / "site"

    report = asyncio.run(export_site(make_app(assets), out))

    assert report.pages == ["/", "/about"]
    assert {path for path, _ in report.skipped} == {"/live", "/users/{name}", "/private"}
    assert "Hello" in (out / "index.html").read_text("utf-8")
    assert "About us" in (out / "about" / "index.html").read_text("utf-8")
    assert (out / "_rational" / "theme.css").read_text("utf-8").strip()
    assert (out / "static" / "logo.txt").read_text() == "logo"
    assert (out / "404.html").exists()
    assert not (out / "live").exists()
    assert "/_rational/runtime.js" not in (out / "index.html").read_text("utf-8")


def test_base_path_prefixes_asset_links(tmp_path):
    asyncio.run(export_site(make_app(), tmp_path, base_path="/my-repo/"))

    assert 'href="/my-repo/_rational/theme.css' in (tmp_path / "index.html").read_text("utf-8")


def test_export_does_not_leave_app_in_debug_mode(tmp_path):
    app = make_app()
    app.debug = True

    asyncio.run(export_site(app, tmp_path))

    assert app.debug is True


def test_cli_export_flag(tmp_path, capsys):
    module = tmp_path / "exportapp.py"
    module.write_text(
        "from rational import App, Page, Text\n"
        "app = App()\n"
        "@app.page('/')\n"
        "class Home(Page):\n"
        "    def render(self):\n"
        "        return Text('exported')\n"
    )
    out = tmp_path / "out"

    with pytest.raises(SystemExit) as exit_info:
        main([str(module), "--export", str(out)])

    assert exit_info.value.code == 0
    assert "exported" in (out / "index.html").read_text("utf-8")
    assert "exported  /" in capsys.readouterr().out
