"""API-only apps: services, bearer-token auth and CORS, with no pages or sessions required."""

import pytest

from rational import App, Context, Page, Text
from rational.backend import Service, remote
from rational.testing import TestClient


def make_app(**options):
    app = App(api_only=True, **options)

    @app.authenticate
    def bearer(ctx: Context):
        header = ctx.request.headers.get("authorization", "") if ctx.request else ""
        return {"id": "ada"} if header == "Bearer secret" else None

    @app.service
    class Notes(Service):
        @remote(method="GET")
        def count(self) -> int:
            return 3

        @remote(auth="required")
        def whoami(self) -> str:
            return self.context.require_user()["id"]

    return app


def test_api_only_serves_services_without_cookies_or_csrf():
    client = TestClient(make_app()).http

    response = client.post("/api/notes/whoami", json={}, headers={"Authorization": "Bearer secret"})

    assert response.status_code == 200 and response.json() == "ada"
    assert "set-cookie" not in response.headers
    assert client.post("/api/notes/whoami", json={}).status_code == 401


def test_api_only_has_no_page_machinery():
    client = TestClient(make_app()).http

    assert client.get("/api/notes/count").json() == 3
    for path in ("/_rational/runtime.js", "/_rational/theme.css", "/_rational/stream"):
        assert client.get(path).status_code == 404
    assert client.post("/_rational/event", json={}).status_code == 404


def test_api_only_rejects_pages():
    app = App(api_only=True)

    class Home(Page):
        def render(self):
            return Text("hi")

    with pytest.raises(TypeError, match="api_only"):
        app.page("/")(Home)


def test_cors_applies_to_the_api_only():
    app = make_app(cors_origins=["https://site.example"])
    client = TestClient(app).http
    origin = {"Origin": "https://site.example"}

    simple = client.get("/api/notes/count", headers=origin)
    assert simple.headers["access-control-allow-origin"] == "https://site.example"
    assert "access-control-allow-credentials" not in simple.headers

    preflight = client.options(
        "/api/notes/whoami",
        headers={**origin, "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "authorization"},
    )
    assert preflight.status_code == 200
    assert "authorization" in preflight.headers["access-control-allow-headers"].lower()

    other = client.get("/api/notes/count", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in other.headers
    assert "access-control-allow-origin" not in client.get("/nope", headers=origin).headers


def test_cors_is_off_by_default_and_validates_wildcards():
    client = TestClient(make_app()).http
    response = client.get("/api/notes/count", headers={"Origin": "https://site.example"})
    assert "access-control-allow-origin" not in response.headers
    with pytest.raises(ValueError):
        App(cors_origins=["*", "https://a.example"])
