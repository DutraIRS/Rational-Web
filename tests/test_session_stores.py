import pytest

from rational import App
from rational.backend import Service, remote
from rational.session import Session
from rational.stores import (
    MemorySessionDriver,
    PersistentSessionStore,
    RedisSessionDriver,
    json_serialize,
)
from rational.testing import TestClient


def worker(driver):
    """One 'worker': its own App and local cache, sharing the driver with the others."""
    app = App(session_store=PersistentSessionStore(driver))

    @app.service
    class AccountService(Service):
        @remote()
        def login(self, name: str) -> str:
            self.context.session.login(name)
            return name

        @remote()
        def logout(self) -> None:
            self.context.session.logout()

        @remote()
        def put(self, value: str) -> None:
            self.context.session["note"] = value

        @remote(method="GET")
        def whoami(self) -> dict:
            session = self.context.session
            return {"user": session.user, "note": session.get("note")}

    return app, TestClient(app)


def sid_of(response):
    return response.headers["set-cookie"].split(";", 1)[0].split("=", 1)[1]


def call(client, path, sid=None, csrf=None, **json):
    headers = {}
    if sid:
        headers["Cookie"] = f"rw_sid={sid}"
    if csrf:
        headers["X-RW-CSRF"] = csrf
    if json or path.endswith(("login", "logout", "put")):
        return client.http.post(f"/api/account/{path}", json=json, headers=headers)
    return client.http.get(f"/api/account/{path}", headers=headers)


def test_login_on_one_worker_is_seen_by_another():
    driver = MemorySessionDriver()
    app_a, a = worker(driver)
    app_b, b = worker(driver)

    sid = sid_of(call(a, "login", name="ada"))

    assert call(b, "whoami", sid).json() == {"user": "ada", "note": None}
    assert app_b.sessions.get(sid) is not None  # now cached locally on worker B


def test_changes_on_one_worker_reach_a_warm_cache_on_another():
    driver = MemorySessionDriver()
    _, a = worker(driver)
    _, b = worker(driver)
    sid = sid_of(call(a, "login", name="ada"))
    assert call(b, "whoami", sid).json()["note"] is None

    csrf = driver_csrf(driver, sid)
    assert call(a, "put", sid, csrf, value="hello").status_code == 200

    assert call(b, "whoami", sid).json()["note"] == "hello"


def driver_csrf(driver, sid):
    import json

    return json.loads(driver._items[f"rational:session:{sid}"][1])["csrf"]


def test_login_rotation_removes_the_old_record():
    driver = MemorySessionDriver()
    _, a = worker(driver)
    first = sid_of(call(a, "whoami"))  # an anonymous session
    assert len(driver) == 1

    response = call(a, "login", first, driver_csrf(driver, first), name="ada")
    new = sid_of(response)

    assert new != first and len(driver) == 1
    assert f"rational:session:{first}" not in driver._items
    assert call(a, "whoami", first).json()["user"] is None


def test_logout_on_one_worker_ends_the_session_on_another():
    driver = MemorySessionDriver()
    _, a = worker(driver)
    _, b = worker(driver)
    sid = sid_of(call(a, "login", name="ada"))
    assert call(b, "whoami", sid).json()["user"] == "ada"  # warm on B

    call(a, "logout", sid, driver_csrf(driver, sid))

    assert call(b, "whoami", sid).json()["user"] is None


def test_unreadable_records_are_discarded():
    import asyncio

    driver = MemorySessionDriver()
    store = PersistentSessionStore(driver)
    asyncio.run(driver.set("rational:session:bad", b"\xff not json", 60))
    assert asyncio.run(store.load("bad")) is None


def test_unserializable_session_data_fails_loudly():
    import asyncio

    store = PersistentSessionStore(MemorySessionDriver())
    session = store.create()
    session["bad"] = {1, 2}
    with pytest.raises(TypeError, match="JSON-serializable"):
        asyncio.run(store.save(session))
    with pytest.raises(TypeError):
        json_serialize({"data": object()})


