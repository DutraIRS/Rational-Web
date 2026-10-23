from rational import App, Button, Component, Page, State, Text
from rational.export import export_site
from rational.testing import TestClient


def make_app(**options):
    app = App(**options)

    @app.page("/")
    class Home(Page):
        def render(self):
            return Text("home")

    class Counter(Component):
        n = State(0)

        def bump(self):
            self.n += 1

        def render(self):
            return Button(f"Count {self.n}", on_click=self.bump)

    @app.page("/live")
    class Live(Page):
        def render(self):
            return Counter()

    return app


def manifest_of(app, path):
    return TestClient(app).open(path).dom.find_all("script", id="rw-manifest")


def test_client_nav_is_off_by_default():
    app = make_app()
    assert manifest_of(app, "/") == []
    html = TestClient(app).http.get("/live", headers={"accept": "text/html"}).text
    assert '"nav":false' in html


def test_client_nav_loads_the_runtime_on_static_pages_without_events():
    app = make_app(client_nav=True)
    response = TestClient(app).http.get("/", headers={"accept": "text/html"})
    assert "/_rational/runtime.js" in response.text
    assert '"nav":true' in response.text
    assert '"page"' not in response.text.split('id="rw-manifest">')[1].split("</script>")[0]
    assert TestClient(app).open("/").manifest is None


def test_client_nav_flags_interactive_pages():
    app = make_app(client_nav=True)
    page = TestClient(app).open("/live")
    assert page.manifest["nav"] is True
    page.click("Count 0")
    assert "Count 1" in page.text


async def test_export_ignores_client_nav(tmp_path):
    app = make_app(client_nav=True)
    report = await export_site(app, tmp_path)
    assert "/" in report.pages
    assert "runtime.js" not in (tmp_path / "index.html").read_text()
    assert app.client_nav is True
