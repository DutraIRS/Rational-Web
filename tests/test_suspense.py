import asyncio

from rational import App, Page, Skeleton, Suspense, Text

from .test_push import Raw


def make_app(load, **options):
    app = App(**options)

    @app.page("/")
    class Home(Page):
        def render(self):
            return Suspense(load=load, fallback=Skeleton(height="3rem"), error=Text("Oops"))

    return app


async def test_page_responds_with_the_fallback_then_pushes_the_content():
    gate = asyncio.Event()

    async def load():
        await gate.wait()
        return Text("Loaded report")

    raw = Raw(make_app(load))
    manifest, html = await raw.open_page()
    assert "rw-skeleton" in html and 'aria-busy="true"' in html and "Loaded report" not in html
    assert manifest["stream"]

    stream = raw.stream(manifest)
    assert await stream.next() == {"hello": 0}
    gate.set()
    batch = await stream.until("Loaded report")
    assert batch["patches"][0]["op"] in ("edit", "morph")
    await stream.close()


async def test_changes_before_the_stream_connects_are_delivered_on_connect():
    async def load():
        return Text("Instant")

    raw = Raw(make_app(load))
    manifest, _ = await raw.open_page()
    await asyncio.sleep(0.05)  # the task finished before anyone listened
    stream = raw.stream(manifest)
    await stream.next()
    await stream.until("Instant")
    await stream.close()


async def test_failures_show_the_error_content():
    def load():
        raise RuntimeError("boom")

    raw = Raw(make_app(load))
    manifest, _ = await raw.open_page()
    stream = raw.stream(manifest)
    await stream.next()
    await stream.until("Oops")
    await stream.close()
