"""Per-page HTTP control: status codes, Cache-Control and ETag/304."""

from rational import App, Page, Text
from rational.testing import TestClient


def make_app():
    app = App(secret_key="k" * 40)

    @app.page("/gone")
    class Gone(Page):
        status = 410

        def render(self):
            return Text("this page has moved on")

    @app.page("/fast")
    class Fast(Page):
        cache_control = "public, max-age=3600"

        def render(self):
            return Text("cache me")

    @app.page("/tagged")
    class Tagged(Page):
        def mount(self):
            self.etag = '"v1"'

        def render(self):
            return Text("etagged content")

    @app.page("/plain")
    class Plain(Page):
        def render(self):
            return Text("defaults")

    return app


def test_status_code_comes_from_the_page():
    client = TestClient(make_app())
    assert client.http.get("/gone").status_code == 410
    assert "moved on" in client.http.get("/gone").text


def test_cache_control_and_the_default():
    client = TestClient(make_app())
    assert client.http.get("/fast").headers["cache-control"] == "public, max-age=3600"
    assert client.http.get("/plain").headers["cache-control"] in ("no-cache", "no-store")


def test_etag_answers_304_for_a_matching_if_none_match():
    client = TestClient(make_app())
    first = client.http.get("/tagged")
    assert first.headers["etag"] == '"v1"' and first.status_code == 200

    same = client.http.get("/tagged", headers={"If-None-Match": '"v1"'})
    assert same.status_code == 304 and same.headers.get("etag") == '"v1"'

    weak = client.http.get("/tagged", headers={"If-None-Match": 'W/"v1"'})
    assert weak.status_code == 304

    other = client.http.get("/tagged", headers={"If-None-Match": '"v2"'})
    assert other.status_code == 200 and "etagged content" in other.text


def test_etag_set_in_mount_from_the_page_data():
    app = App(secret_key="k" * 40)

    @app.page("/docs/{slug}")
    class Doc(Page):
        slug: str

        def mount(self):
            self.etag = f'"{self.slug}-v3"'

        def render(self):
            return Text(self.etag)

    client = TestClient(app)
    response = client.http.get("/docs/faq")
    assert response.headers["etag"] == '"faq-v3"'
    again = client.http.get("/docs/faq", headers={"If-None-Match": '"faq-v3"'})
    assert again.status_code == 304
    assert client.http.get("/docs/other", headers={"If-None-Match": '"faq-v3"'}).status_code == 200


def test_visitor_specific_pages_are_never_shared_in_a_cache():
    from rational import Button, State

    app = App()

    @app.page("/live")
    class Live(Page):
        cache_control = "public, max-age=3600"  # ignored: this page carries a CSRF token and page id
        n = State(0)

        def bump(self):
            self.n += 1

        def render(self):
            return Button(f"n={self.n}", on_click=self.bump)

    @app.page("/greet")
    class Greet(Page):
        cache_control = "public, max-age=60"
        etag = "v2"  # unquoted: quoted when sent

        def render(self):
            self.context.session["seen"] = True  # creates a session: its cookie must not be cached
            return Text("hi")

    assert TestClient(app).http.get("/live").headers["cache-control"] == "no-store"
    greet = TestClient(app).http.get("/greet")  # a new visitor: this response starts their session
    assert greet.headers["cache-control"] == "private, no-cache" and "set-cookie" in greet.headers
    assert greet.headers["etag"] == '"v2"'


def test_the_csrf_endpoint_and_cacheable_pages_with_client_components():
    from tests.clientapp import make_app as client_app

    client = TestClient(client_app())
    assert client.http.get("/_rational/csrf").json() == {"csrf": None}  # no session, nothing to protect
    client.open("/todos")  # an interactive page starts a session
    token = client.http.get("/_rational/csrf")
    assert token.headers["cache-control"] == "no-store" and len(token.json()["csrf"]) > 20

    cached = client.http.get("/cached-todos")
    assert cached.headers["cache-control"] == "public, max-age=60" and '"csrf":null' in cached.text
    assert TestClient(client_app()).http.get("/todos").headers["cache-control"] == "no-store"
