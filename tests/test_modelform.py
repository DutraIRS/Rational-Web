import enum
from typing import Literal

import pytest
from pydantic import BaseModel, Field

from rational import App, Component, ModelForm, Page, State, Text
from rational.testing import TestClient


class Role(enum.Enum):
    admin = "admin"
    guest = "guest"


class Signup(BaseModel):
    username: str = Field(min_length=3, max_length=20, description="Public name")
    email: str
    password: str = Field(min_length=8)
    age: int = Field(ge=18, le=120)
    newsletter: bool = False
    role: Role = Role.guest
    plan: Literal["free", "pro"] | None = None
    bio: str = Field(default="", max_length=500)


def render(form):
    app = App()

    @app.page("/")
    class Home(Page):
        def render(self):
            return form

    with TestClient(app) as client:
        return client.open("/").html


def test_controls_follow_the_annotations():
    html = render(ModelForm(Signup, on_submit=lambda: None))
    assert 'name="username"' in html and 'minlength="3"' in html and 'maxlength="20"' in html
    assert "Public name" in html
    assert 'type="email"' in html and 'type="password"' in html
    assert 'type="number"' in html and 'min="18"' in html and 'max="120"' in html
    assert 'type="checkbox"' in html and "<select" in html and "<textarea" in html
    assert "Guest" in html and ">pro<" in html
    assert html.count("<select") == 2 and "required" in html


def test_values_errors_and_password_redaction():
    html = render(
        ModelForm(
            Signup,
            values={"username": "ada", "password": "secret-value", "role": Role.admin},
            errors={"email": "Already taken"},
            exclude=("bio",),
        )
    )
    assert 'value="ada"' in html and "secret-value" not in html
    assert "Already taken" in html and "<textarea" not in html


def test_submit_label_and_disabled():
    html = render(ModelForm(Signup, submit_label="Join", disabled=True))
    assert "Join" in html and "disabled" in html


def test_model_instance_supplies_values():
    html = render(ModelForm(Signup, values=Signup(username="grace", email="g@x.io", password="longenough", age=30)))
    assert 'value="grace"' in html and 'value="30"' in html


def test_end_to_end_validation_shows_under_the_field():
    app = App()

    @app.page("/")
    class Home(Page):
        def render(self):
            return Join()

    class Join(Component):
        done = State("")

        def submit(self, data: Signup):
            self.done = data.username

        def render(self):
            return [ModelForm(Signup, on_submit=self.submit), Text(f"hi {self.done}")]

    with TestClient(app) as client:
        view = client.open("/")
        bad = view.submit({"username": "ab", "email": "e", "password": "x", "age": "5"}, check=False)
        assert bad["error"]["code"] == "validation_error"
        assert {d["field"] for d in bad["error"]["details"]} == {"username", "password", "age"}
        ok = view.submit({"username": "ada", "email": "a@b.c", "password": "longenough", "age": "30", "role": "guest"})
        assert "error" not in ok
        assert "hi ada" in view.text


@pytest.mark.parametrize("kwargs", [{"exclude": ("nope",)}])
def test_unknown_exclude_is_ignored(kwargs):
    assert ModelForm(Signup, **kwargs).tag == "form"
