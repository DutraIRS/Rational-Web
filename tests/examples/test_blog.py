import pytest

from rational.testing import TestClient


@pytest.fixture
def blog(example):
    return example("blog")


def test_public_pages_ship_no_javascript(blog):
    with TestClient(blog.app) as client:
        index = client.open("/")
        assert "Hello, Rational Web" in index.text and "Pages that ship no JavaScript" in index.text
        assert "An unfinished draft" not in index.text  # drafts are hidden from readers
        assert index.manifest is None and "runtime.js" not in index.html

        tag = client.open("/tag/performance")
        assert "Pages that ship no JavaScript" in tag.text and "Hello, Rational Web" not in tag.text


def test_post_page_renders_markup_and_comments(blog):
    with TestClient(blog.app) as client:
        post = client.open("/posts/hello-rational-web")
        assert post.dom.find_all("h2")[0].text == "One model"
        assert [li.text for li in post.dom.find_all("li")][:3] == [
            "Server-rendered first",
            "Explicit boundaries",
            "Typed styles",
        ]
        assert post.manifest is not None  # the comment form is interactive
        post.submit({"author": "Grace", "body": "<b>Nice</b> post"})
        assert "Comments (1)" in post.text and "<b>Nice</b> post" in post.text  # shown as text, escaped
        assert "<b>Nice</b>" not in post.html

        assert client.open("/posts/an-unfinished-draft").status_code == 404
        assert client.open("/posts/missing").status_code == 404


def test_admin_writes_posts_with_live_preview(blog):
    with TestClient(blog.app) as client:
        assert client.http.get("/admin", follow_redirects=False).headers["location"] == "/login?next=/admin"
        login = client.open("/login")
        assert login.submit({"password": "nope"})["error"]["details"][0]["message"] == "Wrong password"
        assert login.submit({"password": "rational"})["actions"] == [{"op": "navigate", "url": "/admin"}]

        admin = client.open("/admin")
        assert "An unfinished draft" in admin.text and "draft" in admin.text

        editor = client.open("/admin/posts/new")
        editor.input("Title", "Live preview")
        editor.input("Body", "## Section\n\n- one\n- two")
        preview = editor.text
        assert "Live preview" in preview and "Section" in preview and "one two" in preview

        data = editor.submit({"title": "Hello, Rational Web", "body": "dup"})
        assert data["error"]["details"][0]["field"] == "slug"  # the address is taken
        data = editor.submit({"title": "Live preview", "tags": "Demo, Python", "body": "Text", "published": "true"})
        assert data["actions"] == [{"op": "navigate", "url": "/admin"}]

        post = client.open("/posts/live-preview")
        assert post.status_code == 200 and "demo" in post.text

        admin = client.open("/admin")
        admin.click("Publish")  # publishes the draft
        assert client.open("/posts/an-unfinished-draft").status_code == 200


def test_feed_and_public_api(blog):
    with TestClient(blog.app) as client:
        feed = client.http.get("/feed.xml")
        assert feed.headers["content-type"].startswith("application/rss+xml")
        assert "<title>Hello, Rational Web</title>" in feed.text and "unfinished" not in feed.text

        posts = client.http.get("/api/blog/list-posts").json()
        assert {p["slug"] for p in posts} == {"hello-rational-web", "pages-that-ship-no-javascript"}
        assert client.http.get("/api/blog/get-post", params={"slug": "an-unfinished-draft"}).status_code == 404
        response = client.http.post("/api/blog/save-post", json={"post": {"title": "Hack"}})
        assert response.status_code == 401  # writing needs the admin session
