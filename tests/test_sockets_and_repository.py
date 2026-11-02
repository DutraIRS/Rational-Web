"""WebSocket classes with rooms, and the typed repository."""

import asyncio

import pytest
from pydantic import BaseModel
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from starlette.testclient import TestClient as StarletteClient
from starlette.websockets import WebSocketDisconnect

from rational import App, FieldError, Forbidden, MemoryBus, Page, PersistentSessionStore, Router, Socket, Text
from rational.backend.database import Database, Repository
from rational.stores import MemorySessionDriver

ORIGIN = {"origin": "http://testserver"}


class Say(BaseModel):
    text: str


class Chat(Socket):
    async def connect(self) -> None:
        await self.join("lobby")
        await self.send({"hello": self.app.rooms.count("lobby")})

    async def receive(self, message: Say) -> None:
        if message.text == "bad":
            raise FieldError("text", "Not that word")
        await self.publish("lobby", {"said": message.text})


class Private(Socket):
    auth = "required"


def chat_app(bus=None):
    app = App(bus=bus)
    app.socket("/ws/chat")(Chat)
    app.socket("/ws/private")(Private)
    return app


def test_messages_are_validated_and_published_to_the_room():
    client = StarletteClient(chat_app())
    with (
        client.websocket_connect("/ws/chat", headers=ORIGIN) as a,
        client.websocket_connect("/ws/chat", headers=ORIGIN) as b,
    ):
        assert a.receive_json() == {"hello": 1} and b.receive_json() == {"hello": 2}
        a.send_json({"text": "hi"})
        assert a.receive_json() == {"said": "hi"} and b.receive_json() == {"said": "hi"}
        a.send_json({"nope": 1})
        assert a.receive_json()["error"]["code"] == "bad_message"
        a.send_text("{not json")
        assert a.receive_json()["error"]["code"] == "bad_message"
        a.send_json({"text": "bad"})
        assert a.receive_json()["error"]["details"] == [{"field": "text", "message": "Not that word"}]
        a.send_json({"text": "x" * (70 * 1024)})
        assert a.receive_json()["error"]["code"] == "too_large"


def test_connections_from_other_sites_and_anonymous_visitors_are_refused():
    client = StarletteClient(chat_app())
    for headers in ({}, {"origin": "https://evil.example"}):
        with pytest.raises(WebSocketDisconnect), client.websocket_connect("/ws/chat", headers=headers) as ws:
            ws.receive_json()
    with pytest.raises(WebSocketDisconnect), client.websocket_connect("/ws/private", headers=ORIGIN) as ws:
        ws.receive_json()


def test_floods_are_rate_limited():
    class Strict(Chat):
        burst, rate = 2, 0.001

    app = App()
    app.socket("/ws/strict")(Strict)
    with StarletteClient(app).websocket_connect("/ws/strict", headers=ORIGIN) as ws:
        ws.receive_json()
        for _ in range(3):
            ws.send_json({"text": "x"})
        replies = [ws.receive_json() for _ in range(3)]
        assert replies[-1]["error"]["code"] == "rate_limited"


def test_rooms_reach_other_workers_through_the_bus():
    bus = MemoryBus()
    one, two = StarletteClient(chat_app(bus)), StarletteClient(chat_app(bus))
    with one.websocket_connect("/ws/chat", headers=ORIGIN) as a, two.websocket_connect("/ws/chat", headers=ORIGIN) as b:
        a.receive_json(), b.receive_json()
        a.send_json({"text": "across"})
        assert a.receive_json() == {"said": "across"}
        assert b.receive_json() == {"said": "across"}  # delivered by the other worker


def test_binary_frames_are_refused_without_ending_the_connection():
    with StarletteClient(chat_app()).websocket_connect("/ws/chat", headers=ORIGIN) as ws:
        ws.receive_json()
        ws.send_bytes(b"\x00\x01")
        assert ws.receive_json()["error"]["code"] == "bad_message"
        ws.send_json({"text": "still here"})
        assert ws.receive_json() == {"said": "still here"}


def test_an_origin_that_is_not_a_url_is_refused():
    client = StarletteClient(chat_app())
    with pytest.raises(WebSocketDisconnect), client.websocket_connect("/ws/chat", headers={"origin": "http://[bad"}):
        pass


def test_what_was_sent_arrives_before_a_server_side_close():
    class Refuses(Socket):
        async def connect(self) -> None:
            await self.send({"reason": "no room"})
            raise Forbidden("Full")

    app = App()
    app.socket("/ws/full")(Refuses)
    with StarletteClient(app).websocket_connect("/ws/full", headers=ORIGIN) as ws:
        assert ws.receive_json() == {"reason": "no room"}
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_json()
    assert closed.value.code == 1008


class StuckSocket:
    """A client that stopped reading: sends block, closes are recorded."""

    def __init__(self):
        self.closed = None
        self.never = asyncio.Event()

    async def send_text(self, text):
        await self.never.wait()

    async def close(self, code):
        self.closed = code


async def test_a_client_that_stops_reading_is_disconnected_without_holding_up_the_others(monkeypatch):
    monkeypatch.setattr("rational.sockets.FLUSH_SECONDS", 0)

    class Small(Socket):
        queue_size = 2

    app = App()
    stuck = Small(app, StuckSocket(), app)
    writer = asyncio.create_task(stuck._write())
    await app.rooms.join("r", stuck)
    healthy = Socket(app, StuckSocket(), app)
    await app.rooms.join("r", healthy)

    for n in range(4):  # the writer takes one; then the queue of 2 fills up
        await app.rooms.publish("r", {"n": n})  # never waits for any client
        await asyncio.sleep(0)
    assert stuck._closing and not healthy._closing

    await asyncio.gather(*app._tasks)
    assert stuck.websocket.closed == 1013
    await stuck.send({"after": "closing"})  # dropped, not queued without end
    assert stuck._outbox.qsize() <= 2
    writer.cancel()


