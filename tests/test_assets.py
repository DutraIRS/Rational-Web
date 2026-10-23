import pytest

from rational import App, Asset, Page, Text, bootstrap, cx, tailwind
from rational.testing import TestClient


def page_app(**options):
    app = App(**options)

    @app.page("/")
    class Home(Page):
        def render(self):
            return Text("hi", class_=cx("btn", {"btn-primary": True, "off": False}, None))

    return app


def get(app):
    with TestClient(app) as client:
        return client.http.get("/", headers={"accept": "text/html"})


def test_bootstrap_adds_pinned_assets_with_integrity():
    res = get(page_app(adapter=bootstrap(js=True)))
    assert 'href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css"' in res.text
    assert 'integrity="sha384-QWTKZyjp' in res.text and 'crossorigin="anonymous"' in res.text
    assert "bootstrap.bundle.min.js" in res.text and "defer" in res.text
    assert 'class="btn btn-primary ' in res.text


def test_unknown_bootstrap_version_needs_integrity():
    with pytest.raises(ValueError, match="integrity"):
        bootstrap("5.9.9")
    assert bootstrap("5.9.9", integrity=("sha384-a", "sha384-b")).stylesheets[0].integrity == "sha384-a"


def test_local_assets_get_the_base_path_and_other_assets_pass_through():
    app = page_app(adapter=tailwind(css="/static/tw.css"), scripts=["/static/app.js"])
    res = get(app)
    assert '<link rel="stylesheet" href="/static/tw.css">' in res.text
    assert '<script src="/static/app.js" defer></script>' in res.text


def test_csp_allows_exactly_the_asset_origins():
    res = get(page_app(adapter=bootstrap(js=True), csp=True))
    csp = res.headers["content-security-policy"]
    assert "script-src 'self' https://cdn.jsdelivr.net;" in csp
    assert "https://cdn.jsdelivr.net;" in csp.split("style-src")[1]
    plain = get(page_app(csp=True)).headers["content-security-policy"]
    assert "script-src 'self';" in plain and "jsdelivr" not in plain
    assert 'nonce="' in res.text.split("bootstrap.bundle")[1][:200]  # the script tag carries the nonce


def test_validation():
    for bad in ("javascript:alert(1)", "http://insecure.example/x.css", "//evil.example/x.js", "relative.css"):
        with pytest.raises(ValueError):
            Asset(bad)
    with pytest.raises(ValueError):
        tailwind()
    with pytest.raises(ValueError):
        tailwind(css="/a.css", play_cdn=True)
    with pytest.raises(ValueError, match="csp"):
        App(adapter=tailwind(play_cdn=True), csp=True)
    assert 'src="https://cdn.tailwindcss.com"' in get(page_app(adapter=tailwind(play_cdn=True))).text


def test_cx():
    assert cx("a", None, False, ["b", {"c": 1, "d": 0}], {"e": True}) == "a b c e"
    assert cx() == ""
