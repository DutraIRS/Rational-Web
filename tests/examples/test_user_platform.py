import pytest

from rational.testing import TestClient


@pytest.fixture
def platform(example):
    return example("user-platform")


def sign_up(client, name, email, password="correct horse"):
    page = client.open("/signup")
    data = page.submit({"name": name, "email": email, "password": password, "confirm": password})
    assert data["actions"] == [{"op": "navigate", "url": "/"}], data
    return client.open("/")


def test_sign_up_validation(platform):
    with TestClient(platform.app) as client:
        page = client.open("/signup")
        data = page.submit({"name": "Ada", "email": "nope", "password": "short", "confirm": "different"})
        fields = {d["field"]: d["message"] for d in data["error"]["details"]}
        assert fields["email"] == "Enter a valid email address"  # no "Value error, " prefix
        assert "password" in fields and fields["confirm"] == "Passwords do not match"


def test_account_lifecycle(platform):
    with TestClient(platform.app) as client:
        assert client.http.get("/", follow_redirects=False).headers["location"] == "/login?next=/"
        home = sign_up(client, "Ada Lovelace", "ada@example.com")
        assert "Welcome, Ada Lovelace" in home.text and "admin" in home.text  # first user is admin

        # Duplicate email is a FieldError shown under the email field.
        with TestClient(platform.app) as other:
            data = other.open("/signup").submit(
                {"name": "Imposter", "email": "ADA@example.com", "password": "12345678", "confirm": "12345678"}
            )
            assert data["error"]["details"] == [
                {"field": "email", "message": "An account with this email already exists"}
            ]

        settings = client.open("/settings")
        data = settings.submit({"name": "Ada King", "bio": "Analyst"}, button="Save profile")
        assert data["actions"] == [{"op": "navigate", "url": "/settings?saved=profile"}]
        assert "Ada King" in client.open("/settings?saved=profile").text

        data = settings.submit({"current": "wrong", "new": "new password"}, button="Change password")
        assert data["error"]["details"] == [{"field": "current", "message": "That is not your current password"}]
        data = settings.submit({"current": "correct horse", "new": "new password"}, button="Change password")
        assert "Password changed." in settings.text

        client.open("/").click("Sign out")
        login = client.open("/login?next=/settings")
        data = login.submit({"email": "ada@example.com", "password": "correct horse"})
        assert data["error"]["details"][0]["field"] == "password"
        data = login.submit({"email": "ada@example.com", "password": "new password"})
        assert data["actions"] == [{"op": "navigate", "url": "/settings"}]


def test_open_redirects_are_refused(platform):
    with TestClient(platform.app) as client:
        sign_up(client, "Ada", "ada@example.com")
        client.open("/").click("Sign out")
        login = client.open("/login?next=//evil.example")
        data = login.submit({"email": "ada@example.com", "password": "correct horse"})
        assert data["actions"] == [{"op": "navigate", "url": "/"}]


def test_roles_and_admin_area(platform):
    with TestClient(platform.app) as admin, TestClient(platform.app) as member:
        sign_up(admin, "Ada", "ada@example.com")
        sign_up(member, "Bob", "bob@example.com")

        assert member.open("/admin").status_code == 403
        assert member.http.get("/api/admin/list-users").status_code == 403

        page = admin.open("/admin")
        assert "Bob" in page.text and "2 accounts" in page.text
        page.input("Role of Bob", "admin", event="change")
        assert member.http.get("/api/account/me").json()["role"] == "admin"  # takes effect immediately
        page.click("Delete")
        assert "1 account" in page.text and "Bob" not in page.text
        assert member.http.get("/api/account/me").status_code == 401  # deleted account is signed out


def test_swagger_ui_carries_the_csrf_token(platform):
    with TestClient(platform.app) as client:
        anonymous = client.http.get("/api/docs").text
        assert "swagger-ui" in anonymous and '"csrf":""' in anonymous
        sign_up(client, "Ada", "ada@example.com")
        signed_in = client.http.get("/api/docs").text
        assert '"csrf":""' not in signed_in and "X-RW-CSRF" in signed_in
        tags = {t["name"] for t in client.http.get("/api/openapi.json").json()["tags"]}
        assert tags == {"account", "admin"}
