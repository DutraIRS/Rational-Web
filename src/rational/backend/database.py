"""SQLAlchemy integration: an async engine plus request-scoped sessions.

SQLAlchemy stays the source of truth for ORM semantics; this module only
creates the engine and hands out sessions. Use Alembic for migrations;
``create_all()`` is a development convenience.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

try:
    from sqlalchemy import MetaData, func, select
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from sqlalchemy.orm import DeclarativeBase
    from sqlalchemy.pool import NullPool
except ImportError as exc:  # pragma: no cover
    raise ImportError("database support needs SQLAlchemy: pip install 'rational[db]'") from exc


class Model(DeclarativeBase):
    """Optional declarative base. Any SQLAlchemy declarative base works with ``Database``."""


class Database:
    def __init__(
        self,
        url: str,
        *,
        echo: bool = False,
        metadata: MetaData | None = None,
        serverless: bool = False,
        **engine_options: Any,
    ) -> None:
        self.url = url
        self.metadata = metadata if metadata is not None else Model.metadata
        if serverless:
            # No pooled connections held between invocations; each use opens and closes its own.
            engine_options.setdefault("poolclass", NullPool)
        self.engine = create_async_engine(url, echo=echo, **engine_options)
        self.sessionmaker = async_sessionmaker(self.engine, expire_on_commit=False)

    def session(self) -> AsyncSession:
        """``async with db.session() as session: ...`` — commit explicitly."""
        return self.sessionmaker()

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[AsyncSession]:
        """A session inside a transaction: commits on success, rolls back on error."""
        async with self.sessionmaker() as session, session.begin():
            yield session

    async def create_all(self, base: type[DeclarativeBase] | None = None) -> None:
        metadata = base.metadata if base is not None else self.metadata
        async with self.engine.begin() as conn:
            await conn.run_sync(metadata.create_all)

    async def upgrade(self, directory: str = "migrations", revision: str = "head") -> None:
        """Apply Alembic migrations (``pip install "rational[migrations]"``); see :mod:`rational.backend.migrations`."""
        import asyncio

        from . import migrations

        await asyncio.to_thread(migrations.upgrade, self, directory, revision)

    async def dispose(self) -> None:
        await self.engine.dispose()


M = TypeVar("M")


@dataclass(frozen=True)
class Paged(Generic[M]):
    """One page of results: ``items``, plus where it sits in the whole."""

    items: list[M]
    total: int
    page: int
    size: int

    @property
    def pages(self) -> int:
        return max(1, -(-self.total // self.size))


class Repository(Generic[M]):
    """Typed create/read/update/delete for one model, each call in its own transaction::

        notes = Repository(db, Note)
        note = await notes.add(title="Hi", owner_id=user.id)
        mine = await notes.find(Note.owner_id == user.id, order_by=Note.created.desc(), limit=20)
        page = await notes.page(Note.owner_id == user.id, page=2, size=20)

    For anything else, use ``db.transaction()`` and SQLAlchemy directly.
    """

    def __init__(self, db: Database, model: type[M]) -> None:
        self.db = db
        self.model = model

    async def get(self, key: Any) -> M | None:
        async with self.db.session() as session:
            return await session.get(self.model, key)

    async def find(self, *where: Any, order_by: Any = None, limit: int | None = None, offset: int = 0) -> list[M]:
        query = select(self.model).where(*where).offset(offset)
        if order_by is not None:
            query = query.order_by(order_by)
        if limit is not None:
            query = query.limit(limit)
        async with self.db.session() as session:
            return list((await session.scalars(query)).all())

    async def count(self, *where: Any) -> int:
        async with self.db.session() as session:
            return int(await session.scalar(select(func.count()).select_from(self.model).where(*where)) or 0)

    async def page(self, *where: Any, page: int = 1, size: int = 20, order_by: Any = None) -> Paged[M]:
        if page < 1 or not 1 <= size <= 1000:
            raise ValueError("page starts at 1 and size is between 1 and 1000")
        items = await self.find(*where, order_by=order_by, limit=size, offset=(page - 1) * size)
        return Paged(items, await self.count(*where), page, size)

    async def add(self, **values: Any) -> M:
        async with self.db.transaction() as session:
            row = self.model(**values)
            session.add(row)
        return row

    async def update(self, key: Any, **values: Any) -> M | None:
        async with self.db.transaction() as session:
            row = await session.get(self.model, key)
            if row is None:
                return None
            for name, value in values.items():
                if not hasattr(self.model, name):
                    raise AttributeError(f"{self.model.__name__} has no column {name!r}")
                setattr(row, name, value)
        return row

    async def delete(self, key: Any) -> bool:
        async with self.db.transaction() as session:
            row = await session.get(self.model, key)
            if row is None:
                return False
            await session.delete(row)
        return True
