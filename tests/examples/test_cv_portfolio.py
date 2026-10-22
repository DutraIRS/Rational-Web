import pytest

from rational.testing import TestClient


@pytest.fixture
def cv(example):
    return example("cv-portfolio")


def test_page_renders_every_section(cv):
    page = TestClient(cv.app).open("/")
    text = page.text
    for heading in ("Alex Rivera", "Experience", "Skills", "Projects", "Contact", "Staff engineer", "FastAPI"):
        assert heading in text
    assert {s.get("id") for s in page.dom.find_all("section")} >= {"experience", "skills", "projects", "contact"}
    assert page.dom.find_all(id="about")


def test_project_filter(cv):
    page = TestClient(cv.app).open("/")
    assert "6 projects" in page.text
    page.click("Redis")
    assert "2 projects" in page.text and "Tidewatch" in page.text and "Ledgerly" not in page.text
    page.click("All")
    assert "6 projects" in page.text


def test_contact_form_validation_and_honeypot(cv):
    from services import INBOX  # the example's own services package, loaded by the fixture

    INBOX.clear()
    page = TestClient(cv.app).open("/")
    data = page.submit({"name": "Sam", "email": "nope", "message": "hi"})
    fields = {d["field"]: d["message"] for d in data["error"]["details"]}
    assert fields == {
        "email": "Enter a valid email address so I can reply",
        "message": "String should have at least 10 characters",
    }

    page.submit({"name": "Bot", "email": "bot@spam.io", "message": "Buy cheap things now!", "website": "spam.io"})
    assert INBOX == [] and "Thanks, Bot!" in page.text  # bots get the same answer

    page = TestClient(cv.app).open("/")
    page.submit({"name": "Sam", "email": "sam@example.com", "message": "Let's build something together."})
    assert "Thanks, Sam!" in page.text and [m.email for m in INBOX] == ["sam@example.com"]


def test_contact_api(cv):
    client = TestClient(cv.app)
    response = client.http.post("/api/contact/send", json={"name": "A", "email": "a@b.co", "message": "hello"})
    assert response.status_code == 200 and response.json() is True
