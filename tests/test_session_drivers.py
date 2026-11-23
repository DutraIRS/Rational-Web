"""What every session driver must do, run against each: memory, Redis and SQL.

Redis runs on fakeredis (with its Lua engine) and SQL on SQLite. Set ``RATIONAL_TEST_REDIS`` and
``RATIONAL_TEST_POSTGRES`` to URLs to run the same tests against real servers (CI does).
"""

import asyncio
import os
import uuid

import fakeredis
import pytest

from rational.backend.database import Database
from rational.stores import MemorySessionDriver, RedisSessionDriver, SQLSessionDriver
from tests.test_session_stores import call, sid_of, worker

BACKENDS = ["memory", "redis", "sqlite"]
if os.environ.get("RATIONAL_TEST_REDIS"):
    BACKENDS.append("real-redis")
if os.environ.get("RATIONAL_TEST_POSTGRES"):
    BACKENDS.append("postgres")


@pytest.fixture(params=BACKENDS)
async def driver(request, tmp_path):
    kind = request.param
    if kind == "memory":
        yield MemorySessionDriver()
    elif kind == "redis":
        yield RedisSessionDriver(fakeredis.FakeAsyncRedis())
    elif kind == "real-redis":
        driver = RedisSessionDriver(url=os.environ["RATIONAL_TEST_REDIS"])
        yield driver
        await driver.client.aclose()
    else:
        url = os.environ["RATIONAL_TEST_POSTGRES"] if kind == "postgres" else f"sqlite+aiosqlite:///{tmp_path / 's.db'}"
        db = Database(url)
        yield SQLSessionDriver(db, table=f"sessions_{uuid.uuid4().hex[:8]}")  # a table per test
        await db.dispose()


def key():
    return f"test:{uuid.uuid4().hex}"  # unique, so tests on a shared real server never collide


async def test_values_expire_and_can_be_touched_and_deleted(driver):
    k = key()
    assert await driver.get(k) is None
    await driver.set(k, b"one", ttl=60)
    await driver.set(k, b"two", ttl=60)  # an overwrite
    assert await driver.get(k) == b"two"
    await driver.touch(k, ttl=60)
    assert await driver.get(k) == b"two"
    await driver.delete(k)
    assert await driver.get(k) is None
    await driver.set(k, b"brief", ttl=1)
    await asyncio.sleep(1.1)
    assert await driver.get(k) is None


async def test_compare_and_swap(driver):
    k = key()
    assert await driver.cas(k, None, b"v1", ttl=60)  # absent: created
    assert not await driver.cas(k, None, b"v1b", ttl=60)  # present: refused
    assert not await driver.cas(k, b"stale", b"v2", ttl=60)  # someone else wrote first
    assert await driver.cas(k, b"v1", b"v2", ttl=60)
    assert await driver.get(k) == b"v2"
    await driver.set(k, b"brief", ttl=1)
    await asyncio.sleep(1.1)
    assert await driver.cas(k, None, b"fresh", ttl=60)  # an expired value counts as absent
    assert await driver.get(k) == b"fresh"


async def test_concurrent_swaps_lose_no_update(driver):
    k = key()

    async def increment():
        while True:
            raw = await driver.get(k)
            if await driver.cas(k, raw, str(int(raw or 0) + 1).encode(), ttl=60):
                return

    await asyncio.gather(*(increment() for _ in range(20)))
    assert await driver.get(k) == b"20"


async def test_two_workers_share_sessions_through_sql(tmp_path):
    db = Database(f"sqlite+aiosqlite:///{tmp_path / 'shared.db'}")
    driver = SQLSessionDriver(db)
    (_, one), (_, two) = worker(driver), worker(driver)
    login = call(one, "login", name="ada")
    sid = sid_of(login)
    assert call(two, "whoami", sid=sid).json()["user"] == "ada"  # signed in on one, known on the other
    await db.dispose()


def test_pooled_sql_connections_are_checked_before_use():
    # After the database restarts, a pooled connection it closed must be replaced, not used (that answered 500).
    assert Database("sqlite+aiosqlite:///:memory:").engine.pool._pre_ping is True
    assert Database("sqlite+aiosqlite:///:memory:", pool_pre_ping=False).engine.pool._pre_ping is False
    assert not getattr(Database("sqlite+aiosqlite:///:memory:", serverless=True).engine.pool, "_pre_ping", False)


def test_redis_clients_from_a_url_check_connections_before_use():
    # redis-py 7+ skips its check of a pooled connection while "maintenance notifications" are on (the default).
    pytest.importorskip("redis")
    from rational.bus import RedisBus
    from rational.jobs import RedisJobStore

    try:
        from redis.maint_notifications import MaintNotificationsConfig  # noqa: F401
    except ImportError:
        pytest.skip("redis-py before 7 always checks")
    url = "redis://127.0.0.1:1/0"  # never connected to here
    for client in (RedisSessionDriver(url=url).client, RedisJobStore(url=url).client, RedisBus(url=url).client):
        assert not client.connection_pool.maint_notifications_enabled()
