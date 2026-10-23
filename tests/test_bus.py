"""Two workers sharing a session driver and a bus: a change on one reaches pages held by the other."""

import asyncio
import json

from rational import MemoryBus, PersistentSessionStore
from rational.stores import MemorySessionDriver

from .test_live_session import handler_of, make_app
from .test_push import Raw


def worker(driver, bus):
    return make_app(live_session=True, session_store=PersistentSessionStore(driver), bus=bus)


async def test_session_change_on_one_worker_updates_a_page_on_another():
    driver, bus = MemorySessionDriver(), MemoryBus()
    a, b = worker(driver, bus), worker(driver, bus)

    one = Raw(a)
    m1, html1 = await one.open_page()
    two = Raw(b)
    two.cookie = one.cookie
    m2, _html2 = await two.open_page()
    stream = two.stream(m2)
    assert await stream.next() == {"hello": 0}
    await asyncio.sleep(0.05)  # let worker B finish subscribing

    status, data = await one.event(m1, handler_of(html1))
    assert status == 200 and "Items: 1" in json.dumps(data["patches"])

    batch = await stream.until("Items: 1", timeout=3)
    assert batch["seq"] > 0
    await stream.close()


async def test_without_a_bus_the_other_worker_is_not_told():
    driver = MemorySessionDriver()
    a = make_app(live_session=True, session_store=PersistentSessionStore(driver))
    b = make_app(live_session=True, session_store=PersistentSessionStore(driver))
    one = Raw(a)
    m1, html1 = await one.open_page()
    two = Raw(b)
    two.cookie = one.cookie
    m2, _ = await two.open_page()
    stream = two.stream(m2)
    await stream.next()
    await one.event(m1, handler_of(html1))
    try:
        frame = await stream.next(timeout=0.4)
    except TimeoutError:
        frame = None
    assert frame is None
    await stream.close()


class FakePubSub:
    def __init__(self, hub):
        self.hub, self.channels, self.queue = hub, set(), asyncio.Queue()
        hub.append(self)

    async def subscribe(self, channel):
        self.channels.add(channel)

    async def unsubscribe(self, channel):
        self.channels.discard(channel)

    async def listen(self):
        while True:
            yield await self.queue.get()

    async def aclose(self):
        pass


class FakeRedis:
    def __init__(self):
        self.hub = []

    def pubsub(self):
        return FakePubSub(self.hub)

    async def publish(self, channel, message):
        for ps in self.hub:
            if channel in ps.channels:
                await ps.queue.put({"type": "message", "channel": channel.encode(), "data": message.encode()})


async def test_redis_bus_delivers_to_subscribers_until_they_unsubscribe():
    from rational import RedisBus

    bus = RedisBus(FakeRedis())
    got = []
    off = await bus.subscribe("c", got.append)
    await bus.publish("c", "one")
    await bus.publish("other", "ignored")
    await asyncio.sleep(0.05)
    assert got == ["one"]
    await off()
    await bus.publish("c", "two")
    await asyncio.sleep(0.05)
    assert got == ["one"]
    await bus.close()


async def test_memory_bus_isolates_a_failing_subscriber():
    bus = MemoryBus()
    got = []

    def bad(_):
        raise RuntimeError("boom")

    await bus.subscribe("c", bad)
    await bus.subscribe("c", got.append)
    await bus.publish("c", "x")
    assert got == ["x"]