def signed_in_app(**kwargs):
    class Private(Socket):
        auth = "required"

        async def receive(self, message) -> None:
            await self.send({"user": self.user})

    app = App(**kwargs)
    app.socket("/ws/private")(Private)

    @app.page("/login")
    class Login(Page):
        def mount(self):
            self.context.session.login("ada")

        def render(self):
            return Text("in")

    @app.page("/logout")
    class Logout(Page):
        def mount(self):
            self.context.session.logout()

        def render(self):
            return Text("out")

    return app


def test_signing_out_ends_the_connections_of_that_session():
    with StarletteClient(signed_in_app()) as client:
        client.get("/login")
        with client.websocket_connect("/ws/private", headers=ORIGIN) as ws:
            ws.send_json("hi")
            assert ws.receive_json() == {"user": "ada"}
            client.get("/logout")
            with pytest.raises(WebSocketDisconnect) as closed:
                ws.receive_json()
    assert closed.value.code == 1008


def test_a_session_ended_on_another_worker_ends_the_connection_here():
    driver = MemorySessionDriver()
    here = signed_in_app(session_store=PersistentSessionStore(driver))
    there = signed_in_app(session_store=PersistentSessionStore(driver))
    with StarletteClient(here) as client, StarletteClient(there) as other:
        client.get("/login")
        other.cookies.set("rw_sid", client.cookies["rw_sid"])
        with client.websocket_connect("/ws/private", headers=ORIGIN) as ws:
            ws.send_json("hi")
            assert ws.receive_json() == {"user": "ada"}
            other.get("/logout")  # no bus: nothing tells this worker
            ws.send_json("still me?")  # the message that would act as the signed-in user
            with pytest.raises(WebSocketDisconnect) as closed:
                ws.receive_json()
    assert closed.value.code == 1008


def test_a_quiet_connection_is_checked_again_after_a_while(monkeypatch):
    monkeypatch.setattr(Socket, "recheck_seconds", 0.01)
    driver = MemorySessionDriver()
    here = signed_in_app(session_store=PersistentSessionStore(driver))
    there = signed_in_app(session_store=PersistentSessionStore(driver))
    with StarletteClient(here) as client, StarletteClient(there) as other:
        client.get("/login")
        other.cookies.set("rw_sid", client.cookies["rw_sid"])
        with client.websocket_connect("/ws/private", headers=ORIGIN) as ws:
            ws.send_json("hi")
            ws.receive_json()
            other.get("/logout")
            with pytest.raises(WebSocketDisconnect) as closed:  # it sent nothing: the timer found out
                ws.receive_json()
    assert closed.value.code == 1008


def test_a_failing_bus_does_not_stop_a_connection_from_closing():
    class Broken(MemoryBus):
        async def subscribe(self, channel, callback):
            async def off():
                raise ConnectionError("down")

            return off

    left = []

    class Leaves(Socket):
        async def connect(self) -> None:
            await self.join("r")

        async def disconnect(self) -> None:
            left.append(True)

    app = App(bus=Broken())
    app.socket("/ws")(Leaves)
    with StarletteClient(app).websocket_connect("/ws", headers=ORIGIN):
        pass
    assert left == [True]


def test_routers_record_sockets_and_shutdown_hooks():
    events = []
    inner = Router(prefix="/live")

    @inner.socket("/chat")
    class Hello(Socket):
        async def connect(self) -> None:
            await self.send({"hello": True})

    inner.on_shutdown(lambda: events.append("stopped"))
    outer = Router(prefix="/v1")
    outer.include(inner)
    app = App()
    app.include(outer)
    with StarletteClient(app) as client, client.websocket_connect("/v1/live/chat", headers=ORIGIN) as ws:
        assert ws.receive_json() == {"hello": True}
    assert events == ["stopped"]


def test_a_socket_route_needs_a_socket_class():
    with pytest.raises(TypeError, match="Socket subclasses"):
        App().socket("/ws")(object)


class Base(DeclarativeBase):
    pass


class Note(Base):
    __tablename__ = "notes"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str]
    stars: Mapped[int] = mapped_column(default=0)


def test_repository_crud_and_pages(tmp_path):
    async def run():
        db = Database(f"sqlite+aiosqlite:///{(tmp_path / 'notes.db').as_posix()}", metadata=Base.metadata)
        await db.create_all()
        notes = Repository(db, Note)
        first = await notes.add(title="a", stars=1)
        for i in range(24):
            await notes.add(title=f"n{i}", stars=i % 3)
        assert (await notes.get(first.id)).title == "a" and await notes.get(999) is None
        assert await notes.count() == 25 and await notes.count(Note.stars == 0) == 8
        page = await notes.page(page=3, size=10, order_by=Note.id)
        assert [n.title for n in page.items] == [f"n{i}" for i in range(19, 24)] and page.pages == 3
        assert (await notes.update(first.id, title="A")).title == "A" and await notes.update(999, title="x") is None
        with pytest.raises(AttributeError, match="no column"):
            await notes.update(first.id, nope=1)
        assert await notes.delete(first.id) and not await notes.delete(first.id)
        assert [n.title for n in await notes.find(Note.stars == 2, order_by=Note.id, limit=2)] == ["n2", "n5"]
        assert [n.title for n in (await notes.page(page=1, size=2)).items] == ["n0", "n1"]  # by key unless told
        with pytest.raises(ValueError):
            await notes.page(page=0)
        await db.dispose()

    asyncio.run(run())
