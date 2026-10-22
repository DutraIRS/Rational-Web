"""Smoke tests for framework behavior at the declared dependency floor."""

from rational import App, Page, Text


def test_page_route_registration_does_not_infer_a_response_model():
    app = App()

    @app.page("/")
    class Home(Page):
        def render(self):
            return Text("ready")

    assert app.fastapi.routes[-1].path == "/"
