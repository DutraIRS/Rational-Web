"""Background tasks and the server-sent-events stream.

The stream never ends on its own, and the in-process test client buffers whole responses, so these
tests drive the ASGI app directly on the test's event loop.
"""

import asyncio
import json
import re

import pytest

from rational import App, Button, Column, Component, Page, State, Text
from rational.testing import TestClient


class Raw:
    def __init__(self, app):
        self.app = app
        self.cookie = ""

    def _scope(self, method, path, query, headers):
        merged = {"accept": "text/html", "host": "testserver", **headers}
        if self.cookie:
            merged["cookie"] = self.cookie
        return {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": method,
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "root_path": "",
            "query_string": query.encode(),
            "headers": [(k.lower().encode(), v.encode()) for k, v in merged.items()],
            "client": ("127.0.0.1", 1),
            "server": ("testserver", 80),
        }

    async def request(self, method, path, *, query="", headers=None, body=b""):
        sent = [{"type": "http.request", "body": body, "more_body": False}]
        out = []

        async def receive():
            if sent:
                return sent.pop(0)
            await asyncio.Event().wait()

        async def send(message):
            out.append(message)

        await self.app(self._scope(method, path, query, headers or {}), receive, send)
        start = next(m for m in out if m["type"] == "http.response.start")
        for name, value in start["headers"]:
            if name == b"set-cookie":
                self.cookie = value.decode().split(";", 1)[0]
        content = b"".join(m.get("body", b"") for m in out if m["type"] == "http.response.body")
        return start["status"], content

    async def open_page(self, path="/"):
        status, body = await self.request("GET", path)
        assert status == 200
        html = body.decode()
        manifest = json.loads(re.search(r'id="rw-manifest">(.*?)</script>', html, re.S).group(1))
        return manifest, html

    async def event(self, manifest, handler):
        payload = {"v": manifest["v"], "page": manifest["page"], "rev": manifest["rev"], "handler": handler}
        status, body = await self.request(
            "POST",
            manifest["endpoint"],
            headers={"content-type": "application/json", "x-rw-csrf": manifest["csrf"]},
            body=json.dumps(payload).encode(),
        )
        data = json.loads(body)
        manifest["rev"] = data.get("rev", manifest["rev"])
        return status, data

    def stream(self, manifest):
        return Stream(self, manifest)


class Stream:
    def __init__(self, raw, manifest):
        self.chunks: asyncio.Queue = asyncio.Queue()
        self.status = None
        self._buffer = ""
        self._gone = asyncio.Event()
        scope = raw._scope("GET", manifest["stream"], f"page={manifest['page']}", {"accept": "text/event-stream"})

        async def receive():
            await self._gone.wait()
            return {"type": "http.disconnect"}

        async def send(message):
            if message["type"] == "http.response.start":
                self.status = message["status"]
            elif message["type"] == "http.response.body":
                await self.chunks.put(message.get("body", b"").decode())
                if not message.get("more_body"):
                    await self.chunks.put(None)

        self.task = asyncio.get_running_loop().create_task(raw.app(scope, receive, send))

    async def next(self, timeout=2):
        """The next ``data:`` frame, parsed; ``None`` once the stream has ended."""
        while "\n\n" not in self._buffer:
            chunk = await asyncio.wait_for(self.chunks.get(), timeout)
            if chunk is None:
                return None
            self._buffer += chunk
        frame, self._buffer = self._buffer.split("\n\n", 1)
        if not frame.startswith("data: "):
            return await self.next(timeout)
        return json.loads(frame[6:])

    async def until(self, text, timeout=2):
        while True:
            frame = await self.next(timeout)
            assert frame is not None, f"stream ended before {text!r}"
            if any(text in p["html"] for p in frame.get("patches", [])):
                return frame

    async def close(self):
        self._gone.set()
        try:
            await asyncio.wait_for(self.task, 2)
        except (asyncio.CancelledError, TimeoutError):
            self.task.cancel()