def test_unchanged_sessions_are_not_rewritten():
    import asyncio

    class Counting(MemorySessionDriver):
        writes = 0

        async def _count(self):
            type(self).writes += 1

        async def set(self, key, value, ttl):
            await self._count()
            await super().set(key, value, ttl)

        async def cas(self, key, expected, value, ttl):
            await self._count()
            return await super().cas(key, expected, value, ttl)

    store = PersistentSessionStore(Counting())
    session = store.create()
    asyncio.run(store.save(session))
    asyncio.run(store.save(session))
    session["a"] = 1
    asyncio.run(store.save(session))
    assert Counting.writes == 2


class FakeRedis:
    """The few redis.asyncio calls the driver makes. Like redis-py, it refuses ``None`` arguments."""

    def __init__(self):
        self.data, self.ttls = {}, {}

    async def get(self, key):
        return self.data.get(key)

    async def set(self, key, value, ex=None):
        self.data[key], self.ttls[key] = value, ex

    async def expire(self, key, ttl):
        self.ttls[key] = ttl

    async def delete(self, key):
        self.data.pop(key, None)

    async def eval(self, script, numkeys, *args):
        assert numkeys == 1 and all(isinstance(a, (str, bytes, int)) for a in args), args
        key, expect_present, expected, ttl, value = args
        if self.data.get(key) != (expected if expect_present == "1" else None):
            return 0
        await self.set(key, value, ex=ttl)
        return 1


async def test_redis_driver_uses_get_set_expire_delete():
    client = FakeRedis()
    driver = RedisSessionDriver(client)
    await driver.set("k", b"v", 30)
    assert await driver.get("k") == b"v" and client.ttls["k"] == 30
    await driver.touch("k", 60)
    assert client.ttls["k"] == 60
    await driver.delete("k")
    assert await driver.get("k") is None
    with pytest.raises(ValueError):
        RedisSessionDriver()


async def test_redis_driver_compare_and_swap():
    driver = RedisSessionDriver(FakeRedis())
    assert await driver.cas("k", None, b"1", 30)  # absent, as expected
    assert not await driver.cas("k", None, b"2", 30)  # no longer absent
    assert not await driver.cas("k", b"0", b"2", 30)
    assert await driver.cas("k", b"1", b"2", 30)
    assert await driver.get("k") == b"2"


async def test_a_persistent_store_works_over_redis():
    driver = RedisSessionDriver(FakeRedis())
    a, b = PersistentSessionStore(driver), PersistentSessionStore(driver)
    session = a.create()
    session["n"] = 1
    await a.save(session)
    assert (await b.load(session.id))["n"] == 1


def test_default_store_is_unchanged():
    app = App()
    session = app.sessions.create()
    assert isinstance(session, Session)
    import asyncio

    assert asyncio.run(app.sessions.load(session.id)) is session


# -- concurrent workers -------------------------------------------------------------------------


async def two_workers(**data):
    """Workers A and B holding the same stored session (with ``data``), as two processes would."""
    driver = MemorySessionDriver()
    a, b = PersistentSessionStore(driver), PersistentSessionStore(driver)
    sa = a.create()
    sa.update(data)
    await a.save(sa)
    sb = await b.load(sa.id)
    return driver, a, b, sa, sb


def stored(driver, session):
    import json

    return json.loads(driver._items[f"rational:session:{session.id}"][1])


async def test_concurrent_changes_to_different_keys_are_both_kept():
    driver, a, b, sa, sb = await two_workers(cart=[], theme="light")
    sa["cart"] = [1]
    sb["theme"] = "dark"
    await a.save(sa)
    await b.save(sb)  # conflicts with A's write: merged, not overwritten

    assert stored(driver, sb)["data"] == {"cart": [1], "theme": "dark"}
    assert dict(sb) == {"cart": [1], "theme": "dark"}  # B's copy has A's change now
    assert (await a.load(sa.id))["theme"] == "dark"


