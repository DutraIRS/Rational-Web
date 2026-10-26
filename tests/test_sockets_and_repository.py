"""WebSocket classes with rooms, and the typed repository."""

import asyncio

import pytest
from pydantic import BaseModel
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from starlette.testclient import TestClient as StarletteClient
from starlette.websockets import WebSocketDisconnect

from rational import App, FieldError, MemoryBus, Socket
from rational.backend.database import Database, Repository

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
        with pytest.raises(ValueError):
            await notes.page(page=0)
        await db.dispose()

    asyncio.run(run())
