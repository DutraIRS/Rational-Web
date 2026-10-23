import asyncio
import time

import pytest

from rational import App, Button, Column, Component, Page, State, Text, threaded, timeout
from rational.backend.services import Service, remote
from rational.concurrency import HandlerTimeout, invoke
from rational.testing import TestClient


def on_loop():
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return False
    return True


def press(page, text):
    return page.fire(page.find(text, "click").attrs["data-rw-on-click"], {}, check=False)


def make_app(**options):
    app = App(**options)
    seen: dict[str, object] = {}

    class Work(Component):
        status = State("idle")

        async def slow_async(self):
            await asyncio.sleep(5)
            self.status = "finished"

        async def probe(self):
            seen["loop_thread"] = on_loop()

        def blocking(self):
            seen["thread"] = on_loop()
            time.sleep(0.01)
            self.status = "blocked-done"

        @timeout(0.05)
        async def limited(self):
            await asyncio.sleep(5)

        @timeout(None)
        async def unlimited(self):
            await asyncio.sleep(0.1)
            self.status = "unlimited-done"

        @threaded
        def pinned_thread(self):
            seen["pinned"] = on_loop()

        @threaded(enabled=False)
        def pinned_loop(self):
            seen["loop"] = on_loop()

        def render(self):
            return Column(
                Text(f"Status: {self.status}"),
                Button("Slow", on_click=self.slow_async),
                Button("Probe", on_click=self.probe),
                Button("Block", on_click=self.blocking),
                Button("Limited", on_click=self.limited),
                Button("Unlimited", on_click=self.unlimited),
                Button("Pinned thread", on_click=self.pinned_thread),
                Button("Pinned loop", on_click=self.pinned_loop),
            )

    @app.page("/")
    class Home(Page):
        def render(self):
            return Work()

    return app, seen


def test_handler_timeout_returns_504_and_page_keeps_working():
    app, _ = make_app(handler_timeout=0.05)
    page = TestClient(app).open("/")

    result = press(page, "Slow")

    assert result["error"]["code"] == "timeout"
    page.click("Block")
    assert "Status: blocked-done" in page.text


def test_per_handler_timeout_overrides_app_default():
    app, _ = make_app(handler_timeout=0.01)
    page = TestClient(app).open("/")

    page.click("Unlimited")
    assert "Status: unlimited-done" in page.text

    limited = press(page, "Limited")
    assert limited["error"]["code"] == "timeout"


def test_sync_handlers_run_on_the_loop_by_default():
    app, seen = make_app()
    page = TestClient(app).open("/")

    page.click("Probe")
    page.click("Block")

    assert seen["thread"] is True


def test_sync_handlers_can_run_in_worker_threads():
    app, seen = make_app(sync_handlers="thread")
    page = TestClient(app).open("/")

    page.click("Probe")
    page.click("Block")
    page.click("Pinned loop")

    assert seen["thread"] is False
    assert "Status: blocked-done" in page.text
    assert seen["loop"] is True


def test_threaded_decorator_overrides_the_app_default():
    app, seen = make_app()
    page = TestClient(app).open("/")

    page.click("Probe")
    page.click("Pinned thread")

    assert seen["pinned"] is False


def test_invalid_options_are_rejected():
    with pytest.raises(ValueError):
        App(handler_timeout=0)
    with pytest.raises(ValueError):
        App(sync_handlers="fork")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        timeout(-1)


async def test_handler_raised_timeout_error_is_not_masked():
    async def raises():
        raise TimeoutError("upstream")

    with pytest.raises(TimeoutError, match="upstream"):
        await invoke(raises, timeout=5)


async def test_invoke_passes_keyword_arguments_even_named_timeout():
    def fn(timeout):
        return timeout

    assert await invoke(fn, kwargs={"timeout": 3}, threads=True) == 3


def test_remote_methods_honour_timeout_and_threads():
    app = App(handler_timeout=0.05, sync_handlers="thread")
    ran_in: dict[str, object] = {}

    @app.service
    class Jobs(Service):
        @remote(method="POST")
        async def stall(self) -> str:
            await asyncio.sleep(5)
            return "late"

        @remote(method="GET")
        async def probe(self) -> str:
            ran_in["loop"] = on_loop()
            return "ok"

        @remote(method="GET")
        def quick(self) -> str:
            ran_in["thread"] = on_loop()
            return "ok"

    client = TestClient(app)
    session = app.sessions.create()
    headers = {"X-RW-CSRF": session.csrf, "Cookie": f"rw_sid={session.id}"}

    stalled = client.http.post("/api/jobs/stall", json={}, headers=headers)
    client.http.get("/api/jobs/probe", headers=headers)
    quick = client.http.get("/api/jobs/quick", headers=headers)

    assert stalled.status_code == HandlerTimeout.status == 504
    assert stalled.json()["error"]["code"] == "timeout"
    assert quick.json() == "ok"
    assert ran_in["thread"] is False and ran_in["loop"] is True
