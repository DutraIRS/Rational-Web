import asyncio

import pytest

from rational import App, Button, Column, Component, Heading, Page, State, Text, h
from rational.cli import main
from rational.export import export_site
from rational.testing import TestClient


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


DOCS = {"faq": "Questions", "install": "Installing"}


def docs_site():
    """A translated documentation site that brings its own stylesheet and keeps its URLs."""
    app = App(title="Docs", theme=None, stylesheets=["/assets/site.css"], favicon=False)

    @app.page(
        "/{language}/docs/{slug}.html",
        paths=[{"language": lang, "slug": slug} for lang in ("en", "ar") for slug in DOCS],
    )
    class Doc(Page):
        language: str
        slug: str
        head_start = """<meta http-equiv="Content-Security-Policy" content="style-src 'self'">"""

        def mount(self):
            self.title = DOCS[self.slug]
            self.lang = self.language
            self.dir = "rtl" if self.language == "ar" else None
            self.head_end = '<link rel="icon" href="../../assets/icon.png">'

        def render(self):
            return h("main", h("h1", DOCS[self.slug]))  # plain markup: no built-in component styles

    @app.page("/404.html")
    class Missing(Page):
        def render(self):
            return h("p", "Lost?")

    return app


def test_a_site_with_its_own_stylesheet_keeps_its_urls_and_document_settings(tmp_path):
    report = asyncio.run(export_site(docs_site(), tmp_path, relative=True))
    assert sorted(report.pages) == [
        "/404.html",
        "/ar/docs/faq.html",
        "/ar/docs/install.html",
        "/en/docs/faq.html",
        "/en/docs/install.html",
    ]

    html = (tmp_path / "ar" / "docs" / "faq.html").read_text("utf-8")
    assert '<html lang="ar" dir="rtl">' in html and "<title>Questions</title>" in html
    head = '<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8">'
    assert html.startswith(head + '<meta http-equiv="Content-Security-Policy"')  # before anything it governs
    assert '<link rel="stylesheet" href="../../assets/site.css">' in html  # relative: works from disk too
    assert html.index("site.css") < html.index("icon.png")  # the page's own head markup comes last
    assert html.count('rel="icon"') == 1  # favicon=False: only the page's own icon
    for rational_only in ("theme.css", "rw-styles", "data-rw-c", "data-theme", "<style"):
        assert rational_only not in html
    assert '<html lang="en">' in (tmp_path / "en" / "docs" / "faq.html").read_text("utf-8")
    assert not (tmp_path / "_rational").exists()
    assert "Lost?" in (tmp_path / "404.html").read_text("utf-8")  # the site's own 404 page is kept


def test_relative_links_follow_each_page_and_the_404_page_is_optional(tmp_path):
    app = App(title="Site")

    @app.page("/")
    class Home(Page):
        def render(self):
            return Text("Home")

    @app.page("/guide/start.html")
    class Start(Page):
        def render(self):
            return Text("Start")

    asyncio.run(export_site(app, tmp_path, relative=True, not_found=False))
    assert 'href="./_rational/theme.css' in (tmp_path / "index.html").read_text("utf-8")
    assert 'href="../_rational/theme.css' in (tmp_path / "guide" / "start.html").read_text("utf-8")
    assert not (tmp_path / "404.html").exists()


def test_path_parameters_need_their_values_listed(tmp_path):
    app = App()

    @app.page("/tags/{tag}.html", paths=lambda: [{"tag": "news"}])
    class Tag(Page):
        tag: str

        def render(self):
            return Text(self.tag)

    @app.page("/wrong/{slug}.html", paths=[{"name": "x"}])
    class Wrong(Page):
        slug: str

        def render(self):
            return Text(self.slug)

    with pytest.raises(ValueError, match=r"exactly \['slug'\]"):
        asyncio.run(export_site(app, tmp_path))
    del app.routes["/wrong/{slug}.html"]
    assert asyncio.run(export_site(app, tmp_path)).pages == ["/tags/news.html"]


def test_document_settings_are_not_props_and_dir_is_checked():
    assert "title" not in Page._rw_props and "lang" not in Page._rw_props

    class Plain(Page):
        title = "Fixed"
        dir = "sideways"  # type: ignore[assignment]

        def render(self):
            return Text("x")

    assert "title" not in Plain._rw_props and "dir" not in Plain._rw_props
    app = App()
    app.page("/")(Plain)
    with pytest.raises(ValueError, match="dir must be"):
        TestClient(app).http.get("/")