async def test_a_concurrent_delete_is_merged():
    driver, a, b, sa, sb = await two_workers(flash="saved", theme="light")
    del sa["flash"]
    sb["theme"] = "dark"
    await a.save(sa)
    await b.save(sb)
    assert stored(driver, sb)["data"] == {"theme": "dark"}


async def test_session_state_values_merge_too():
    driver, a, b, sa, sb = await two_workers()
    sa.state["app.Cart.items"] = [1]
    sa.bump()
    sb.state["app.Prefs.dense"] = True
    sb.state["app.Local.handle"] = handle = object()  # not JSON: stays on worker B only
    sb.bump()
    await a.save(sa)
    await b.save(sb)
    assert stored(driver, sb)["state"] == {"app.Cart.items": [1], "app.Prefs.dense": True}
    assert sb.state["app.Local.handle"] is handle


async def test_loading_merges_newer_data_without_losing_unsaved_changes():
    _, a, b, sa, sb = await two_workers(x=0, y=0)
    sb["y"] = "unsaved"  # a change on B that a failed save left unwritten
    sa["x"] = 1
    await a.save(sa)
    assert await b.load(sb.id) is sb
    assert dict(sb) == {"x": 1, "y": "unsaved"}


async def test_a_stale_read_never_rolls_a_session_back():
    driver, _, b, sa, sb = await two_workers(x=0)
    old = driver._items[f"rational:session:{sa.id}"][1]
    sb["x"] = 1
    await b.save(sb)

    class Stale(MemorySessionDriver):
        async def get(self, key):
            return old  # a read that was issued before B's write

    b.driver = Stale()
    assert (await b.load(sb.id))["x"] == 1


async def test_two_loads_of_one_id_share_one_session():
    import asyncio

    driver, _, _, sa, _ = await two_workers(x=0)
    c = PersistentSessionStore(driver)
    first, second = await asyncio.gather(c.load(sa.id), c.load(sa.id))
    assert first is second is c.get(sa.id)


async def test_a_load_waiting_for_a_logout_does_not_revive_the_old_id():
    import asyncio

    driver, a, _, sa, _ = await two_workers(x=0)
    old_id = sa.id
    newer = b'{"n":9,"csrf":"c","data":{"x":2},"state":{}}'  # written by another worker meanwhile
    await driver.set(f"rational:session:{old_id}", newer, 60)

    async with sa.lock:  # a request on this worker holds the session and logs out
        loading = asyncio.ensure_future(a.load(old_id))
        await asyncio.sleep(0)
        sa.logout()
        await a.rotate(sa)
        await a.save(sa)

    assert await loading is None
    assert a.get(old_id) is None and await driver.get(f"rational:session:{old_id}") is None


async def test_unchanged_sessions_renew_their_expiry_at_most_every_quarter_ttl():
    class Touches(MemorySessionDriver):
        touched = 0

        async def touch(self, key, ttl):
            type(self).touched += 1

    store = PersistentSessionStore(Touches(), ttl=400)
    session = store.create()
    await store.save(session)  # the write itself sets the expiry
    await store.save(session)
    assert Touches.touched == 0
    session.touched_at -= 101
    await store.save(session)
    assert Touches.touched == 1


async def test_endless_conflicts_give_up_and_keep_the_change_for_next_time(caplog):
    class Busy(MemorySessionDriver):
        """Another worker writes the record between every read and every write."""

        n = 1

        async def cas(self, key, expected, value, ttl):
            type(self).n += 1
            await self.set(key, b'{"n":%d,"csrf":"c","data":{},"state":{}}' % self.n, ttl)
            return False

    store = PersistentSessionStore(Busy())
    session = store.create()
    session["x"] = 1
    await store.save(session)
    assert "will retry next time" in caplog.text
    assert session.saved_revision != session.revision and session["x"] == 1
