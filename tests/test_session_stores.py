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

        async def set(self, key, value, ttl):
            type(self).writes += 1
            await super().set(key, value, ttl)

    store = PersistentSessionStore(Counting())
    session = store.create()
    asyncio.run(store.save(session))
    asyncio.run(store.save(session))
    session["a"] = 1
    asyncio.run(store.save(session))
    assert Counting.writes == 2


def test_redis_driver_uses_get_set_expire_delete():
    import asyncio

    class FakeRedis:
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

    client = FakeRedis()
    driver = RedisSessionDriver(client)

    async def run():
        await driver.set("k", b"v", 30)
        assert await driver.get("k") == b"v" and client.ttls["k"] == 30
        await driver.touch("k", 60)
        assert client.ttls["k"] == 60
        await driver.delete("k")
        assert await driver.get("k") is None

    asyncio.run(run())
    with pytest.raises(ValueError):
        RedisSessionDriver()


def test_default_store_is_unchanged():
    app = App()
    session = app.sessions.create()
    assert isinstance(session, Session)
    import asyncio

    assert asyncio.run(app.sessions.load(session.id)) is session
