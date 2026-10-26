"""Reproducible performance numbers for Rational Web.

    python benchmarks/run.py            # prints a Markdown report
    python benchmarks/run.py --quick    # fewer iterations

What is measured, and what is not:

* Requests go through the full ASGI stack in-process (``httpx.ASGITransport``): routing,
  rendering, CSS compilation, sessions, JSON. There is no network and no HTTP server, so
  these numbers are the framework's own cost per request on one CPU core. A real server
  (uvicorn) adds its own parsing and socket overhead on top.
* The baseline is plain FastAPI returning an equivalent, *pre-built* HTML string — the
  floor for "Python serving HTML through FastAPI".
"""

from __future__ import annotations

import argparse
import asyncio
import gzip
import platform
import statistics
import sys
import time
from collections.abc import Awaitable, Callable
from pathlib import Path

import httpx
from fastapi import FastAPI
from fastapi.responses import HTMLResponse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from rational import App, Button, Column, Component, Page, State, Style, Text, h  # noqa: E402
from rational.context import Context  # noqa: E402
from rational.rendering.html import to_html  # noqa: E402
from rational.runtime import PageRuntime  # noqa: E402
from rational.styling.compiler import StyleCompiler, StyleSheet  # noqa: E402

# -- apps under test ------------------------------------------------------------------------


class Counter(Component):
    count = State(0)

    def increment(self):
        self.count += 1

    def render(self):
        return Column(Text(f"Count: {self.count}"), Button("Increment", on_click=self.increment))


class Table(Component):
    rows: int = 100

    def render(self):
        cell = Style(padding_y="xs", padding_x="sm", border_bottom=True)
        return h(
            "table",
            h(
                "tbody",
                *[
                    h("tr", h("td", str(i), style=cell), h("td", f"row {i}", style=cell), key=i)
                    for i in range(self.rows)
                ],
            ),
        )


def rational_app() -> App:
    app = App(title="bench")

    @app.page("/static")
    class Static(Page):
        def render(self):
            return Column(h("h1", "Hello"), Text("A static page."))

    @app.page("/counter")
    class CounterPage(Page):
        def render(self):
            return Counter()

    @app.page("/table")
    class TablePage(Page):
        def render(self):
            return Table(rows=100)

    return app


def fastapi_baseline() -> FastAPI:
    html = (
        "<!doctype html><html><head><title>bench</title></head><body><h1>Hello</h1><p>A static page.</p></body></html>"
    )
    api = FastAPI()

    @api.get("/static", response_class=HTMLResponse)
    async def static() -> str:
        return html

    return api


# -- measurement helpers -----------------------------------------------------------------------


async def throughput(fn: Callable[[], Awaitable[object]], seconds: float) -> tuple[float, list[float]]:
    for _ in range(20):  # warm up caches and the event loop
        await fn()
    samples: list[float] = []
    deadline = time.perf_counter() + seconds
    while time.perf_counter() < deadline:
        start = time.perf_counter()
        await fn()
        samples.append(time.perf_counter() - start)
    return len(samples) / sum(samples), samples


def pct(samples: list[float], q: float) -> float:
    return statistics.quantiles(samples, n=100)[int(q) - 1] * 1000


