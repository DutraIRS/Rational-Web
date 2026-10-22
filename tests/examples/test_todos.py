import pytest

from rational.testing import TestClient


@pytest.fixture
def todos(example):
    return example("todos")


def sign_in(client, name):
    data = client.open("/login").submit({"name": name})
    assert data["actions"] == [{"op": "navigate", "url": "/"}]
    return client.open("/")


def test_requires_sign_in(todos):
    with TestClient(todos.app) as client:
        response = client.http.get("/", follow_redirects=False)
        assert response.status_code == 303 and response.headers["location"].startswith("/login")


def test_crud_and_isolation(todos):
    with TestClient(todos.app) as ada_client, TestClient(todos.app) as bob_client:
        ada = sign_in(ada_client, "ada")
        ada.submit({"title": "Write the spec"})
        ada.submit({"title": "Ship it"})
        assert "Write the spec" in ada.text and "2 items left" in ada.text

        ada.fire(ada.field("Write the spec").get("data-rw-on-change"), {"value": True})
        assert "1 item left" in ada.text
        ada.click("Done")
        assert "Ship it" not in ada.text and "Write the spec" in ada.text
        ada.click("All")
        ada.click("Clear completed")
        assert "Write the spec" not in ada.text and "Ship it" in ada.text

        bob = sign_in(bob_client, "bob")
        assert "Ship it" not in bob.text and "Nothing here yet." in bob.text

        # Bob cannot touch Ada's rows through the JSON API either.
        ada_rows = ada_client.http.get("/api/todo/list-todos").json()
        response = bob_client.http.post(
            "/api/todo/remove", json={"todo_id": ada_rows[0]["id"]}, headers={"X-RW-CSRF": bob.manifest["csrf"]}
        )
        assert response.status_code == 404
        assert len(ada_client.http.get("/api/todo/list-todos").json()) == 1


def test_validation(todos):
    with TestClient(todos.app) as client:
        data = client.open("/login").submit({"name": "<script>"})
        assert data["error"]["code"] == "validation_error"
        page = sign_in(client, "ada")
        data = page.submit({"title": ""})
        assert data["error"]["details"][0]["field"] == "title"


def test_remote_api_requires_auth_and_csrf(todos):
    with TestClient(todos.app) as client:
        assert client.http.get("/api/todo/list-todos").status_code == 401
        sign_in(client, "ada")
        assert client.http.post("/api/todo/add", json={"title": "x"}).status_code == 403
        schema = client.http.get("/api/openapi.json").json()
        assert "/api/todo/add" in schema["paths"]
