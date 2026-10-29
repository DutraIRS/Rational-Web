"""The app.on_error hook: pages, events, @remote methods and jobs all report."""

import anyio

from rational import App, Button, Page, Text
from rational.backend import Service, remote
from rational.errors import ErrorInfo
from rational.jobs import Jobs
from rational.testing import TestClient


def make_app():
    app = App(secret_key="k" * 40)
    reported = []

    @app.on_error
    async def report(info: ErrorInfo):
        reported.append(info)

    @app.on_error
    def broken(info: ErrorInfo):  # a failing hook must not break error handling
        raise RuntimeError("hook itself is broken")

    @app.page("/boom")
    class Boom(Page):
        def render(self):
            raise ValueError("render exploded")
            return Text("never")

    class Greeter(Service):
        @remote
        async def fail(self):
            raise ValueError("remote exploded")

    @app.page("/remote")
    class RemotePage(Page):
        def render(self):
            return Text("remote page")

    app.service(Greeter)

    @app.page("/event")
    class EventPage(Page):
        def mount(self):
            self.count = 0

        async def handle_click(self):  # dispatched through the event protocol
            raise ValueError("event exploded")

        def render(self):
            return Button("go", on_click=self.handle_click)

    return app, reported


def test_page_errors_reach_the_hooks():
    from starlette.testclient import TestClient as RawClient

    app, reported = make_app()
    with RawClient(app, raise_server_exceptions=False) as raw:
        response = raw.get("/boom")
    assert response.status_code == 500
    assert len(reported) == 1
    info = reported[0]
    assert info.kind == "page" and isinstance(info.exc, ValueError)
    assert "render exploded" in str(info.exc)
    assert info.request is not None and "/boom" in str(info.request.url)


def test_remote_errors_reach_the_hooks():
    app, reported = make_app()
    client = TestClient(app)
    answer = client.http.post("/api/greeter/fail", json={})
    assert answer.status_code == 500 and answer.json()["error"]["code"] == "internal"
    info = [i for i in reported if i.kind == "remote"][0]
    assert info.extra == {"service": "Greeter", "method": "fail"}
    assert "remote exploded" in str(info.exc)


def test_event_errors_reach_the_hooks():
    app, reported = make_app()
    client = TestClient(app)
    view = client.open("/event")
    view.click("go", check=False)
    info = [i for i in reported if i.kind == "event"][0]
    assert isinstance(info.exc, ValueError) and "event exploded" in str(info.exc)
    assert info.extra.get("handler")


def test_job_failures_reach_the_hooks():
    app = App(secret_key="k" * 40)
    jobs = Jobs(app)
    reported = []

    @app.on_error
    def report(info):
        reported.append(info)

    @jobs.job(retries=0)
    async def explode():
        raise ValueError("job exploded")

    async def run():
        await jobs.start()
        try:
            await explode.enqueue()
            await anyio.sleep(0.5)
        finally:
            await jobs.stop()

    anyio.run(run)
    info = [i for i in reported if i.kind == "job"][0]
    assert "job exploded" in str(info.exc)
    assert info.extra["job"].endswith("explode") and info.extra["final"] is True and info.request is None
