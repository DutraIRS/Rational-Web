"""Per-page HTTP control: status codes, Cache-Control and ETag/304."""

import pytest

from rational import App, Button, Component, Page, Text
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


def test_duplicate_page_path_is_rejected():
    app = App()

    @app.page("/")
    class A(Page):
        def render(self):
            return None

    with pytest.raises(TypeError, match="already registered"):

        @app.page("/")
        class B(Page):
            def render(self):
                return None


def test_same_page_class_at_two_paths():
    app = App()

    @app.page("/one")
    @app.page("/two")
    class Both(Page):
        def render(self):
            return None

    assert sorted(app.routes) == ["/one", "/two"]
    with pytest.raises(ValueError, match="multiple paths"):
        app.url_for(Both)
    assert app.url_for(Both, _path="/one") == "/one"
    assert app.url_for(Both, _path="/two") == "/two"
    with TestClient(app) as client:
        assert client.open("/one").status_code == 200
        assert client.open("/two").status_code == 200


def tagged(etag='"v1"', **attrs):
    app = App(secret_key="k" * 40)

    @app.page("/")
    class Tagged(Page):
        def mount(self):
            self.etag = etag
            for name, value in attrs.items():
                setattr(self, name, value)

        def render(self):
            return Text("hello")

    return TestClient(app).http


@pytest.mark.parametrize("header", ['"a", "v1"', '"a","v1"', 'W/"v1"', '"a", W/"v1", "b"', "*"])
def test_if_none_match_lists_weak_tags_and_the_wildcard(header):
    assert tagged().get("/", headers={"If-None-Match": header}).status_code == 304


def test_if_none_match_without_our_tag_gets_the_page():
    assert tagged().get("/", headers={"If-None-Match": '"other", "v2"'}).status_code == 200


def test_only_a_page_served_as_200_answers_304():
    assert tagged(status=404).get("/", headers={"If-None-Match": '"v1"'}).status_code == 404


def test_a_304_skips_building_the_document(monkeypatch):
    def fail(**kwargs):
        raise AssertionError("the document was built for nothing")

    http = tagged()
    monkeypatch.setattr("rational.pages.render_document", fail)
    assert http.get("/", headers={"If-None-Match": '"v1"'}).status_code == 304


def test_a_page_for_one_visitor_never_answers_304_with_their_token_in_it():
    class Clicks(Component):
        def render(self):
            return Button("Go", on_click=lambda: None)

    app = App()

    @app.page("/")
    class Personal(Page):
        etag = '"v1"'

        def render(self):
            return Clicks()

    reply = TestClient(app).http.get("/", headers={"If-None-Match": '"v1"'})
    assert reply.status_code == 200 and reply.headers["cache-control"] == "no-store" and "etag" not in reply.headers


class Tracked(Component):
    unmounted: list = []

    def unmount(self):
        Tracked.unmounted.append(self.path)

    def render(self):
        return Text("tracked")


def test_static_pages_and_failed_renders_unmount_what_they_mounted():
    Tracked.unmounted = []
    app = App()

    @app.page("/static")
    class Static(Page):
        def render(self):
            return Tracked()

    class Explodes(Component):
        def render(self):
            raise ValueError("no")

    @app.page("/fails")
    class Fails(Page):
        def render(self):
            return [Tracked(), Explodes()]

    client = TestClient(app)
    client.http.get("/static")
    assert len(Tracked.unmounted) == 1 and len(app.pages) == 0
    with pytest.raises(ValueError):
        client.http.get("/fails")
    assert len(Tracked.unmounted) == 2


def test_url_for_encodes_what_it_puts_in_the_path():
    app = App()

    @app.page("/users/{name}")
    class User(Page):
        name: str

        def render(self):
            return Text(f"name={self.name}")

    @app.page("/files/{where:path}")
    class File(Page):
        where: str

        def render(self):
            return Text(self.where)

    assert app.url_for(User, name="a/b c?x=1") == "/users/a%2Fb%20c%3Fx%3D1"
    assert app.url_for(File, where="docs/a b.txt") == "/files/docs/a%20b.txt"
    assert "name=é x" in TestClient(app).open(app.url_for(User, name="é x")).text


def test_paths_from_a_generator_can_be_read_again():
    app = App()

    @app.page("/p/{slug}", paths=({"slug": s} for s in ("a", "b")))
    class P(Page):
        slug: str

        def render(self):
            return Text(self.slug)

    route = app.routes["/p/{slug}"]
    assert route.urls() == ["/p/a", "/p/b"] == route.urls()


def test_a_path_parameter_cannot_use_a_name_that_means_something_else_on_a_page():
    app = App()
    with pytest.raises(TypeError, match=r"rename path parameter\(s\) \['status'\]"):

        @app.page("/orders/{status}")
        class Orders(Page):
            status: str

            def render(self):
                return Text("no")
