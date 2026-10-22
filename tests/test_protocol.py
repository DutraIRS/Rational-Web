"""Security and robustness of the HTTP event protocol and page routing."""

import asyncio

import httpx
import pytest

from rational import App, Button, Column, Component, FieldError, NotFound, Page, State, Text, redirect
from rational.testing import TestClient


class Counter(Component):
    count = State(0)

    def increment(self):
        self.count += 1

    def boom(self):
        raise RuntimeError("secret internals")

    def render(self):
        return Column(
            Text(f"Count: {self.count}"),
            Button("Increment", on_click=self.increment),
            Button("Boom", on_click=self.boom),
        )


@pytest.fixture
def app():
    app = App(event_burst=5, event_rate=0.001)

    @app.page("/")
    class Home(Page):
        def render(self):
            return Counter()

    @app.page("/users/{user_id}")
    class User(Page):
        user_id: int

        def mount(self):
            if self.user_id == 404:
                raise NotFound("No such user")
            if self.user_id == 0:
                raise redirect("/")

        def render(self):
            return Text(f"user #{self.user_id}")

    @app.page("/private", auth="required")
    class Private(Page):
        def render(self):
            return Text("secret")

    return app


def post_event(client, view, handler="c1.1", **overrides):
    body = {
        "v": 1,
        "page": view.manifest["page"],
        "rev": view.manifest["rev"],
        "handler": handler,
        "payload": {},
    }
    headers = {"X-RW-CSRF": view.manifest["csrf"]}
    headers.update(overrides.pop("headers", {}))
    body.update(overrides)
    response = client.http.post("/_rational/event", json=body, headers=headers)
    data = response.json()
    if "rev" in data:
        view.manifest["rev"] = data["rev"]
    if "csrf" in data:
        view.manifest["csrf"] = data["csrf"]
    return response


def test_event_requires_csrf_token(app):
    client = TestClient(app)
    page = client.open("/")
    response = post_event(client, page, headers={"X-RW-CSRF": "wrong"})
    assert response.status_code == 403 and response.json()["error"]["code"] == "csrf"


def test_event_requires_the_owning_session(app):
    owner = TestClient(app)
    page = owner.open("/")
    attacker = TestClient(app)
    attacker.open("/")  # has its own valid session
    response = post_event(attacker, page)
    assert response.status_code == 403
    assert "Count: 0" in owner.open("/").text


@pytest.mark.parametrize("failure", ["rational", "unexpected"])
def test_remote_errors_finalize_session_rotation(failure):
    from rational.backend import Service, remote

    app = App()

    @app.service
    class AccountService(Service):
        @remote()
        def login_then_fail(self, failure: str) -> None:
            self.context.session.login("alice")
            if failure == "rational":
                raise FieldError("email", "Already registered")
            raise RuntimeError("operation failed")

    client = TestClient(app)
    session = app.sessions.create()
    old_id = session.id

    response = client.http.post(
        "/api/account/login-then-fail",
        json={"failure": failure},
        headers={"X-RW-CSRF": session.csrf, "Cookie": f"rw_sid={old_id}"},
    )

    assert response.status_code == (422 if failure == "rational" else 500)
    new_id = response.headers["set-cookie"].split(";", 1)[0].split("=", 1)[1]
    assert new_id and new_id != old_id
    assert app.sessions.get(old_id) is None
    assert app.sessions.get(new_id).user == "alice"


def test_failed_page_render_finalizes_rotated_session():
    app = App()

    @app.page("/")
    class Broken(Page):
        def render(self):
            self.context.session.login("alice")
            raise RuntimeError("render failed")

    client = TestClient(app)
    client.http.__init__(client.app, raise_server_exceptions=False)

    response = client.http.get("/")

    assert response.status_code == 500
    new_id = response.headers["set-cookie"].split(";", 1)[0].split("=", 1)[1]
    session = app.sessions.get(new_id)
    assert session is not None and session.user == "alice"


def test_unknown_page_session_is_gone(app):
    client = TestClient(app)
    page = client.open("/")
    response = post_event(client, page, page="nope")
    assert response.status_code == 410


