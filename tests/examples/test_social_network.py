import pytest
from sqlalchemy import event

from rational.testing import TestClient


@pytest.fixture
def social(example):
    return example("social-network")


def sign_in(client, handle):
    page = client.open("/login")
    data = page.click(f"Continue as @{handle}")
    assert data["actions"] == [{"op": "navigate", "url": "/"}]
    return client.open("/")


def test_explore_is_public_and_read_only(social):
    with TestClient(social.app) as client:
        explore = client.open("/explore")
        assert "A nanosecond is about 30 cm of wire" in explore.text and "If debugging is removing bugs" in explore.text
        assert not [b for b in explore.dom.find_all("button") if "Like post" in (b.get("aria-label") or "")]
        assert client.http.get("/", follow_redirects=False).headers["location"] == "/login?next=/"


def test_timeline_compose_and_like(social):
    with TestClient(social.app) as client:
        home = sign_in(client, "ada")  # ada follows grace and alan
        text = home.text
        assert "A nanosecond" in text and "Can machines think?" in text and "The engine weaves" in text
        assert "Write the error handling first" not in text  # margaret: not followed
        assert "Who to follow" in text and "@edsger" in text and "@grace" not in text.split("Who to follow")[1]

        home.input("What's happening?", "x" * 281)
        assert "-1 characters left" in home.html
        data = home.submit({"body": "   "})
        assert data["error"]["details"] == [{"field": "body", "message": "Write something first"}]
        home.submit({"body": "Hello from the Rational Web test suite!"})
        assert home.text.index("Hello from the Rational Web") < home.text.index("A nanosecond")  # newest first

        # Ada already likes Grace's newest post (seed data); her older one has no likes yet.
        assert home.find("Unlike post by Grace Hopper (3 likes)", "click").get("aria-pressed") == "true"
        home.click("Unlike post by Grace Hopper (3 likes)")
        assert home.find("Like post by Grace Hopper (2 likes)", "click").get("aria-pressed") == "false"
        home.click("Like post by Grace Hopper (0 likes)")
        assert home.find("Unlike post by Grace Hopper (1 like)", "click").get("aria-pressed") == "true"


def test_following_changes_the_timeline(social):
    with TestClient(social.app) as client:
        home = sign_in(client, "ada")
        assert "If debugging is removing bugs" not in home.text
        home.click("Follow @edsger")
        assert "If debugging is removing bugs" in home.text  # the page reloaded the timeline
        assert "@edsger" not in home.text.split("Who to follow")[1]

        profile = client.open("/u/grace")
        assert "Grace Hopper" in profile.text and "Following" in profile.text
        followers = profile.text.split("followers")[0].split()[-1]
        profile.click("Following")
        assert "Follow" in profile.text and profile.text.split("followers")[0].split()[-1] == str(int(followers) - 1)
        assert "This is you." in client.open("/u/ada").text
        assert client.open("/u/nobody").status_code == 404


def test_join(social):
    with TestClient(social.app) as client:
        login = client.open("/login")
        data = login.submit({"handle": "No Spaces!", "name": "X"})
        assert data["error"]["details"][0]["message"] == "Use 3 to 20 lowercase letters, digits or underscores"
        data = login.submit({"handle": "@Ada", "name": "Another Ada"})
        assert data["error"]["details"] == [{"field": "handle", "message": "That handle is taken"}]
        data = login.submit({"handle": "newbie", "name": "New Person"})
        assert data["actions"] == [{"op": "navigate", "url": "/"}]
        home = client.open("/")
        assert "Follow people to fill your timeline." in home.text


def test_api(social):
    with TestClient(social.app) as client:
        posts = client.http.get("/api/social/explore").json()
        assert len(posts) == 8 and posts[0]["author_handle"] == "grace" and posts[0]["liked"] is False
        assert client.http.post("/api/social/publish", json={"body": "hi"}).status_code == 401
        assert client.http.get("/api/social/profile", params={"handle": "ada"}).json()["followers"] == 2


def test_post_lists_use_a_fixed_number_of_queries(social):
    """The README's claim: no N+1, however many posts are shown."""
    from models import database

    statements: list[str] = []
    event.listen(database.engine.sync_engine, "before_cursor_execute", lambda *a: statements.append(a[2]))

    with TestClient(social.app) as client:
        sign_in(client, "ada")

        def queries_for_explore() -> int:
            statements.clear()
            client.http.get("/api/social/explore")
            return len(statements)

        few = queries_for_explore()
        page = client.open("/")
        for i in range(15):
            page.submit({"body": f"Post number {i}"})
        assert len(client.http.get("/api/social/explore").json()) == 23
        assert queries_for_explore() == few
