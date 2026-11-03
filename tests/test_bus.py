"""Two workers sharing a session driver and a bus: a change on one reaches pages held by the other."""

import asyncio
import json
import os
import uuid

import fakeredis
import pytest

from rational import App, MemoryBus, PersistentSessionStore, RedisBus
from rational.sockets import Rooms
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


BUSES = ["fakeredis"]
if os.environ.get("RATIONAL_TEST_REDIS"):
    BUSES.append("real-redis")


@pytest.fixture(params=BUSES)
async def redis_bus(request):
    if request.param == "fakeredis":
        bus = RedisBus(fakeredis.FakeAsyncRedis())
    else:
        bus = RedisBus(url=os.environ["RATIONAL_TEST_REDIS"])
    yield bus
    await bus.close()


async def eventually(check, timeout=3.0):
    """Wait, without assuming how long it takes, until ``check()`` is true."""
    async with asyncio.timeout(timeout):
        while not check():
            await asyncio.sleep(0.005)


async def test_a_real_client_delivers_and_stops_after_the_last_unsubscribe(redis_bus):
    channel, got = f"test:{uuid.uuid4().hex}", []
    off = await redis_bus.subscribe(channel, got.append)
    await redis_bus.publish(channel, "one")
    await eventually(lambda: got == ["one"])

    await off()
    await off()  # twice is harmless
    reader = redis_bus._reader
    await eventually(reader.done)  # the reader ends instead of spinning: this test would hang on a busy loop
    await asyncio.wait_for(asyncio.sleep(0), 1)

    off = await redis_bus.subscribe(channel, got.append)  # a later subscribe starts a new reader
    assert redis_bus._reader is not reader
    await redis_bus.publish(channel, "two")
    await eventually(lambda: got == ["one", "two"])
    await off()


class FlakyPubSub:
    """Fails its first ``listen()``; the next one delivers a message and then waits."""

    def __init__(self):
        self.subscribed, self.listens, self.closed = [], 0, False

    async def subscribe(self, *channels):
        self.subscribed.append(channels)

    async def unsubscribe(self, *channels):
        pass

    async def listen(self):
        self.listens += 1
        if self.listens == 1:
            raise ConnectionError("redis is down")
        yield {"type": "message", "channel": b"c", "data": b"one"}
        await asyncio.Event().wait()

    async def aclose(self):
        self.closed = True


class FlakyClient:
    def __init__(self):
        self.pubsub_instance = FlakyPubSub()

    def pubsub(self):
        return self.pubsub_instance


async def test_the_reader_reconnects_after_an_error_and_close_ends_it():
    client = FlakyClient()
    bus = RedisBus(client)
    bus.reconnect_delay = 0
    got = []
    await bus.subscribe("c", got.append)
    await eventually(lambda: got == ["one"])
    assert client.pubsub_instance.subscribed == [("c",), ("c",)]  # subscribed again after reconnecting

    reader = bus._reader
    await bus.close()
    assert reader.done() and client.pubsub_instance.closed


async def test_a_failed_subscribe_leaves_nothing_behind():
    client = FlakyClient()

    async def refuse(*channels):
        raise ConnectionError("redis is down")

    good = client.pubsub_instance.subscribe
    client.pubsub_instance.subscribe = refuse
    bus = RedisBus(client)
    with pytest.raises(ConnectionError):
        await bus.subscribe("c", print)
    assert bus._callbacks == {} and bus._reader is None
    client.pubsub_instance.subscribe = good
    await bus.subscribe("c", print)  # the next attempt subscribes for real
    assert client.pubsub_instance.subscribed == [("c",)]
    await bus.close()


async def test_close_closes_only_a_client_the_bus_made_itself(monkeypatch):
    class Client:
        closed = False

        async def aclose(self):
            self.closed = True

    client = Client()
    monkeypatch.setattr("redis.asyncio.Redis.from_url", lambda url: client)
    await RedisBus(url="redis://x").close()
    assert client.closed

    theirs = Client()
    await RedisBus(theirs).close()
    assert not theirs.closed


class CountingBus(MemoryBus):
    """Takes its time to subscribe, so that joins can overlap."""

    def __init__(self):
        super().__init__()
        self.subscribes, self.unsubscribes = 0, 0
        self.gate = asyncio.Event()

    async def subscribe(self, channel, callback):
        self.subscribes += 1
        await self.gate.wait()
        unsubscribe = await super().subscribe(channel, callback)

        async def counted():
            self.unsubscribes += 1
            await unsubscribe()

        return counted


async def test_joins_at_the_same_time_subscribe_once():
    bus = CountingBus()
    rooms = Rooms(App(bus=bus))
    a, b = object(), object()
    joins = [asyncio.create_task(rooms.join("r", a)), asyncio.create_task(rooms.join("r", b))]
    await asyncio.sleep(0)
    bus.gate.set()
    await asyncio.gather(*joins)
    assert bus.subscribes == 1 and rooms.count("r") == 2


async def test_leaving_while_the_subscribe_is_running_undoes_it():
    bus = CountingBus()
    rooms = Rooms(App(bus=bus))
    member = object()
    join = asyncio.create_task(rooms.join("r", member))
    await asyncio.sleep(0)
    await rooms.leave("r", member)  # nothing to unsubscribe from yet
    bus.gate.set()
    await join
    assert bus.unsubscribes == 1 and rooms._unsubscribe == {}


async def test_a_failed_join_lets_the_next_one_try_again():
    class Refusing(MemoryBus):
        fail = True

        async def subscribe(self, channel, callback):
            if self.fail:
                raise ConnectionError("down")
            return await super().subscribe(channel, callback)

    bus = Refusing()
    rooms = Rooms(App(bus=bus))
    with pytest.raises(ConnectionError):
        await rooms.join("r", object())
    assert rooms._unsubscribe == {}
    bus.fail = False
    await rooms.join("r", object())
    assert callable(rooms._unsubscribe["r"])