def test_event_revision_prevents_duplicate_mutations(app):
    client = TestClient(app)
    page = client.open("/")
    original_revision = page.manifest["rev"]
    page.click("Increment")
    request = {"v": 1, "page": page.manifest["page"], "rev": original_revision, "handler": "c1.1", "payload": {}}
    headers = {"X-RW-CSRF": page.manifest["csrf"]}

    replay = client.http.post("/_rational/event", json=request, headers=headers)

    assert replay.status_code == 409
    assert replay.json()["error"]["code"] == "stale_revision"
    assert replay.json()["actions"] == [{"op": "reload"}]
    assert "Count: 1" in page.text


@pytest.mark.asyncio
async def test_session_state_mutations_are_serialized_across_page_views():
    app = App()

    class SharedCounter(Component):
        count = State(0, scope="session")

        async def increment(self):
            current = self.count
            await asyncio.sleep(0.02)
            self.count = current + 1

        def render(self):
            return Button(f"Count: {self.count}", on_click=self.increment)

    @app.page("/")
    class Home(Page):
        def render(self):
            return SharedCounter()

    client = TestClient(app)
    first_page = client.open("/")
    second_page = client.open("/")

    cookie_header = "; ".join(f"{name}={value}" for name, value in client.http.cookies.items())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http:
        responses = await asyncio.gather(
            *(
                http.post(
                    page.manifest["endpoint"],
                    json={
                        "v": page.manifest["v"],
                        "page": page.manifest["page"],
                        "rev": page.manifest["rev"],
                        "handler": page.find("Count:", "click").get("data-rw-on-click"),
                        "payload": {},
                    },
                    headers={"X-RW-CSRF": page.manifest["csrf"], "Cookie": cookie_header},
                )
                for page in (first_page, second_page)
            )
        )

    assert [response.status_code for response in responses] == [200, 200]
    assert "Count: 2" in client.open("/").text


def test_protocol_version_mismatch(app):
    client = TestClient(app)
    page = client.open("/")
    assert post_event(client, page, v=99).status_code == 410


def test_malformed_and_oversized_events(app):
    client = TestClient(app)
    client.open("/")
    assert client.http.post("/_rational/event", content=b"{not json").status_code == 400
    assert client.http.post("/_rational/event", content=b"x" * 70_000).status_code == 413


def test_handler_ids_cannot_reach_arbitrary_methods(app):
    client = TestClient(app)
    page = client.open("/")
    for handler in ("increment", "c1.99", "c0.1", "__init__"):
        data = post_event(client, page, handler=handler).json()
        assert data["error"]["code"] == "stale"
    assert "Count: 0" in page.text


def test_internal_errors_are_not_leaked(app):
    client = TestClient(app)
    page = client.open("/")
    response = post_event(client, page, handler="c1.2")
    assert response.status_code == 500
    assert "secret" not in response.text and response.json()["error"]["code"] == "internal"


def test_rate_limit(app):
    client = TestClient(app)
    page = client.open("/")
    statuses = [post_event(client, page).status_code for _ in range(7)]
    assert statuses[:5] == [200] * 5 and statuses[5:] == [429, 429]


def test_typed_path_params(app):
    client = TestClient(app)
    assert "user #7" in client.open("/users/7").text
    assert client.open("/users/abc").status_code == 404
    page = client.open("/users/404")
    assert page.status_code == 404 and "No such user" in page.text
    response = client.http.get("/users/0", follow_redirects=False)
    assert response.status_code == 303 and response.headers["location"] == "/"


def test_auth_required_pages(app):
    assert TestClient(app).open("/private").status_code == 401
    app.login_path = "/login"
    response = TestClient(app).http.get("/private", follow_redirects=False)
    assert response.headers["location"] == "/login?next=/private"


def test_html_404_and_json_404(app):
    client = TestClient(app)
    assert "Page not found" in client.open("/missing").text
    assert client.http.get("/missing", headers={"accept": "application/json"}).json() == {"detail": "Not Found"}


