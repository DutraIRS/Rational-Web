import logging

import pytest

from rational import App, Button, Component, Page
from rational.testing import TestClient


class Counter(Component):
    count = 0

    def increment(self):
        self.count += 1

    def render(self):
        return Button(f"Count: {self.count}", on_click=self.increment)


def make_app():
    app = App()

    @app.page("/")
    class Home(Page):
        def render(self):
            return Counter()

    return app


def test_http_requests_have_correlatable_structured_logs(caplog):
    app = make_app()
    caplog.set_level(logging.INFO, logger="rational")

    response = TestClient(app).http.get("/", headers={"X-Request-ID": "client-42"})

    assert response.headers["x-request-id"] == "client-42"
    record = next(r for r in caplog.records if getattr(r, "rational_event", None) == "http.request.completed")
    assert record.rational_request_id == "client-42"
    assert record.rational_method == "GET"
    assert record.rational_path == "/"
    assert record.rational_status_code == 200
    assert record.rational_duration_ms >= 0


def test_invalid_request_ids_are_replaced():
    response = TestClient(make_app()).http.get("/", headers={"X-Request-ID": "bad id"})
    request_id = response.headers["x-request-id"]

    assert request_id and request_id != "bad id"
    assert len(request_id) == 32


def test_event_dispatch_timing_is_logged(caplog):
    app = make_app()
    caplog.set_level(logging.INFO, logger="rational")
    client = TestClient(app)
    page = client.open("/")
    caplog.clear()

    page.click("Count: 0")

    event_record = next(r for r in caplog.records if getattr(r, "rational_event", None) == "event.dispatch.completed")
    request_record = next(r for r in caplog.records if getattr(r, "rational_event", None) == "http.request.completed")
    assert event_record.rational_request_id == request_record.rational_request_id
    assert event_record.rational_handler
    assert event_record.rational_duration_ms >= 0
    assert event_record.rational_status_code == 200


def test_slow_render_is_reported(caplog):
    app = make_app()
    app.logging.configure(slow_render_threshold_ms=0)
    caplog.set_level(logging.WARNING, logger="rational")

    response = TestClient(app).http.get("/")

    assert response.status_code == 200
    record = next(r for r in caplog.records if getattr(r, "rational_event", None) == "page.render.slow")
    assert record.levelno == logging.WARNING
    assert record.rational_duration_ms >= 0
    assert record.rational_threshold_ms == 0


@pytest.mark.parametrize("value", [-1, float("nan"), float("inf")])
def test_slow_render_threshold_must_be_finite_and_non_negative(value):
    with pytest.raises(ValueError, match="finite non-negative"):
        make_app().logging.configure(slow_render_threshold_ms=value)


def test_request_id_header_name_is_validated():
    with pytest.raises(ValueError, match="valid HTTP header"):
        make_app().logging.configure(request_id_header="Bad Header")
