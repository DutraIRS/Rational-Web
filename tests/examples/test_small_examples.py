"""hello, counter and dashboard: no database."""

from rational.testing import TestClient

from .conftest import load_example


def test_hello_is_static():
    page = TestClient(load_example("hello").app).open("/")
    assert page.status_code == 200 and "Hello, Rational Web" in page.text
    assert page.manifest is None  # no handlers: no JavaScript shipped


def test_counter():
    page = TestClient(load_example("counter").app).open("/")
    page.click("+10")
    page.click("+1")
    page.click("+10")
    assert "Tens 20" in page.text and "Clicks 1" in page.text
    page.input("Your name", "Ada")
    assert "Hello, Ada!" in page.text


def test_dashboard_range_and_refresh():
    page = TestClient(load_example("dashboard").app).open("/")
    before = page.text
    assert "Revenue by region" in before and "Recent orders" in before
    page.input("Range", "7", event="change")
    assert page.text != before
    data = page.input("Range", "9999", event="change")  # not an allowed option: ignored
    assert data["patches"] == []
    page.click("Refresh")