def test_static_pages_have_no_session_cookie_or_runtime():
    app = App()

    @app.page("/")
    class Home(Page):
        def render(self):
            return Text("static")

    response = TestClient(app).http.get("/")
    assert "set-cookie" not in response.headers
    assert "runtime.js" not in response.text and "rw-manifest" not in response.text


def test_session_cookie_flags_and_security_headers(app):
    response = TestClient(app).http.get("/")
    cookie = response.headers["set-cookie"]
    assert "rw_sid=" in cookie and "HttpOnly" in cookie and "SameSite=lax" in cookie
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cache-control"] == "no-store"


def test_csp_nonce_mode():
    app = App(csp=True)

    @app.page("/")
    class Home(Page):
        def render(self):
            return Text("x")

    response = TestClient(app).http.get("/")
    policy = response.headers["content-security-policy"]
    nonce = policy.split("'nonce-")[1].split("'")[0]
    assert f'<style id="rw-styles" nonce="{nonce}">' in response.text
    assert "script-src 'self';" in policy


def test_assets_are_served_with_long_cache(app):
    client = TestClient(app)
    runtime = client.http.get(app.runtime_src)
    theme = client.http.get(app.theme_href)
    assert runtime.status_code == theme.status_code == 200
    assert "immutable" in runtime.headers["cache-control"]
    assert "--rw-color-primary" in theme.text
    assert runtime.headers["x-content-type-options"] == "nosniff"
    assert theme.headers["referrer-policy"] == "strict-origin-when-cross-origin"


def test_api_responses_have_baseline_security_headers(app):
    response = TestClient(app).http.get("/api/openapi.json")

    assert response.status_code == 200
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "SAMEORIGIN"


def test_manifest_cannot_break_out_of_script():
    from rational.document import json_for_script

    assert "</script>" not in json_for_script({"x": "</script><script>alert(1)</script>"})


def test_expired_pages_are_evicted():
    app = App(max_pages=2)

    @app.page("/")
    class Home(Page):
        def render(self):
            return Counter()

    client = TestClient(app)
    first = client.open("/")
    client.open("/")
    client.open("/")
    assert post_event(client, first).status_code == 410


def test_mounted_under_a_sub_path():
    from fastapi import FastAPI

    from rational.backend import Service, remote

    app = App()

    @app.page("/")
    class Home(Page):
        def render(self):
            return Counter()

    @app.service
    class PingService(Service):
        @remote(method="GET")
        def ping(self) -> str:
            return "pong"

    outer = FastAPI()
    outer.mount("/app", app)
    client = TestClient(outer)
    page = client.open("/app/")
    assert page.manifest["endpoint"] == "/app/_rational/event" and page.manifest["base"] == "/app"
    assert f'src="/app{app.runtime_src}"' in page.html and f'href="/app{app.theme_href}"' in page.html
    assert client.http.get(f"/app{app.runtime_src}").status_code == 200
    page.click("Increment")
    assert "Count: 1" in page.text
    assert client.http.get("/app/api/ping/ping").json() == "pong"


def test_routers_compose_pages_services_and_hooks():
    from rational import Router
    from rational.backend import Service, remote

    started = []
    admin = Router(prefix="/admin/")

    @admin.page("/")
    class AdminHome(Page):
        def render(self):
            return Text("admin home")

    @admin.page("/users/{user_id}")
    class AdminUser(Page):
        user_id: int

        def render(self):
            return Text(f"user {self.user_id}")

    @admin.service
    class StatsService(Service):
        @remote(method="GET")
        def count(self) -> int:
            return 3

    admin.on_startup(lambda: started.append(True))
    site = Router()
    site.include(admin)

    app = App()
    app.include(site)
    with TestClient(app) as client:
        assert "admin home" in client.open("/admin").text
        assert "user 7" in client.open("/admin/users/7").text
        assert client.http.get("/api/stats/count").json() == 3
    assert started == [True]
    assert app.url_for(AdminUser, user_id=5) == "/admin/users/5"