async def main(seconds: float) -> None:
    app = rational_app()
    base = fastapi_baseline()
    rows: list[tuple[str, float, float, float]] = []

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=base), base_url="http://b") as client:
        rps, s = await throughput(lambda: client.get("/static"), seconds)
        rows.append(("FastAPI baseline: prebuilt HTML string", rps, pct(s, 50), pct(s, 95)))

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://r") as client:
        for label, path in [
            ("Rational: static page", "/static"),
            ("Rational: interactive page (counter)", "/counter"),
            ("Rational: 100-row table page", "/table"),
        ]:
            rps, s = await throughput(lambda p=path: client.get(p), seconds)
            rows.append((label, rps, pct(s, 50), pct(s, 95)))

        page = await client.get("/counter")
        manifest = page.text.split('id="rw-manifest">')[1].split("</script>")
        import json

        m = json.loads(manifest[0])
        app.event_burst, app.event_rate = 10**9, 10**9

        async def click() -> None:
            nonlocal m
            body = {"v": 1, "page": m["page"], "rev": m["rev"], "handler": "c1.1", "payload": {}}
            r = await client.post("/_rational/event", json=body, headers={"X-RW-CSRF": m["csrf"]})
            assert r.status_code == 200, f"event failed: {r.status_code} {r.text}"
            m["rev"] = r.json()["rev"]  # feed the returned revision back: every click must succeed

        rps, s = await throughput(click, seconds)
        rows.append(("Rational: event round trip (click -> patch)", rps, pct(s, 50), pct(s, 95)))
        event_response = await client.post(
            "/_rational/event",
            json={"v": 1, "page": m["page"], "rev": m["rev"], "handler": "c1.1", "payload": {}},
            headers={"X-RW-CSRF": m["csrf"]},
        )
        assert event_response.status_code == 200, "the event response must be a successful round trip"
        table_html = (await client.get("/table")).text
        dashboard = await dashboard_html()

    # micro-benchmarks
    compiler = StyleCompiler()
    styles = [Style(padding=i, color="primary", hover=Style(color="primary_hover")) for i in range(1000)]
    start = time.perf_counter()
    for st in styles:
        compiler.compile(st)
    cold = (time.perf_counter() - start) / len(styles) * 1e6
    start = time.perf_counter()
    for _ in range(10):
        for st in styles:
            compiler.compile(st)
    warm = (time.perf_counter() - start) / (10 * len(styles)) * 1e6

    big = await render_rows(1000)

    runtime_js = app.runtime_js.encode()
    theme_css = app.theme_css.encode()

    print(f"## Benchmarks\n\n{machine()}\n")
    print("| Scenario | Requests/s (1 core) | p50 | p95 |\n|---|---:|---:|---:|")
    for label, rps, p50, p95 in rows:
        print(f"| {label} | {rps:,.0f} | {p50:.2f} ms | {p95:.2f} ms |")
    print("\n| Micro-benchmark | Result |\n|---|---:|")
    print(f"| Render + serialize a 1,000-row keyed table | {big:.1f} ms |")
    print(f"| Compile a new `Style` (cold) | {cold:.1f} µs |")
    print(f"| Compile a seen `Style` (cached) | {warm:.1f} µs |")
    print("\n| Bytes on the wire | Raw | gzip |\n|---|---:|---:|")
    for label, data in [
        ("`runtime.js` (only on interactive pages)", runtime_js),
        ("Theme CSS (cached, immutable)", theme_css),
        ("Counter event response", event_response.content),
        ("100-row table page HTML (incl. inline CSS)", table_html.encode()),
        ("Dashboard example page HTML", dashboard),
    ]:
        print(f"| {label} | {len(data) / 1024:.1f} KiB | {len(gzip.compress(data)) / 1024:.1f} KiB |")


async def render_rows(n: int) -> float:
    app = App()
    page = Page()
    timings = []
    for _ in range(5):
        runtime = PageRuntime(page.__class__(), Context(app), StyleSheet(app.compiler))
        runtime.page.render = lambda n=n: Table(rows=n)  # type: ignore[method-assign]
        start = time.perf_counter()
        to_html(await runtime.render_page())
        timings.append(time.perf_counter() - start)
    return min(timings) * 1000


async def dashboard_html() -> bytes:
    import importlib.util

    project = ROOT / "examples" / "dashboard"
    sys.path.insert(0, str(project))  # the example is a project: app.py imports its ``dashboard`` package
    spec = importlib.util.spec_from_file_location("bench_dashboard", project / "app.py")
    module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    sys.modules[spec.name] = module  # type: ignore[union-attr]
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=module.app), base_url="http://d") as client:
        return (await client.get("/")).content


def machine() -> str:
    cpu = platform.processor() or platform.machine()
    return (
        f"Python {platform.python_version()} on {platform.system()} {platform.release()} ({cpu}); "
        f"single process, in-process ASGI, no network."
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--quick", action="store_true")
    asyncio.run(main(0.5 if parser.parse_args().quick else 3.0))
