from app import app

from rational.testing import TestClient


def test_sign_the_guestbook():
    with TestClient(app) as client:  # "with" runs the startup hooks: the tables get created
        page = client.open("/")
        page.submit({"name": "Ada", "message": "Hello from the tests!"})
        assert "Hello from the tests!" in page.text


def test_validation_messages():
    with TestClient(app) as client:
        page = client.open("/")
        data = page.submit({"name": "", "message": "Visit https://spam.example"})
        fields = {error["field"] for error in data["error"]["details"]}
        assert fields == {"name"}  # the form model rejects the empty name first
        data = page.submit({"name": "Bot", "message": "Visit https://spam.example"})
        assert data["error"]["details"] == [{"field": "message", "message": "Links are not allowed"}]


def test_likes_are_per_card():
    with TestClient(app) as client:
        page = client.open("/")
        page.submit({"name": "Grace", "message": "First"})
        page.submit({"name": "Alan", "message": "Second"})
        page.click("♥ 0")
        assert page.text.count("♥ 1") == 1 and page.text.count("♥ 0") >= 1


def test_the_json_api():
    with TestClient(app) as client:
        client.http.post("/api/guestbook/sign", json={"name": "API", "message": "Signed over HTTP"})
        entries = client.http.get("/api/guestbook/entries").json()
        assert entries[0]["message"] == "Signed over HTTP"