def make_app():
    app = App()
    spawned = {}

    class Ticker(Component):
        count = State(0)

        async def mount(self):
            spawned["task"] = self.run_task(self.tick, 3)

        async def tick(self, times):
            for _ in range(times):
                await asyncio.sleep(0.02)
                self.count += 1

        def render(self):
            return Text(f"Count: {self.count}")

    @app.page("/")
    class Home(Page):
        def render(self):
            return Ticker()

    return app, spawned


async def test_background_task_pushes_patches_over_the_stream():
    app, _ = make_app()
    raw = Raw(app)
    manifest, _html = await raw.open_page()
    assert manifest["stream"] == "/_rational/stream"

    stream = raw.stream(manifest)
    hello = await stream.next()
    assert hello == {"hello": 0}

    batch = await stream.until("Count: 3")
    assert batch["seq"] > 0
    assert batch["patches"][0]["op"] == "morph"
    await stream.close()


async def test_changes_made_before_the_stream_connects_are_delivered_on_connect():
    app, spawned = make_app()
    raw = Raw(app)
    manifest, _html = await raw.open_page()
    await spawned["task"]

    stream = raw.stream(manifest)
    assert (await stream.next()) == {"hello": 0}
    await stream.until("Count: 3")
    await stream.close()


async def test_disposing_the_page_cancels_tasks_and_ends_streams():
    app, spawned = make_app()
    raw = Raw(app)
    manifest, _html = await raw.open_page()
    stream = raw.stream(manifest)
    await stream.next()

    app.pages.get(manifest["page"]).dispose()

    assert await stream.next() is None
    await asyncio.sleep(0)
    assert spawned["task"].cancelled() or spawned["task"].done()
    await stream.close()


async def test_task_started_by_an_event_tells_the_browser_to_open_the_stream():
    app = App()

    class Starter(Component):
        done = State(False)

        async def work(self):
            await asyncio.sleep(0.02)
            self.done = True

        def start(self):
            self.run_task(self.work)

        def render(self):
            return Column(Text(f"Done: {self.done}"), Button("Start", on_click=self.start))

    @app.page("/")
    class Home(Page):
        def render(self):
            return Starter()

    raw = Raw(app)
    manifest, html = await raw.open_page()
    assert manifest["stream"] is None
    handler = re.search(r'data-rw-on-click="([^"]+)"', html).group(1)

    status, data = await raw.event(manifest, handler)
    assert status == 200
    assert {"op": "stream"} in data["actions"]

    manifest["stream"] = "/_rational/stream"
    stream = raw.stream(manifest)
    await stream.next()
    await stream.until("Done: True")
    await stream.close()


async def test_stream_requires_the_owning_session_and_a_live_page():
    app, _ = make_app()
    raw = Raw(app)
    manifest, _html = await raw.open_page()

    stranger = Raw(app)
    status, _ = await stranger.request("GET", "/_rational/stream", query=f"page={manifest['page']}")
    assert status == 403
    status, _ = await raw.request("GET", "/_rational/stream", query="page=nope")
    assert status == 410


async def test_stream_count_is_capped_per_page():
    app, _ = make_app()
    raw = Raw(app)
    manifest, _html = await raw.open_page()
    streams = [raw.stream(manifest) for _ in range(4)]
    for s in streams:
        assert await s.next() == {"hello": 0}

    extra = raw.stream(manifest)
    await asyncio.wait_for(extra.task, 2)
    assert extra.status == 429
    for s in streams:
        await s.close()


def test_run_task_rejects_sync_functions():
    app = App()

    class Bad(Component):
        def mount(self):
            self.run_task(lambda: None)

        def render(self):
            return Text("x")

    @app.page("/")
    class Home(Page):
        def render(self):
            return Bad()

    with pytest.raises(TypeError, match="async"):
        TestClient(
            app,
        ).open("/")
